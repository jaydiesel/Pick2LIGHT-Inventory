#!/usr/bin/env bash
# Update a Docker Compose install: back up, pull the new image, restart (migrations run on start).
set -euo pipefail
cd "$(dirname "$0")"

echo "Backing up before the update..."
docker compose exec -T -u p2l server pick2light backup
newest="$(ls -t "${P2L_BACKUP_DIR:-./backups}"/pick2light-*.tar.gz 2> /dev/null | head -1 || true)"

docker compose pull
docker compose up -d

port="$(grep -E '^P2L_HTTP_PORT=' .env 2> /dev/null | cut -d= -f2)"
for _ in $(seq 1 90); do
  if curl -fsS "http://127.0.0.1:${port:-80}/api/v1/health" 2> /dev/null | grep -q '"status":"ok"'; then
    echo "Update complete."
    exit 0
  fi
  sleep 1
done

echo "The server did not come back healthy." >&2
if [ -n "$newest" ]; then
  echo "Your pre-update backup is $(basename "$newest"). To restore it:" >&2
  echo "  docker compose exec -u p2l server pick2light restore /backups/$(basename "$newest") --yes" >&2
fi
docker compose logs --tail 50 server >&2
exit 1
