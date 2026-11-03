# Pick2LIGHT-Inventory

A self-hosted inventory for the home workshop — electronic parts, screws, wire, connectors,
individually tested Li-ion cells, spare computer parts, or anything else you store. It runs on a
Raspberry Pi or an old thin client and you use it from any browser on your home network.

**Pick2LIGHT** (coming in v0.2) lights a WS2812B LED on the drawer or bin that holds what you searched
for. Without LED hardware it is a complete inventory database.

## What v0.1 does

- **Your own categories and fields.** Categories form a tree and children inherit their parents' fields.
  Field types: text, numbers with units and SI prefixes (type `4k7`, `100n`, `22 mΩ`), choices, yes/no,
  dates, links, files.
- **Bulk or per-unit stock.** Count screws by the hundred, or track each 18650 cell, RAM stick or drive
  on its own with its own label, condition and **history log** (capacity tests, health checks, Memtest…).
- **Locations** in a tree of any depth: room › cabinet › drawer › bin.
- **SKUs from patterns**, e.g. `SCR-{thread}-{length}-{head}` → `SCR-M3-10-SHCS`.
- **Barcode scanning** with any USB or wireless scanner that types like a keyboard: find, check in,
  check out and use up items from any page.
- **Search** by name, SKU or value (`4.7k`, `10uF`), with filters like "IR < 30 mΩ in the latest test".
- **Labels** as PDFs (QR / Data Matrix / Code 128) for label printers or sticker sheets.
- **CSV import/export** (works with Excel's `;` files), full JSON export.
- **Undo** for every stock change, a **trash** for deletions, **nightly backups**.
- Optional password login; starter category packs for electronics, hardware, batteries and computer parts.

## Install with Docker

Needs Docker with the compose plugin, on a Raspberry Pi (64-bit OS) or any x86 Linux machine.

```bash
git clone https://github.com/jaydiesel/Pick2LIGHT-Inventory && cd Pick2LIGHT-Inventory/deploy/docker
cp .env.example .env   # set P2L_DB_PASSWORD
docker compose up -d --build
```

`--build` builds the image on your machine (a few minutes on a Pi). Once release images are published
to `ghcr.io/jaydiesel/pick2light-inventory`, plain `docker compose up -d` pulls them instead.

Open `http://<that-machine>/` and follow the setup wizard. To update later, run `deploy/docker/update.sh`
(it backs up first).

Backups land in `deploy/docker/backups/` by default (`P2L_BACKUP_DIR` in `.env`), and can be restored from the
Backups page or with `docker compose exec -u p2l server pick2light restore /backups/<file> --yes`.

## Development

- Server: Python 3.12, FastAPI, SQLAlchemy, PostgreSQL 16 — in `server/`, managed with [uv](https://docs.astral.sh/uv/).
- Web app: Vue 3 + TypeScript + Vite — in `web/`.

```bash
docker run -d --name p2l-pg -p 5432:5432 -e POSTGRES_PASSWORD=postgres postgres:16
cd server && uv sync && uv run pytest
P2L_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pick2light serve --port 8000
```

```bash
cd web && npm ci && npm run dev    # http://localhost:5173, proxies /api to :8000
npx vitest run && npm run lint && npm run typecheck
```

The design is in `docs/superpowers/specs/` and the build plan in `docs/superpowers/plans/`.

## License

GPL-3.0 — see [LICENSE](LICENSE).
