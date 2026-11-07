# Bridge (Tauri + Rust)

Local service between the Lightroom plugin and the server API (see
[ADR 004](../../docs/adr/004-bridge-localhost-architecture.md)).

```
Plugin ──HTTP 127.0.0.1:47600──▶ Bridge ──SQLite outbox──▶ Server API
       ◀── status + lr_settings ──        ◀── polling ───
```

| Folder | Contents |
|---|---|
| `core/` | `lrff-bridge-core`: local API (axum), outbox (SQLite), preview from the original file, API client. Testable without Tauri, also runs headless. |
| `src-tauri/` | Desktop app: starts the core, status window, commands `bridge_status` / `set_api_base_url` / `retry_now`. |
| `ui/` | Status window (static HTML/JS, no bundler). |

Contract of the local API: [`packages/contracts/openapi/plugin-bridge-api.yaml`](../../packages/contracts/openapi/plugin-bridge-api.yaml).

## What the Bridge does

- **Local API** on `127.0.0.1` only. On first start, `bridge.json` (port,
  random token, server address) is created in the data folder: `%APPDATA%\LRFrameFlow` or
  `~/Library/Application Support/LRFrameFlow` (override with `LRFF_BRIDGE_DATA_DIR`).
  Every `/v1` call needs the `X-LRFF-Token` header.
- **Outbox:** photos and jobs land in `bridge.sqlite3` first. A background loop
  builds previews, uploads, creates jobs (fixed `Idempotency-Key`) and polls the status.
  Network errors, 5xx/429 and unreachable files (unplugged drive) → retry with
  backoff (2 s … 5 min). Rejected requests (4xx) and broken files → `failed` with a reason.
- **Preview = unedited image:** for RAW, the smallest embedded camera JPEG that
  covers 1200 px (otherwise the largest); for JPEG/TIFF/PNG, the file itself. Longest side
  ≤ 1200 px, orientation from the RAW container or EXIF applied. If a RAW contains only a
  full-size JPEG (e.g. Canon CR2), it is decoded directly at reduced size (DCT scaling).
  Measured: Canon CR3 ~200 ms, Canon CR2 ~300 ms per photo (local SSD).

## Folder mode (without Lightroom)

`lrff-folder` works with RAW + XMP sidecars and talks to the running Bridge:

```bash
lrff-folder train  <folder> --name "Business Warm" --genre business   # edited RAWs (RAW + XMP)
lrff-folder apply  <folder> --profile "Business Warm"                  # writes IMG_0001.xmp next to each RAW
lrff-folder profiles

# Style layer: the model sets exposure/WB/tone per photo, the preset sets the look
lrff-folder train  <folder> --name "Business + Look" --style my-preset.xmp

# Train/test split and output to another folder (source stays untouched)
lrff-folder train  <folder> --name X --files-from train.txt
lrff-folder apply  <folder> --profile X --files-from test.txt --out <output>
```

- Training uses only RAWs whose XMP contains develop settings (`crs:Exposure2012` …).
- `apply` skips photos that are already edited (your XMPs); `--force` updates only the
  `crs:` values in them and leaves stars, keywords etc. in place. New XMPs carry
  `crs:ProcessVersion="15.4"` and `lrff:Profile="…"`.
- Then import the folder into Lightroom — the photos are edited right away. For photos that
  are already in the catalog, the plugin is the right way.
- Photo IDs outside a catalog: `file-` + SHA-256 over size, first and last MiB
  (stable when moving/renaming).

## Development

```bash
# Core: tests + lint (fast, without Tauri)
cargo test -p lrff-bridge-core
cargo clippy -p lrff-bridge-core --all-targets -- -D warnings

# Check preview extraction on real RAWs (time, size, orientation)
cargo run --release -p lrff-bridge-core --example preview -- <out-dir> <raw-files>

# Run without a window
cargo run -p lrff-bridge-core --bin lrff-bridge-headless

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
- Previews are built one after another (4 per pass) — parallelize for large shoots.
- Folder mode writes RAW sidecars only; JPEG/TIFF carry XMP inside the file itself.
