# Bridge (Tauri + Rust)

Local service between the Lightroom plugin and the server API (see
[ADR 004](../../docs/adr/004-bridge-localhost-architecture.md)).

```
Plugin ──HTTP 127.0.0.1:47600──▶ Bridge ──SQLite outbox──▶ Server API
       ◀── status + lr_settings ──        ◀── polling ───
```

| Folder | Contents |
|---|---|
| `core/` | `calotype-bridge-core`: local API (axum), outbox (SQLite), preview from the original file, API client, XMP sidecars, preset installer, `calotype-folder`, automation channel. Testable without Tauri, also runs headless. |
| `src-tauri/` | Desktop app: starts the core, status window, commands `bridge_status` / `set_api_base_url` / `retry_now`. |
| `ui/` | Status window (static HTML/JS, no bundler). |

Contract of the local API: [`packages/contracts/openapi/plugin-bridge-api.yaml`](../../packages/contracts/openapi/plugin-bridge-api.yaml).

## What the Bridge does

- **Local API** on `127.0.0.1` only. On first start, `bridge.json` (port,
  random token, server address) is created in the data folder: `%APPDATA%\Calotype` or
  `~/Library/Application Support/Calotype` (override with `CALOTYPE_BRIDGE_DATA_DIR`).
  Every `/v1` call needs the `X-Calotype-Token` header.
- **Outbox:** photos and jobs land in `bridge.sqlite3` first. A background loop
  builds previews, uploads, creates jobs (fixed `Idempotency-Key`) and polls the status.
  Network errors, 5xx/429 and unreachable files (unplugged drive) → retry with
  backoff (2 s … 5 min). Rejected requests (4xx) and broken files → `failed` with a reason.
- **Preview = unedited image:** for RAW, the smallest embedded camera JPEG that
  covers 1200 px (otherwise the largest); for JPEG/TIFF/PNG, the file itself. Longest side
  ≤ 1200 px, orientation from the RAW container or EXIF applied. If a RAW contains only a
  full-size JPEG (e.g. Canon CR2), it is decoded directly at reduced size (DCT scaling).
  When the RAW holds a mid-size preview, only its first 4 MB are read (CR3 from USB 650 → 237 ms
  per photo, ~85 % less data over a NAS). Measured: Canon CR3 ~200 ms, Canon CR2 ~300 ms per photo
  (local SSD); 8 photos are prepared in parallel.
- **Jobs:** train, edit (optionally with straighten) and cull jobs go to the server; results are
  mapped back to catalog UUIDs. A file that stays unreachable after 5 attempts is skipped instead
  of blocking the job.
- **Presets:** on start the Bridge installs the project's looks and retouch presets into Camera
  Raw's settings folder (`…\Adobe\CameraRaw\Settings\Calotype`); `"install_presets": false` in
  `bridge.json` turns this off. Files it once installed under the old names are removed.
- **Automation channel** (`"automation": true` in `bridge.json`, off by default): lets
  `tools/lr_e2e/` run whitelisted plugin commands in a running Lightroom.

## Folder mode (without Lightroom)

`calotype-folder` works with RAW + XMP sidecars and talks to the running Bridge:

```bash
calotype-folder train  <folder> --name "Business Warm" --genre business   # edited RAWs (RAW + XMP)
calotype-folder apply  <folder> --profile "Business Warm"                  # writes IMG_0001.xmp next to each RAW
calotype-folder profiles

# Style layer: the model sets exposure/WB/tone per photo, the preset sets the look
calotype-folder train  <folder> --name "Business + Look" --style my-preset.xmp

# Train/test split and output to another folder (source stays untouched)
calotype-folder train  <folder> --name X --files-from train.txt
calotype-folder apply  <folder> --profile X --files-from test.txt --out <output>

# A whole archive (one folder per shoot); edits from the Lightroom catalogs next to the photos
calotype-folder train  E:/2018 E:/2019 --recursive --catalogs --name "Weddings" --dry-run   # count first
calotype-folder train  E:/2018 E:/2019 --recursive --catalogs --name "Weddings"

# Edits exported from a catalog into another folder; straighten while applying
calotype-folder train  <folder> --name X --sidecars <xmp-folder>
calotype-folder apply  <folder> --profile X --straighten

# Culling: color label green / yellow / red + calotype:Cull / calotype:CullReason in the sidecar
calotype-folder cull   <folder> [--out <output>]
```

- Training uses only RAWs whose XMP contains develop settings (`crs:Exposure2012` …).
- `--recursive` reads every folder below the given ones and skips Lightroom's preview folders
  (`*.lrdata` — smart previews are DNGs), hidden folders and NAS metadata (`@eaDir`, `._*`).
- `--catalogs` reads Lightroom catalogs (`.lrcat`) next to or above the photos, read-only
  (SQLite `immutable`: no lock, no journal). The nearest catalog that knows a file wins over its
  sidecar; photos it lists as only imported (also with an import preset) or reset are left out.
  Matched by file name below the catalog's folder — catalogs store paths of another computer.
- `apply` skips photos that are already edited (your XMPs); `--force` updates only the
  `crs:` values in them and leaves stars, keywords etc. in place. New XMPs carry
  `crs:ProcessVersion="15.4"` and `calotype:Profile="…"`; `lrff:` / `tarsier:` attributes from
  before the rename are upgraded.
- `cull` leaves stars and edits alone; sidecars that already carry stars or labels teach the scorer.
- Then import the folder into Lightroom — the photos are edited right away. For photos that
  are already in the catalog, the plugin is the right way.
- Photo IDs outside a catalog: `file-` + SHA-256 over size, first and last MiB
  (stable when moving/renaming).

## Development

```bash
# Core: tests + lint (fast, without Tauri)
cargo test -p calotype-bridge-core
cargo clippy -p calotype-bridge-core --all-targets -- -D warnings

# Check preview extraction on real RAWs (time, size, orientation)
cargo run --release -p calotype-bridge-core --example preview -- <out-dir> <raw-files>

# Run without a window
cargo run -p calotype-bridge-core --bin calotype-bridge-headless

# Desktop app
npm install
npm run dev        # debug window
npm run build      # installer (MSI/NSIS or .dmg)
```

Windows needs the MSVC Build Tools and WebView2 (preinstalled on Windows 11).

## Known limits

- Closing the window quits the Bridge (tray mode will follow).
- Photos that are already uploaded are not updated when registered again —
  the server API is idempotent per `lr_catalog_uuid` and does not take over new develop settings.
- Folder mode writes RAW sidecars only; JPEG/TIFF carry XMP inside the file itself.
