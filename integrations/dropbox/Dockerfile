# Sidecar image for the "dropbox" container in the hermes ECS task (see
# pulumi-hermes/src/service.py:_dropbox_container_definition). Runs Dropbox's
# own official headless Linux daemon so selective sync (used to hard-exclude
# the huge Shotwell folder) and two-way sync are Dropbox's own battle-tested
# code, not a reimplementation.
#
# Dropbox doesn't publish an official Docker image, and trusting an
# unofficial one for full-account access is a real supply-chain risk. This
# downloads the two official artifacts directly from Dropbox's own CDN and
# checksum-verifies them, the same pin-don't-trust-latest approach the main
# hermes-agent image uses for its own native dependencies (see ../../Dockerfile).
#
# Versions were resolved by following Dropbox's official "latest stable"
# redirect (https://www.dropbox.com/download?plat=lnx.x86_64) on 2026-10-06;
# bump DROPBOX_VERSION/_SHA256 the same way when updating.
FROM debian:13.4

ARG DROPBOX_VERSION=272.4.3798
ARG DROPBOX_TARBALL_SHA256=bf0b0945ace2c02fe790189fece8a2fa9c3a9c7e9fef879eb34b01098a957a01
ARG DROPBOX_PY_SHA256=c53a91d36566785bef88beb8b1fb3b1847a037d41e6ce2e26f1ceddf5a5c0342

RUN apt-get -o Acquire::Retries=3 update && \
    apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
        ca-certificates curl python3 procps && \
    rm -rf /var/lib/apt/lists/*

# Baked at a fixed, root-owned path (not under $HOME — that's the EFS mount,
# unavailable at build time). entrypoint.sh seeds $HOME/.dropbox-dist from
# here on first boot.
RUN curl -fsSL --retry 3 --retry-all-errors --connect-timeout 15 --max-time 300 \
        -o /tmp/dropbox.tar.gz \
        "https://edge.dropboxstatic.com/dbx-releng/client/dropbox-lnx.x86_64-${DROPBOX_VERSION}.tar.gz" && \
    printf '%s  /tmp/dropbox.tar.gz\n' "${DROPBOX_TARBALL_SHA256}" | sha256sum -c - && \
    mkdir -p /opt/dropbox-dist && \
    tar -xzf /tmp/dropbox.tar.gz -C /opt/dropbox-dist --strip-components=1 && \
    rm /tmp/dropbox.tar.gz && \
    chmod -R a+rX /opt/dropbox-dist

# dropbox.py is the control-script CLI (status / exclude add / exclude list /
# stop / start) used interactively via ECS Exec against the already-running
# daemon over its local control socket. It is not the main process.
RUN curl -fsSL --retry 3 --retry-all-errors --connect-timeout 15 --max-time 60 \
        -o /usr/local/bin/dropbox.py \
        "https://www.dropbox.com/download?dl=packages/dropbox.py" && \
    printf '%s  /usr/local/bin/dropbox.py\n' "${DROPBOX_PY_SHA256}" | sha256sum -c - && \
    chmod 0755 /usr/local/bin/dropbox.py

# uid/gid 10000 matches the EFS access point's enforced POSIX owner
# (pulumi-hermes/src/foundation.py's hermes access point) and the main
# hermes container's HERMES_UID/HERMES_GID, purely for consistency — the
# access point attributes every NFS operation through it to 10000:10000
# regardless of the requesting container's own uid.
RUN useradd -u 10000 -m -d /home/dropbox dropbox

COPY --chmod=0755 entrypoint.sh /usr/local/bin/dropbox-entrypoint.sh

USER 10000:10000
ENTRYPOINT ["/usr/local/bin/dropbox-entrypoint.sh"]
