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
FILTERS=/opt/dropbox-filters.txt
INTERVAL="${BISYNC_INTERVAL_SECONDS:-300}"

mkdir -p "${MIRROR}" "${WORKDIR}"

while true; do
    if [ ! -e "${MARKER}" ]; then
        # First run: no prior baseline. --resync-mode path1 (the --resync
        # default) treats Dropbox as authoritative, which is moot here since
        # the local side starts empty anyway.
        if rclone bisync dropbox: "${MIRROR}" \
            --filters-file="${FILTERS}" --workdir="${WORKDIR}" --resync -v; then
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
            --filters-file="${FILTERS}" --workdir="${WORKDIR}" \
            --recover --resilient -v || \
            echo "bisync run failed; will retry in ${INTERVAL}s" >&2
    fi
    sleep "${INTERVAL}"
done
