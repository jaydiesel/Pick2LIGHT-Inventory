#!/usr/bin/env bash
# Build and start the Docker Compose stack, check it works, then tear it down.
# Usage: deploy/docker/smoke-test.sh   (needs Docker with the compose plugin)
set -euo pipefail
cd "$(dirname "$0")"

export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-p2l-smoke}"
export P2L_DB_PASSWORD="smoke-test-password"
export P2L_HTTP_PORT="${P2L_HTTP_PORT:-8088}"
export P2L_DB_PORT="${P2L_DB_PORT:-55432}"
export P2L_VERSION="smoke"
# Like a fresh install: the data and backup folders don't exist yet, so Docker creates them (as root).
WORK="$(mktemp -d)"
export P2L_DATA_DIR="${WORK}/data"
export P2L_BACKUP_DIR="${WORK}/backups"

cleanup() {
  docker compose --env-file /dev/null down -v > /dev/null 2>&1 || true
  rm -rf "$WORK" 2> /dev/null || true
}
trap cleanup EXIT

# Build the image (optionally with a CA bundle for TLS-inspecting proxies: P2L_BUILD_CA_BUNDLE=/path/ca.pem).
build_args=()
if [ -s "${P2L_BUILD_CA_BUNDLE:-}" ]; then
  build_args+=(--secret "id=ca_bundle,src=${P2L_BUILD_CA_BUNDLE}")
fi
docker build "${build_args[@]}" -f Dockerfile -t "ghcr.io/jaydiesel/pick2light-inventory:${P2L_VERSION}" ../..
docker compose --env-file /dev/null up -d

base="http://127.0.0.1:${P2L_HTTP_PORT}"
echo "Waiting for ${base}/api/v1/health ..."
for _ in $(seq 1 90); do
  if curl -fsS "${base}/api/v1/health" 2> /dev/null | grep -q '"status":"ok"'; then
    ok=1
    break
  fi
  sleep 1
done
if [ "${ok:-0}" != 1 ]; then
  echo "FAIL: server did not become healthy" >&2
  docker compose --env-file /dev/null logs --tail 50 >&2
  exit 1
fi

curl -fsS "${base}/" | grep -q '<div id="app">' || { echo "FAIL: web app not served" >&2; exit 1; }
curl -fsS -X POST -H 'Content-Type: application/json' \
  -d '{"auth_mode": "password", "password": "smoke-test-pw", "packs": ["generic"]}' \
  "${base}/api/v1/setup" > /dev/null || { echo "FAIL: setup wizard (password mode) failed" >&2; docker compose --env-file /dev/null logs --tail 30 server >&2; exit 1; }
curl -fsS "${base}/items/1" | grep -q '<div id="app">' || { echo "FAIL: SPA fallback missing" >&2; exit 1; }
docker compose --env-file /dev/null exec -T -u p2l server pick2light backup
ls "${P2L_BACKUP_DIR}"/pick2light-*.tar.gz > /dev/null || { echo "FAIL: backup file missing" >&2; exit 1; }
docker compose --env-file /dev/null ps --status running --services | grep -qx backup || { echo "FAIL: backup service not running" >&2; exit 1; }
echo "SMOKE TEST PASSED"
