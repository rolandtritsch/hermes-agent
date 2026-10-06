# Sidecar image for the "dropbox" container in the hermes ECS task (see
# pulumi-hermes/src/service.py:_dropbox_container_definition). Runs rclone's
# Dropbox backend in a bisync loop, syncing into the shared EFS volume.
#
# This replaces an earlier attempt at Dropbox's own official headless Linux
# daemon: that daemon links fine but refuses to sync onto any network
# filesystem ("Your Dropbox folder is on a file system that is no longer
# supported"), and EFS is NFS. rclone does plain file I/O and has no concept
# of a supported/unsupported local filesystem, so it doesn't hit that wall.
#
# Version pinned and checksum-verified against rclone's own published
# SHA256SUMS on 2026-10-06; bump both ARGs the same way when updating:
#   curl -s https://downloads.rclone.org/version.txt
#   curl -sL https://downloads.rclone.org/<version>/SHA256SUMS | grep linux-amd64.zip
FROM debian:13.4

ARG RCLONE_VERSION=v1.75.1
ARG RCLONE_ZIP_SHA256=982b5aa772841168f8e380f139e9e787b2a105403e32b94da8676a0e1c0a13ab

RUN apt-get -o Acquire::Retries=3 update && \
    apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
        ca-certificates curl unzip procps && \
    rm -rf /var/lib/apt/lists/*

RUN curl -fsSL --retry 3 --retry-all-errors --connect-timeout 15 --max-time 120 \
        -o /tmp/rclone.zip \
        "https://downloads.rclone.org/${RCLONE_VERSION}/rclone-${RCLONE_VERSION}-linux-amd64.zip" && \
    printf '%s  /tmp/rclone.zip\n' "${RCLONE_ZIP_SHA256}" | sha256sum -c - && \
    unzip -q /tmp/rclone.zip -d /tmp/rclone-extracted && \
    install -m 0755 /tmp/rclone-extracted/rclone-*-linux-amd64/rclone /usr/local/bin/rclone && \
    rm -rf /tmp/rclone.zip /tmp/rclone-extracted

# Hard-excludes a handful of large/irrelevant top-level folders (see
# filters.txt for the current list and how it was confirmed).
COPY filters.txt /opt/dropbox-filters.txt

# uid/gid 10000 matches the EFS access point's enforced POSIX owner
# (pulumi-hermes/src/foundation.py's hermes access point) and the main
# hermes container's HERMES_UID/HERMES_GID, purely for consistency — the
# access point attributes every NFS operation through it to 10000:10000
# regardless of the requesting container's own uid.
RUN useradd -u 10000 -m -d /home/dropbox dropbox

COPY --chmod=0755 entrypoint.sh /usr/local/bin/dropbox-entrypoint.sh

USER 10000:10000
ENTRYPOINT ["/usr/local/bin/dropbox-entrypoint.sh"]
