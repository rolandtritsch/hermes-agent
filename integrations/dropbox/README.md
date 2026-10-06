# Dropbox sidecar image

This is a deployment artifact, not a Hermes connector: it builds a container
image for the non-essential `dropbox` sidecar in the `hermes` ECS task (see the
infrastructure [deployment runbook][deployment]). The sidecar runs Dropbox's own
official headless Linux daemon (`dropboxd`) against the same EFS volume the
`hermes` container mounts at `/opt/data`, so Hermes' existing file tools
(`tools/file_tools.py` et al.) can read/write the synced folder directly. There
is no MCP manifest, no plugin, and no Hermes application code involved — the
daemon and Hermes are two independent processes sharing a filesystem.

[Dockerfile](Dockerfile) downloads the two official Dropbox artifacts directly
from Dropbox's own CDN and checksum-verifies them (Dropbox publishes no official
Docker image, and trusting an unofficial one for full-account access is a real
supply-chain risk):

- `dropbox-lnx.x86_64-<version>.tar.gz` — the daemon itself, baked to the
  fixed, root-owned path `/opt/dropbox-dist`.
- `dropbox.py` — the control-script CLI (`status`, `exclude add`, `exclude
  list`, ...) used interactively over ECS Exec against the already-running
  daemon's local control socket; it is never the container's main process.

[entrypoint.sh](entrypoint.sh) seeds `$HOME/.dropbox-dist` from the baked copy
on first boot only (`$HOME` is the EFS mount, unavailable at build time; once
linked, that directory holds this install's host keys and must survive image
updates), then execs `dropboxd` in the foreground as PID 1.

## Updating the pinned version

`DROPBOX_VERSION`, `DROPBOX_TARBALL_SHA256`, and `DROPBOX_PY_SHA256` are build
args at the top of the Dockerfile. To bump them, follow Dropbox's official
"latest stable" redirect and recompute checksums:

```sh
curl -sIL "https://www.dropbox.com/download?plat=lnx.x86_64" | grep -i location
# https://edge.dropboxstatic.com/dbx-releng/client/dropbox-lnx.x86_64-<version>.tar.gz
curl -sL -o dropbox-lnx.tar.gz "<that URL>"
curl -sL -o dropbox.py "https://www.dropbox.com/download?dl=packages/dropbox.py"
sha256sum dropbox-lnx.tar.gz dropbox.py
```

## Build and publish

Build/push/pin steps live in the [deployment runbook][deployment], which also
covers the one-time account link and the Shotwell selective-sync exclude.

[deployment]: https://github.com/rolandtritsch/pulumi-hermes/blob/trunk/docs/dropbox.md
