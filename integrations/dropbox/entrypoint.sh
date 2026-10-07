#!/bin/sh
# Runs rclone bisync on a loop as the container's main process. $HOME is the
# EFS mount (unavailable at build time), so rclone's config (default
# $HOME/.rclone.conf) and bisync's --workdir both land there automatically —
# set explicitly below anyway so a redeploy / container restart resumes the
# existing baseline instead of forcing a fresh --resync.
set -eu

MIRROR="${HOME}/Dropbox"
WORKDIR="${HOME}/.cache/rclone/bisync"
MARKER="${HOME}/.bisync-initialized"
INTERVAL="${BISYNC_INTERVAL_SECONDS:-300}"

# rclone writes a .md5 stamp of the filters file *next to* the filters file
# itself (to detect mid-run filter changes), but /opt is root-owned and
# read-only for this container's runtime user — writing there fails with
# "Bisync critical error: ... permission denied" (hit live in production).
# Copy the baked filters into the writable EFS home instead, same seed-from-
# image-into-EFS shape the dropboxd-era entrypoint used for .dropbox-dist.
FILTERS="${HOME}/dropbox-filters.txt"
cp /opt/dropbox-filters.txt "${FILTERS}"

mkdir -p "${MIRROR}" "${WORKDIR}"

while true; do
    if [ ! -e "${MARKER}" ]; then
        # First run: no prior baseline. --resync-mode path1 (the --resync
        # default) treats Dropbox as authoritative, which is moot here since
        # the local side starts empty anyway. --max-lock auto-expires a lock
        # left behind by a killed/crashed prior run (hit live: an abruptly
        # terminated run left a permanent lock that wedged every retry until
        # manually cleared) instead of requiring manual intervention forever.
        if rclone bisync dropbox: "${MIRROR}" \
            --filters-file="${FILTERS}" --workdir="${WORKDIR}" --max-lock 15m --resync -v; then
            touch "${MARKER}"
        else
            echo "Initial --resync failed; will retry in ${INTERVAL}s" >&2
        fi
    else
        # --recover / --resilient let an unattended loop ride out a
        # redeploy-interrupted run or a transient error without requiring a
        # human to re-run --resync. Deliberately no --force: bisync's own
        # mass-deletion abort stays active.
        rclone bisync dropbox: "${MIRROR}" \
            --filters-file="${FILTERS}" --workdir="${WORKDIR}" --max-lock 15m \
            --recover --resilient -v || \
            echo "bisync run failed; will retry in ${INTERVAL}s" >&2
    fi
    sleep "${INTERVAL}"
done
