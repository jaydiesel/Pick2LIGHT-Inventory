# Pick2LIGHT-Inventory — Design Spec

- **Date:** 2026-11-03
- **Status:** Draft for owner review
- **License:** GPL-3.0 (repository license)

## 1. Purpose

Pick2LIGHT-Inventory is a self-hosted home inventory system. It starts with the owner's
needs — electronic components, fasteners, wire, connectors, individually tested Li-ion
cells and spare computer parts — but nothing about those domains is hard-coded. Any user
can define their own categories, fields, storage layout and labels.

Its signature feature, **Pick2LIGHT**, lights WS2812B LEDs on the storage location of an
item when it is searched or scanned. Pick2LIGHT is optional: without LED controllers the
system is a complete plain inventory database.

### 1.1 Success criteria

1. The owner can scan a homemade label on an 18650 cell and see that cell's full test
   history (capacity, internal resistance, storage voltage, dates) and its datasheet.
2. Searching for or scanning any item lights its drawer/bin within one second when its
   controller is online.
3. A new user with no LED hardware can install it, define their own categories and
   locations, and use it as an inventory database without touching code.
4. The server runs comfortably on a Raspberry Pi 4 (2 GB) or a repurposed x86 thin
   client.
5. New categories, fields, label layouts, location types and importers can be added by
   users or contributors without changing the core schema.

### 1.2 Constraints and decisions

| Topic | Decision |
|---|---|
| Users | Single owner/admin. Login optional. No multi-user roles in scope (schema leaves room). |
| Network | Home LAN only. No remote access, no internet exposure. |
| Database | PostgreSQL 16. |
| Server stack | Python 3.12, FastAPI, SQLAlchemy 2 (async, asyncpg), Alembic, Pydantic v2. |
| Web UI | Vue 3 + TypeScript + Vite + Pinia + Vue Router, PrimeVue components. Built to static files and served by the server. |
| Firmware | PlatformIO, Arduino framework, ESP32 / ESP32-S3 / ESP32-C3. |
| Server ↔ controller | WebSocket, JSON messages. Standalone; no MQTT or Home Assistant in scope. |
| Scanner | Wireless (2.4 GHz / Bluetooth) 1D/2D handheld acting as a keyboard; USB scanners also supported, either on the client device or on the server. |
| Labels | Niimbot B1 (primary label printer), any CUPS printer, PDF for regular printers. |
| Power | Controllers powered from 5 V USB; firmware enforces a current budget. |
| Install | Docker Compose (separate PostgreSQL container), Proxmox LXC script, bare-metal script. |

### 1.3 Non-goals (this spec)

- Multiple users, roles or permissions.
- Remote/internet access, cloud sync.
- MQTT / Home Assistant integration (possible future add-on).
- Phone-camera barcode scanning.
- Lighting a whole project/BOM pick list at once (possible future feature).
- Native mobile apps (the web UI is responsive instead).
- Valuation, accounting or sales features beyond recording purchase price.

## 2. Architecture

```
 ┌──────────────────────────── Home LAN ───────────────────────────────────┐
 │                                                                         │
 │  Browser (phone / PC / tablet)  ◄── HTTP /api/v1 + WS /api/v1/events ──┐│
 │  Wireless or USB scanner acts as keyboard into the page                ││
 │                                                                        ▼│
 │        ┌──────────────── Server host (Pi / thin client / LXC) ──────────┐│
 │        │ pick2light-server (FastAPI, single process)                    ││
 │        │  ├─ Core inventory service                                     ││
 │        │  ├─ REST API + browser event WebSocket                         ││
 │        │  ├─ Scan Router            ◄── evdev USB scanner (optional)    ││
 │        │  ├─ Light Manager          ─── WS /ws/controller ──────────────┼┼──► ESP32 controllers ─► WS2812B
 │        │  ├─ Label Service          ──► Niimbot B1 (USB/BT) / CUPS / PDF││
 │        │  ├─ Importers (plugins)    ◄── AliExpress userscript, CSV, ... ││
 │        │  ├─ Backup job                                                 ││
 │        │  └─ Static web UI                                              ││
 │        │ PostgreSQL 16                                                  ││
 │        └────────────────────────────────────────────────────────────────┘│
 └─────────────────────────────────────────────────────────────────────────┘
```

### 2.1 Components

Each component has one responsibility and talks to others only through the interfaces
listed.

| Component | Responsibility | Interface |
|---|---|---|
| **Core inventory** | Categories, fields, items, units, stock, locations, history log, movements, barcodes, attachments. Validation of custom field values. | Python service layer used by API, Scan Router and Importers. |
| **REST API** | Everything the UI can do. OpenAPI docs at `/api/docs`. | HTTP JSON under `/api/v1`. |
| **Event hub** | Pushes scan results, light state and controller status to open browsers. | WS `/api/v1/events`. |
| **Scan Router** | Accepts a raw scanned string from any source, classifies it, executes it according to the current scan mode. | `handle_scan(code, source, session) -> ScanResult`. |
| **Light Manager** | Tracks controllers and active lights; resolves "light location X for reason Y" to per-controller LED commands; colours, timeouts, power budget. | `light(location_ids, reason, request_id)`, `clear(request_id)`, controller WS. |
| **Label Service** | Renders a label template to an image and sends it to a printer backend or PDF. | `render(template, target) -> Image`, `print(job)`; printer backend plugins. |
| **Importers** | Turn external data (supplier bag codes, supplier APIs, AliExpress, product URLs, CSV) into import-inbox entries. | Importer plugin interface (§9). |
| **Backup job** | Scheduled database + attachment backups and retention. | Settings + CLI `pick2light backup`. |
| **Firmware** | Wi-Fi, server link, LED driving, local timeouts, OTA. | Controller protocol (§7). |

### 2.2 Repository layout

```
server/            FastAPI app, services, Alembic migrations, tests
  pick2light/
    api/           routers
    core/          inventory services, field engine, SKU engine, units parser
    scan/          scan router, classifiers, evdev reader
    lights/        light manager, controller WS handler, virtual controller
    labels/        templates, renderer, printer backends (niimbot, cups, pdf)
    importers/     plugin base + digikey, mouser, lcsc, aliexpress, link, csv
    backup/
web/               Vue 3 app
firmware/          PlatformIO project
deploy/
  docker/          Dockerfile, docker-compose.yml
  install.sh       bare-metal installer (Debian / Raspberry Pi OS / Ubuntu)
  proxmox/         LXC creation script (calls install.sh inside the container)
  userscripts/     AliExpress userscript
docs/              user docs, wiring guide, specs
```

## 3. Data model

All tables have `id` (bigint identity), `created_at`, `updated_at`. Tables marked
*soft-delete* have `deleted_at` and are hidden unless restoring from Trash.

### 3.1 Definitions

**`category`** *(soft-delete)*
- `parent_id` → category (nullable; tree)
- `name`, `icon`, `description`
- `tracking_mode`: `bulk` | `unit` (inherited from parent unless set)
- `sku_pattern` (nullable; see §4.2), `sku_prefix`
- `unit_id_pattern` (unit mode only)
- `default_label_template_id`, `default_unit_label_template_id`

**`field_definition`**
- `category_id` → category
- `key` (snake_case, unique across the category's ancestor chain and descendants)
- `label`, `help_text`, `order`
- `type`: `text` | `long_text` | `number` | `select` | `multi_select` | `boolean` |
  `date` | `url` | `file`
- `scope`: `item` | `unit` (unit scope only valid in unit-tracked categories)
- `required` (bool), `filterable` (bool), `show_on_label` (bool)
- `number_unit` (e.g. `Ω`, `F`, `mAh`, `mΩ`, `mm`), `number_si_prefixes` (bool),
  `min`, `max`, `decimals`
- `options` (JSONB, for select types): `[{value, label, sku_code}]`

Child categories inherit all ancestor field definitions. A child may not redefine an
inherited key.

**`log_entry_type`** *(soft-delete)*
- `category_id` → category (inherited by child categories)
- `key` (snake_case, e.g. `capacity_test`; used in templates and filters), `name` (e.g.
  "Capacity Test"), `icon`
- `applies_to`: `unit` | `item`
- `fields` (JSONB array, same shape as `field_definition` minus `scope`)
- `summary_fields` (array of field keys shown as "latest values" on the unit/item page
  and available as filters)

**`location_type`**: `name`, `icon`.

**`label_template`**: `name`, `width_mm`, `height_mm`, `dpi` (default 203),
`target`: `item` | `unit` | `location` | `command`, `layout` (JSONB, §8.1).

**`settings`**: `key` (text PK), `value` (JSONB).

**`user`**: `username`, `password_hash` (argon2). Exactly one row in this scope.

### 3.2 Inventory

**`item`** *(soft-delete)* — a product / SKU.
- `category_id`, `name`, `sku` (unique), `description`, `notes`
- `attrs` (JSONB) — values for item-scope fields, keyed by field key
- `min_stock` (nullable int), `default_location_id` (nullable)
- `photo_attachment_id` (nullable)
- `search_vector` (tsvector, maintained by a trigger from name, sku, description and
  text values of `attrs`)

**`stock`** — bulk quantity per location.
- `item_id`, `location_id`, `quantity` (numeric, ≥ 0), unique (`item_id`, `location_id`)

**`unit`** *(soft-delete)* — one physical thing in a unit-tracked category.
- `item_id`, `unit_code` (unique, e.g. `C0042`), `serial_number` (nullable)
- `location_id` — where the unit lives; kept while `checked_out` so check-in returns
  it home; null once `consumed` or `disposed`
- `condition`: `new` | `tested_good` | `untested` | `faulty` | `for_parts`
- `status`: `in_stock` | `checked_out` | `consumed` | `disposed`
- `attrs` (JSONB) — values for unit-scope fields

**`log_entry`**
- `log_entry_type_id`, `unit_id` (nullable), `item_id` (nullable; exactly one set)
- `performed_at` (timestamptz), `values` (JSONB), `notes`
- Check constraint: exactly one of `unit_id` / `item_id` is set.

A view **`unit_latest_values`** uses `DISTINCT ON (unit_id, log_entry_type_id)` ordered
by `performed_at DESC` to expose the newest summary values per unit. (An equivalent view
exists for items.)

**`stock_movement`** — append-only audit trail.
- `item_id`, `unit_id` (nullable)
- `from_location_id`, `to_location_id` (nullable each)
- `quantity_delta` (numeric; for units ±1)
- `reason`: `create` | `import` | `check_out` | `check_in` | `consume` | `move` |
  `adjust` | `stocktake` | `undo`
- `source`: `ui` | `scan` | `import` | `api` | `stocktake`
- `reverses_movement_id` (nullable), `note`

Undo creates a new movement with `reason = undo` and `reverses_movement_id` set; history
is never rewritten.

**`barcode`**
- `code` (text, unique, stored exactly as scanned after trimming)
- `target_type`: `item` | `unit` | `location`, `target_id`
- `kind`: `sku` | `unit_code` | `location_code` | `manufacturer` | `supplier` | `custom`

SKUs, unit codes and location codes are inserted here automatically so all lookups use
one table.

**`attachment`**
- `owner_type`: `item` | `unit` | `location` | `log_entry` | `category`, `owner_id`
- `kind`: `photo` | `datasheet` | `document` | `other`
- `filename`, `content_type`, `size_bytes`, `sha256`, `storage_path` (relative to the
  attachments directory) **or** `url` for linked external datasheets

**`purchase_source`**
- `item_id`, `supplier` (text), `url`, `supplier_part_number`, `manufacturer_part_number`
- `unit_price`, `currency`, `pack_quantity`, `last_ordered_at`, `order_reference`

### 3.3 Places and hardware

**`location`** *(soft-delete)*
- `parent_id` (nullable; tree), `location_type_id`, `name`, `code` (unique, e.g.
  `LOC-0031`), `notes`, `photo_attachment_id`
- `light_children`: `inherit` | `on` | `off` (global default setting
  `lights.light_children_default = off`)
- `grid_row`, `grid_col` (nullable; set by the grid wizard for layout display)

**`controller`**
- `name`, `device_id` (unique; derived from MAC), `state`: `pending` | `approved` |
  `disabled`
- `token_hash` (set on approval)
- `chip` (`esp32` | `esp32s3` | `esp32c3`), `firmware_version`, `max_outputs` (reported)
- `outputs` (JSONB): `[{index, gpio, led_count, color_order, name}]`
- `power_limit_ma` (default 1800), `brightness` (0–255, default 128),
  `night_dim` (JSONB: `{enabled, start, end, brightness}`)
- `last_seen_at`, `last_ip`

**`led_segment`**
- `location_id`, `controller_id`, `output_index`, `start_led`, `led_count`
- A location may have several segments, possibly on different controllers.

### 3.4 Imports

**`import_inbox`**
- `source` (importer id), `status`: `new` | `matched` | `applied` | `dismissed`
- `raw` (JSONB), `parsed` (JSONB: name, quantity, mpn, supplier pn, price, image url,
  url, order ref, suggested category, attributes)
- `matched_item_id` (nullable), `applied_movement_id` (nullable)

### 3.5 Custom field storage and querying

- Field values live in `item.attrs`, `unit.attrs` and `log_entry.values` as JSONB.
- `number` values are stored as plain JSON numbers in the base unit (e.g. `4700` for
  4.7 kΩ, `0.022` for 22 mΩ when `number_unit = Ω`; when `number_unit = mΩ` the stored
  number is in mΩ). The base unit is whatever `number_unit` says; SI prefixes only
  affect input parsing and display.
- `select` stores the option `value`; `multi_select` stores an array of values;
  `date` stores ISO `YYYY-MM-DD`; `file` stores an attachment id.
- Every write is validated against the merged field definitions for the category
  (Pydantic model built at runtime and cached per category version).
- Indexes: GIN (`jsonb_path_ops`) on `item.attrs` and `unit.attrs`; GIN on
  `item.search_vector`; `pg_trgm` GIN on `item.name` and `item.sku`. Numeric filters
  cast `(attrs->>'key')::numeric`. This is sufficient for tens of thousands of items on a
  Pi; per-field expression indexes are a later optimisation, not in scope.

## 4. Core behaviours

### 4.1 Engineering-unit parser

Parses input like `4.7k`, `4k7`, `100n`, `100nF`, `2.2u`, `2.2µ`, `22 mΩ`, `1M`, `3000`
into a number in the field's base unit. Supported prefixes: p n u/µ m k M G. `m` is milli
and `M` is mega (case-sensitive). The `4k7` form (prefix as decimal point) is supported.
Display formats with the closest prefix and the field's `decimals`.

### 4.2 SKU and unit-code patterns

Pattern tokens:

| Token | Meaning |
|---|---|
| `{prefix}` | category `sku_prefix` |
| `{field_key}` | field value; for selects, the option's `sku_code` if set, else its value |
| `{field_key\|upper}` / `\|lower` | case transform |
| `{field_key\|si}` | number formatted with its SI prefix, no spaces, prefix case preserved (`4700` → `4.7k`, `0.022` → `22m`, `1000000` → `1M`) |
| `{seq:N}` | per-category sequence zero-padded to N digits |
| `{sku}` | (unit-code patterns only) the parent item's SKU |

Text and select tokens are upper-cased; `|si` tokens keep their prefix case so milli
(`m`) and mega (`M`) stay distinct. Spaces are removed and characters outside
`[A-Za-z0-9._-]` are replaced with `-`. If the generated SKU already exists, `-2`, `-3`… is appended. SKUs can always
be overridden by hand. Defaults: SKU pattern `{prefix}-{seq:4}`; unit-code pattern
`{prefix}{seq:4}`.

Examples (starter templates): `SCR-{thread}-{length}-{head}` → `SCR-M3-10-SHCS`;
`CELL-{format}-{model}` → `CELL-18650-30Q`; unit code `C{seq:4}` → `C0042`.

### 4.3 Stock operations

All stock changes go through one service function that writes `stock`/`unit` and a
`stock_movement` row in the same transaction.

- **Bulk:** add, remove (check out / consume), move between locations, adjust to a
  counted value. Quantity may not go below zero; the API rejects it.
- **Unit:** check out (status `checked_out`, location kept as "home"), check in,
  consume/dispose, move, change condition.
- **Low stock:** an item is low when the sum of its bulk stock (or count of
  `in_stock` units) is below `min_stock`. Low-stock items appear on the dashboard and
  the Reorder list.

### 4.4 Search

One search box. Query terms match against `search_vector` (full text), trigram
similarity on name and SKU, exact matches in `barcode.code`, and text values in `attrs`.
Results are ranked: exact barcode/SKU match first, then full-text rank combined with
trigram similarity. Structured filters (category, location subtree, condition, field
comparisons such as `ir_mohm < 30`, latest log values) are applied on top.

### 4.5 Trash

Soft-deleted categories, items, units, log entry types and locations appear in Trash
for 30 days (setting) and can be restored. Deleting a location that still holds stock
or units is refused until it is emptied or its contents are moved.

## 5. Scanning

### 5.1 Input sources

1. **Browser keyboard wedge.** A global listener in the web app detects scans by timing:
   ≥ 4 characters with inter-key gaps ≤ 30 ms terminated by Enter (both thresholds are
   settings). An optional scanner prefix/suffix (settings) makes detection exact. When
   focus is in a text input that is not the search box, a detected scan is still
   intercepted and routed (setting to disable). Detected codes are POSTed to
   `/api/v1/scan`.
2. **Server USB scanner.** `python-evdev` grabs configured input devices exclusively
   (`scanner.server_devices` setting; picked from a list in the UI), maps key codes to
   characters using a configured keyboard layout (default US), and calls the Scan Router.
   Results are broadcast on the event hub so any open page reacts.
3. **Batch upload.** In Stocktake mode the page collects all detected scans (including
   a burst replayed from the scanner's offline storage) into a list instead of executing
   them. See §5.4.

### 5.2 Classification order

The Scan Router normalises the code (trim whitespace; keep GS `\x1d` / RS `\x1e`
characters) and classifies in this order; the first match wins:

1. **Command** — prefix `CMD:` (e.g. `CMD:CHECKOUT`).
2. **Known barcode** — exact match in `barcode.code` (case-sensitive first; a
   case-insensitive match is used only if it is unique).
3. **Supplier code** — each importer's `match_scan(code)` is asked in turn (§9.2).
4. **Unknown** — returned to the UI with options "Create item with this barcode" /
   "Attach to existing item, unit or location". Stored in a recent-unknown-scans list
   (last 50).

### 5.3 Scan modes and commands

The scan session (per browser tab, or one shared session for the server scanner) has a
mode, a pending quantity and a timeout (default 60 s back to `find`).

| Command | Effect |
|---|---|
| `CMD:FIND` | Mode `find` (default). |
| `CMD:CHECKOUT` | Mode `check_out`. |
| `CMD:CHECKIN` | Mode `check_in`. |
| `CMD:PUTAWAY` | Mode `put_away`. |
| `CMD:CONSUME` | Mode `consume`. |
| `CMD:QTY-<n>` | Quantity for the next bulk operation (default 1). |
| `CMD:DONE` | Clear all lights for this session. |
| `CMD:CANCEL` | Reset mode, quantity and any pending put-away. |
| `CMD:STOCKTAKE` | Open stocktake collection in the UI. |

Behaviour when an item/unit/location is scanned:

| Mode | Item (bulk) | Unit | Location |
|---|---|---|---|
| `find` | Open item, light all its stock locations | Open unit, light its location | Open location, light it (children per `light_children`) |
| `check_out` | Remove qty from the only location, or prompt if several | Mark checked out | — (error) |
| `check_in` | Add qty to default location (prompt if none) | Mark in stock at home location | — |
| `put_away` | Light default location green; next location scan sets where qty goes | Light home location green; next location scan moves it there | Completes a pending put-away |
| `consume` | Remove qty (reason `consume`) | Mark consumed | — |

Scanning the same unit/item again while it is lit in `find` mode clears its light
("picked").

### 5.4 Stocktake

1. User opens Stocktake, optionally scoped to a location subtree.
2. All scans are collected into a list (code, count, time). A burst of rapid scans is
   accepted without loss: the listener buffers characters and splits on the terminator.
3. The server classifies each code and produces a proposal: per item/location counted
   quantity vs. recorded, units found/missing, unknown codes.
4. Conflicts are flagged (negative results, unit scanned in two locations, unknown
   codes). Nothing is applied until the user confirms.
5. Apply writes `stocktake` movements in one transaction.

### 5.5 Known risk: control characters

Digi-Key/Mouser 2D codes use ASCII GS/RS separators. Some keyboard-wedge scanners drop
or remap them depending on configuration. Mitigations: documentation for configuring the
scanner's control-character output; parsers tolerate missing separators by splitting on
known data-identifier prefixes; the server evdev path receives raw characters when the
scanner sends them as key combinations.

## 6. Light Manager

### 6.1 Light requests

`light(location_ids, reason, request_id, session_id)`:

1. Expand locations: include descendants when the effective `light_children` is `on`.
2. Collect `led_segment`s; group by controller.
3. Choose colour from the reason and the session's palette slot:
   - reasons: `find` (default blue `#0050FF`), `put_away` (green `#00C850`),
     `low_stock` (amber `#FFA000`), `error` (red `#FF0000`), `identify` (white).
   - Concurrent `find` requests from different sessions/requests get distinct colours
     from a configurable palette (blue, magenta, cyan, yellow, …).
4. Effect: `solid` | `blink` | `pulse` (setting per reason; default `pulse` for find).
5. Timeout: per reason (default 30 s find, 60 s put-away).
6. Send `light` to each online controller; record the active request in memory.
7. Report per-location status to the browser: `lit`, `controller_offline`,
   `no_leds`.

Requests for offline controllers are held for 60 s (setting) and sent if the controller
reconnects within that window.

`clear(request_id)` / `clear_session(session_id)` / `clear_all()` send `clear` messages.
Active lights are in-memory only; on server restart controllers time out on their own.

### 6.2 Power budget

The server sends `power_limit_ma` and `brightness` in `config`; the **firmware** enforces
the budget (§7.4), because it knows exactly what is lit. The UI shows an estimate when
configuring outputs.

### 6.3 Virtual controller

A built-in simulated controller (enabled from the UI) registers through the same
protocol code path. The UI renders its outputs as on-screen LED strips. It is used for
demos, development and automated tests.

### 6.4 Setup tools

- **Grid wizard:** inputs: parent location, rows, columns, location type, name pattern
  (e.g. `{row_letter}{col}` → `A1`), controller + output, first LED, LEDs per cell,
  start corner (TL/TR/BL/BR), wiring order (row-major or column-major), serpentine
  (yes/no), LEDs skipped between cells. Creates the locations and segments in one
  transaction and previews the mapping before saving.
- **Walk-through mapping:** the UI lights LED *n* (`test_led`) on a chosen output; the
  user clicks the location it belongs to, or "skip", and advances.
- **Identify:** blink a whole controller or a single location.

## 7. Controller protocol and firmware

### 7.1 Discovery and onboarding

1. Fresh controller with no Wi-Fi credentials starts an AP `Pick2LIGHT-Setup-XXXX`
   with a captive portal (WiFiManager) to enter Wi-Fi and, optionally, a server
   address.
2. Without a configured address it discovers the server via mDNS service
   `_pick2light._tcp` (advertised by the server with `zeroconf`).
3. It connects to `ws://<server>/ws/controller` and sends `hello` without a token. The
   server creates a `pending` controller visible in the UI.
4. The user approves it (and names it). The server generates a random token, stores its
   hash and sends `welcome {token}`; the controller saves the token in NVS. Subsequent
   `hello` messages must include the token; mismatches are rejected and logged.
5. Holding the BOOT button for 10 s erases Wi-Fi and token (factory reset).

### 7.2 Messages

All messages are JSON objects with `"v": 1` (protocol version) and `"t"` (type). The
server accepts the current and previous protocol versions.

Controller → server:

| `t` | Fields |
|---|---|
| `hello` | `device_id`, `chip`, `fw`, `max_outputs`, `token?` |
| `heartbeat` | `uptime_s`, `rssi`, `free_heap` (every 15 s) |
| `ack` | `id` (message id being acknowledged), `ok`, `error?` |
| `ota_status` | `state` (`downloading` / `success` / `failed`), `progress`, `error?` |

Server → controller (each has `id` for acks):

| `t` | Fields |
|---|---|
| `welcome` | `token` (first approval only) |
| `config` | `outputs[]`, `brightness`, `power_limit_ma`, `night_dim` |
| `light` | `req`, `segments[{o, s, n}]`, `color` (`#RRGGBB`), `effect`, `timeout_ms` |
| `clear` | `req` |
| `clear_all` | — |
| `identify` | `duration_ms` |
| `test_led` | `o`, `i`, `color` |
| `ota` | `url`, `sha256`, `version` |

After every (re)connect the server sends `config` and then re-sends `light` for all
active requests touching that controller (remaining timeout).

### 7.3 Firmware structure

- Libraries: NeoPixelBus (RMT driver, multiple outputs), WiFiManager, arduinoWebSockets,
  ArduinoJson, ESPmDNS, Update/HTTPUpdate.
- Max outputs per chip are limited by available RMT channels and reported in `hello`.
- Active lights stored locally with their own expiry; expired or cleared requests are
  removed and the strip is re-rendered. Overlapping segments: most recent request wins.
- Reconnect with exponential backoff (1 s → 30 s max). LEDs keep their timeouts while
  disconnected.
- Status LED (on-board or LED 0 when configured): slow blink = no Wi-Fi, fast blink = no
  server, off = connected.
- OTA: downloads over HTTP from the server, verifies SHA-256, writes the inactive app
  partition, reboots; rollback if the new image does not reach `welcome`/`config`
  within 60 s.

### 7.4 Power budget algorithm

Estimated current per LED = `(R + G + B) / 255 × 20 mA` after brightness scaling, plus
1 mA quiescent per configured LED. If the total exceeds `power_limit_ma`, the firmware
scales the global brightness down proportionally for that frame.

### 7.5 Wiring guidance (docs)

330 Ω series resistor on data, 1000 µF capacitor across 5 V/GND at the strip, common
ground, level shifter (74AHCT125) or sacrificial first pixel for long data runs, power
injection for long strips, and a supply sized for the configured power limit.

## 8. Labels and printing

### 8.1 Templates

`label_template.layout` is a list of elements positioned in millimetres:

- `barcode`: `symbology` (`qr`, `datamatrix`, `code128`, `ean13`), `value` (template
  string, e.g. `{unit_code}`), `x`, `y`, `size`/`width`/`height`.
- `text`: `value` (template string, e.g. `{name}` or `{format} · {capacity|si}mAh ·
  {latest.capacity_test.ir_mohm}mΩ`), `x`, `y`, `w`, `h`, `font_size`, `bold`, `align`,
  `max_lines`.
- `image`: attachment or item photo, `x`, `y`, `w`, `h`.
- `line` / `box`.

Template strings can reference item/unit/location fields, `attrs`, `latest.<log type
key>.<field>` and `location.path`. A visual editor with live preview is part of v0.3;
v0.1 ships fixed default templates that can be edited as JSON.

Starter sizes include the Niimbot B1 label sizes 50×30, 40×30, 30×15 mm and a
cell-wrap label, plus A4/Letter sheet layouts (Avery-style grids) for PDF output.

### 8.2 Rendering and backends

- Rendering: Pillow at the template DPI, 1-bit dithering for thermal printers.
  Barcodes via `segno` (QR), `pylibdmtx` (Data Matrix) and `python-barcode` (1D).
- **PDF backend** (v0.1): single labels or sheets; printed from the browser to any
  printer.
- **Niimbot backend** (v0.3): server-side over USB serial or Bluetooth, using the
  open-source Niimbot protocol (the `niimprint` implementation, adapted/vendored after
  confirming licence compatibility with GPL-3.0). Supports B1 first; others where the
  protocol matches.
- **CUPS backend** (v0.3): any printer configured in CUPS on the server host.
- **Browser-direct Niimbot** (optional, v0.3): via the NiimBlue library over Web
  Bluetooth/Web Serial in Chrome/Edge. Requires HTTPS (a secure context), so it is only
  available when HTTPS is enabled (§10.4).
- Print jobs are queued with status (`queued`, `printing`, `done`, `failed`), retryable
  from the UI.

## 9. Importers

### 9.1 Plugin interface

```python
class Importer(Protocol):
    id: str                      # "digikey", "aliexpress", ...
    name: str
    def match_scan(self, code: str) -> ParsedImport | None: ...     # optional
    async def lookup(self, parsed: ParsedImport) -> ParsedImport: ... # optional enrich
    async def from_url(self, url: str) -> ParsedImport | None: ...    # optional
```

`ParsedImport` holds name, quantity, manufacturer, MPN, supplier, supplier part number,
unit price, currency, product URL, image URL, order reference, datasheet URL,
attribute suggestions and a category suggestion. Importers are registered via Python
entry points (`pick2light.importers`) so third-party packages can add more.

### 9.2 Built-in importers

| Importer | Release | Notes |
|---|---|---|
| CSV | v0.1 | Upload, map columns to fields (including custom fields), preview, import. Export of items/units/locations/stock/log to CSV and full JSON. |
| Digi-Key | v0.4 | Parses ECIA/ISO-15434 2D bag codes (data identifiers `P`, `1P`, `Q`, `K`, `1K`, `10K`, …). Optional enrichment via Digi-Key API (user-supplied client id/secret). |
| Mouser | v0.4 | Parses Mouser 2D bag codes (ECIA format). Optional enrichment via Mouser Search API key. |
| LCSC | v0.4 | Parses LCSC QR (`{pc:C…,pm:…,qty:…,on:…}` style). Enrichment from LCSC product page data where reachable. |
| AliExpress | v0.4 | Userscript (Tampermonkey/Violentmonkey) on the AliExpress orders and product pages. Reads order lines (title, variant, quantity, price, image, order number, product URL) from the page the user is viewing in their own logged-in session and sends them with `GM_xmlhttpRequest` to `/api/v1/import/inbox` using an import API token. `GM_xmlhttpRequest` is required because a normal page script cannot call an `http://` LAN server from an `https://` page. No server-side scraping of AliExpress. |
| Generic link | v0.4 | Server fetches a pasted URL and extracts OpenGraph/JSON-LD product data. Best effort; on failure the inbox entry is pre-filled with the URL only. |

### 9.3 Import inbox flow

Every import lands in `import_inbox`. For each entry the user: confirms/changes the
suggested category, edits fields, matches to an existing item (adds stock) or creates a
new one (SKU generated), picks a location, then applies. Applying writes the item,
stock/units, `purchase_source` and an `import` movement, optionally prints labels and
lights the location for put-away. Category suggestion v0.4 uses keyword rules
configurable per category (e.g. "M3", "screw", "bolt" → Screws).

### 9.4 Reorder list

Lists low-stock items with their purchase sources (supplier, last price, link). Opening a
link goes straight to the original listing.

## 10. Web UI

### 10.1 Screens

- **Dashboard:** search box, recent scans, low-stock items, controller status, lit
  locations with "Done".
- **Search / item list:** results with filters (category, location, field filters,
  condition, latest test values).
- **Item page:** fields, stock per location, units table (for unit-tracked), history
  log, attachments (datasheets/photos), purchase sources, movement history with undo,
  Find / Check in / Check out / Print label buttons.
- **Unit page:** unit fields, condition/status, latest values summary, full log with
  "Add entry", attachments, location, Find, Print label.
- **Locations:** tree view, grid view for wizard-created cabinets, contents, LED
  segments, Find, Print location labels.
- **Categories:** tree, field editor, log entry type editor, SKU/unit-code patterns,
  tracking mode, label defaults.
- **Controllers:** pending/approved list, outputs editor, power/brightness/night-dim,
  identify, LED mapping tools, firmware update.
- **Labels:** templates, print queue, command-barcode sheet (PDF).
- **Import:** CSV import/export, import inbox (v0.4).
- **Stocktake.**
- **Settings:** login on/off and password, scanner detection, colours/effects/timeouts,
  `light_children` default, backup schedule/destination, units display, trash retention.
- **Trash.**

The UI is responsive (phone-first for scanning workflows) and supports light/dark
themes.

### 10.2 Starter templates

On first run a setup wizard offers starter category packs, each optional:

- **Electronics:** Resistors, Capacitors, Inductors, Diodes, Transistors, ICs, Modules
  (fields: value with SI units, package, tolerance, voltage, MPN, datasheet).
- **Hardware:** Screws/Bolts, Nuts, Washers, Standoffs (thread, length, head, drive,
  material); Wire (AWG, colour, solid/stranded, insulation, length on spool);
  Connectors (family, pins, pitch, gender).
- **Batteries:** Li-ion Cells, unit-tracked (format, brand, model, rated capacity,
  chemistry; unit fields: wrap colour, source; log type "Capacity Test": date,
  capacity mAh, IR mΩ, storage voltage V, tester, notes).
- **Computer parts:** RAM (generation, capacity, speed, form factor, ECC/registered,
  MPN; log "Memtest"), CPUs (socket, model, cores/threads, TDP; log "Bench Test"),
  PCIe cards (card type, slot width, chipset), Drives (type, capacity, interface, form
  factor; log "Health Check": power-on hours, reallocated sectors, health %, wiped),
  Peripherals (device type, connection, model). All unit-tracked.
- **Generic:** a single "General" category with no extra fields.

Location types seeded: Room, Cabinet, Drawer, Shelf, Bin, Tote, Box.

### 10.3 Authentication

Setting `auth.mode`: `password` or `none`. The first-run wizard asks, with `password`
preselected; it can be changed later in Settings.
Password mode uses a session cookie (HTTP-only, SameSite=Lax) and argon2 hashing.
Importer userscripts and scripts use per-token API keys created in Settings. The
controller WebSocket always uses controller tokens regardless of `auth.mode`.

### 10.4 HTTPS (optional)

HTTP on the LAN is the default. Installers offer an optional self-signed HTTPS mode
(server serves TLS directly using a generated certificate) for features that need a
secure context in the browser (Web Bluetooth/Web Serial printing). Controllers keep
using `ws://` on a separate plain port in this mode.

## 11. Error handling

| Situation | Behaviour |
|---|---|
| Controller offline on Find | Location path is shown with "controller offline"; request held for 60 s and sent on reconnect. |
| Wi-Fi drop / power flicker | Firmware reconnects with backoff; server resends `config` and active lights; firmware times out LEDs locally. |
| Unknown scan | UI prompts to create/attach; kept in recent unknown scans. |
| Scan in wrong mode (e.g. location in check-out) | Error toast, red light on the scanned location if it has LEDs, mode unchanged. |
| Negative stock | Rejected by service layer with a clear message. |
| Stocktake conflicts | Flagged in review; nothing applied until confirmed. |
| Printer unavailable | Job stays queued as failed with reason; retry; PDF always available. |
| Importer/lookup failure | Inbox entry pre-filled with what is known; error noted on the entry. |
| Validation errors | API returns 422 with per-field messages; UI shows them inline. |
| Mistaken edit | Undo from movement history; Trash for deletions. |
| Migration failure on update | Update aborts; pre-update backup is kept and the restore command is printed. |
| Database unreachable | Server health endpoint reports it; UI shows a banner; server retries connection. |

The server exposes `/api/v1/health` (database, controllers, printers, backup status).

## 12. Backups

- Scheduled job (default nightly 03:00, setting) creates
  `pick2light-YYYYMMDD-HHMM.tar.gz` containing a `pg_dump` (custom format) and the
  attachments directory.
- Destination: local backup directory (default), which can be a mounted USB stick or
  network share. Retention: keep last 14 (setting).
- UI: list backups, "Back up now", download, restore (with confirmation; restore stops
  the app, restores DB and attachments, restarts).
- CLI: `pick2light backup` / `pick2light restore <file>`.
- Every `pick2light update` makes a backup first.

## 13. Deployment

### 13.1 Docker Compose

Services:
- `db`: `postgres:16` with a named volume.
- `server`: Pick2LIGHT image (multi-arch amd64/arm64) serving API, UI and controller WS.
  Uses `network_mode: host` so mDNS advertisement and discovery work on the LAN.
  Optional device mappings for the USB scanner (`/dev/input/...`) and Niimbot
  (`/dev/ttyACM*`, or the host Bluetooth/D-Bus socket).
- `backup`: same image running the scheduled backup job against `db`, writing to a bind
  mount.

Configuration in `.env`: database password, HTTP port (default 80), controller WS port
(same as HTTP by default), backup path, timezone.

### 13.2 Bare-metal installer (`deploy/install.sh`)

Targets Raspberry Pi OS (Bookworm, 64-bit), Debian 12 and Ubuntu 22.04+. Installs
PostgreSQL 16, Python 3.12 virtualenv, the server package and the prebuilt web UI, a
systemd service, a systemd timer for backups and the `pick2light` CLI. Re-running it
upgrades in place.

### 13.3 Proxmox LXC script (`deploy/proxmox/pick2light-lxc.sh`)

Runs on the Proxmox host. Prompts (with defaults) for CT ID, hostname, CPU, RAM
(default 1 GB), disk (default 8 GB), storage and bridge; creates an unprivileged
Debian 12 container; runs `install.sh` inside it. Optional USB device passthrough for
the scanner and Niimbot (device cgroup rules + bind mounts). Bluetooth inside LXC is not
supported by the script; the docs recommend USB for the Niimbot on Proxmox.

### 13.4 Updates

`pick2light update` (all install types): backup → pull/install new version → run
Alembic migrations → restart. Controller firmware binaries ship with each server release;
the UI shows controllers running older firmware and offers OTA.

### 13.5 Hardware guidance

Raspberry Pi 4/5 with ≥ 2 GB RAM, booting from SSD recommended (SD card supported), or
any 64-bit x86 thin client. Controllers: ESP32-S3 or ESP32-C3 USB-C dev boards
recommended; classic ESP32 supported.

## 14. Extensibility and versioning

- Database changes only through Alembic migrations; never manual DDL.
- REST API versioned under `/api/v1`; breaking changes go to `/api/v2`.
- Controller protocol carries `v`; the server supports the current and previous version
  so controllers can be updated after the server.
- Plugin points: importers and printer backends via Python entry points; category packs
  as JSON files that can be imported/exported and shared.

## 15. Testing

- **Server:** pytest against a real PostgreSQL 16 (Docker in CI). Unit tests for the
  units parser, SKU engine, field validation, scan classification and modes, stock
  operations and undo, light request resolution and grid wizard mapping, label template
  rendering, supplier code parsers (fixture codes from real Digi-Key/Mouser/LCSC bags),
  CSV import mapping. API tests for each router.
- **Controller protocol:** integration tests with the virtual controller over a real
  WebSocket (onboarding, config, light, reconnect replay, OTA message flow).
- **Web:** Vitest for components and stores; Playwright end-to-end tests for search →
  find → light (virtual controller), simulated scanner keystrokes in each mode,
  stocktake review/apply, CSV import.
- **Firmware:** PlatformIO native unit tests for message parsing, segment rendering,
  expiry and the power budget; a manual hardware test checklist in `docs/`.
- **Install:** CI job running `install.sh` in a Debian 12 container and smoke-testing
  `/api/v1/health`.
- **CI (GitHub Actions):** ruff + mypy, eslint + vue-tsc, all test suites, multi-arch
  image build, firmware builds for esp32/esp32s3/esp32c3.

## 16. Releases

Each release gets its own implementation plan.

| Release | Scope |
|---|---|
| **v0.1 — Database** | Server, PostgreSQL schema, core inventory (categories, fields, items, units, stock, locations, history log, movements, undo, trash, barcodes, attachments, purchase sources), units parser, SKU engine, search, web UI (all non-hardware screens), first-run wizard with starter packs, browser keyboard-wedge scanning with `find`/`check_in`/`check_out`/`consume` (mode
chosen with buttons in the UI; command barcodes arrive in v0.3), CSV import/export, PDF labels with default templates, auth, backups, Docker Compose install, health endpoint. |
| **v0.2 — Pick2LIGHT** | Light Manager, controller protocol, ESP32 firmware (onboarding, LEDs, power budget, OTA), controller UI, grid wizard, walk-through mapping, virtual controller, Find lights from UI and scans, `CMD:DONE`. |
| **v0.3 — Labels & scanning** | Label template editor, Niimbot B1 backend, CUPS backend, optional HTTPS + browser-direct Niimbot, all command barcodes + command sheet, `put_away` mode, stocktake/batch scans, server-side evdev scanner, bare-metal installer and Proxmox LXC script. |
| **v0.4 — Imports** | Importer plugin interface, import inbox, Digi-Key/Mouser/LCSC scan parsing and lookups, AliExpress userscript, generic link import, Reorder list, category keyword suggestions. |
