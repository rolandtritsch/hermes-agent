# Dropbox sidecar image

This is a deployment artifact, not a Hermes connector: it builds a container
image for the non-essential `dropbox` sidecar in the `hermes` ECS task (see the
infrastructure [deployment runbook][deployment]). The sidecar runs
[rclone][rclone]'s Dropbox backend in a `bisync` loop against the same EFS
volume the `hermes` container mounts at `/opt/data`, so Hermes' existing file
tools (`tools/file_tools.py` et al.) can read/write the synced folder directly.
There is no MCP manifest, no plugin, and no Hermes application code involved —
rclone and Hermes are two independent processes sharing a filesystem.

An earlier version of this image ran Dropbox's own official headless Linux
daemon instead. That daemon links fine but refuses to sync onto any network
filesystem ("Your Dropbox folder is on a file system that is no longer
supported"), and EFS is NFS — a hard wall discovered live during deployment,
not a theoretical concern. rclone does plain file I/O and has no concept of a
supported/unsupported local filesystem, so it doesn't hit that wall.

[Dockerfile](Dockerfile) downloads the official rclone release zip and
checksum-verifies it against rclone's own published `SHA256SUMS` (rclone is
open-source and widely used as infrastructure tooling, unlike the
closed-source Dropbox daemon the previous version of this image avoided
trusting an unofficial build of). [filters.txt](filters.txt) hard-excludes a
handful of large/irrelevant top-level folders (`Shotwell`, `Archive`,
`Videos`, `Drobo`, `GoogleDrive` as of 2026-10-06) — confirmed top-level via
`rclone lsf dropbox:`, not guessed.

[entrypoint.sh](entrypoint.sh) runs as PID 1 and loops forever: the first run
passes `--resync` (no prior baseline exists) and drops a marker file in
`$HOME` on success; every run after that is a normal `bisync` with `--recover
--resilient` so an unattended loop can ride out a redeploy-interrupted run
without a human re-running `--resync`. `$HOME` is the EFS mount (unavailable at
build time), so rclone's config and bisync's `--workdir` (the prior-run
listings bisync diffs against) both land there automatically and survive
container restarts/redeploys.

## Updating the pinned rclone version

`RCLONE_VERSION` and `RCLONE_ZIP_SHA256` are build args at the top of the
Dockerfile:

```sh
curl -s https://downloads.rclone.org/version.txt
curl -sL "https://downloads.rclone.org/<version>/SHA256SUMS" | grep linux-amd64.zip
```

## Build, publish, and link

Build/push/pin steps and the rclone Dropbox authorization flow live in the
[deployment runbook][deployment].

[deployment]: https://github.com/rolandtritsch/pulumi-hermes/blob/trunk/docs/dropbox.md
[rclone]: https://rclone.org/
