#!/bin/sh
# Make sure the bind-mounted data and backup folders belong to the app user, then drop root.
# (A fresh `docker compose up` creates ./data and ./backups owned by root.)
set -e
if [ "$(id -u)" = "0" ]; then
  for dir in /data /backups; do
    mkdir -p "$dir"
    if [ "$(stat -c %u "$dir")" != "1000" ]; then
      chown -R p2l:p2l "$dir" 2> /dev/null || echo "warning: could not change the owner of $dir; make it writable for uid 1000" >&2
    fi
  done
  export HOME=/home/p2l
  exec setpriv --reuid=p2l --regid=p2l --init-groups pick2light "$@"
fi
exec pick2light "$@"
