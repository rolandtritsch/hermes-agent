#!/bin/sh
# Seeds $HOME/.dropbox-dist from the image-baked copy on first boot only, then
# runs the daemon in the foreground as the container's main process.
#
# The dist can't be baked directly under $HOME at build time: $HOME
# (/opt/data/integrations/dropbox/home) is an EFS mount, not available until
# the task runs. Copying unconditionally on every boot would also be wrong:
# once linked, .dropbox-dist holds this install's host keys, and a later
# image update (newer dropboxd bundled) must not silently clobber a live
# link's state.
set -eu

if [ ! -e "${HOME}/.dropbox-dist" ]; then
    mkdir -p "${HOME}"
    cp -a /opt/dropbox-dist "${HOME}/.dropbox-dist"
fi

exec "${HOME}/.dropbox-dist/dropboxd"
