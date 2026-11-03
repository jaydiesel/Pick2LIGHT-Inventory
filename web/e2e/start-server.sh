#!/usr/bin/env bash
# Start a fresh Pick2LIGHT server for the end-to-end tests (empty database, temp data dir).
set -euo pipefail
cd "$(dirname "$0")/../../server"
export P2L_DATABASE_URL="${P2L_E2E_DATABASE_URL:-postgresql+asyncpg://postgres:postgres@localhost:5432/p2l_e2e}"
export P2L_ALLOW_RESET=1
export P2L_WEB_DIST
P2L_WEB_DIST="$(cd ../web/dist && pwd)"
export P2L_DATA_DIR
P2L_DATA_DIR="$(mktemp -d)"
uv run python - <<'PY'
import asyncio, os
import asyncpg

url = os.environ["P2L_DATABASE_URL"].replace("+asyncpg", "")
base, name = url.rsplit("/", 1)

async def main():
    conn = await asyncpg.connect(base + "/postgres")
    try:
        if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name):
            await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()

asyncio.run(main())
PY
uv run pick2light reset-db --yes
exec uv run pick2light serve --host 127.0.0.1 --port "${P2L_E2E_PORT:-8765}"
