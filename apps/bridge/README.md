# Bridge (Tauri + Rust)

Lokaler Dienst zwischen Lightroom-Plugin und Server-API (siehe
[ADR 004](../../docs/adr/004-bridge-localhost-architecture.md)).

```
Plugin ──HTTP 127.0.0.1:47600──▶ Bridge ──SQLite-Outbox──▶ Server-API
       ◀── Status + lr_settings ──        ◀── Polling ───
```

| Ordner | Inhalt |
|---|---|
| `core/` | `lrff-bridge-core`: lokale API (axum), Outbox (SQLite), Vorschau aus der Originaldatei, API-Client. Ohne Tauri testbar, läuft auch headless. |
| `src-tauri/` | Desktop-App: startet den Kern, Statusfenster, Befehle `bridge_status` / `set_api_base_url` / `retry_now`. |
| `ui/` | Statusfenster (statisches HTML/JS, kein Bundler). |

Vertrag der lokalen API: [`packages/contracts/openapi/plugin-bridge-api.yaml`](../../packages/contracts/openapi/plugin-bridge-api.yaml).

## Was die Bridge tut

- **Lokale API** nur auf `127.0.0.1`. Beim ersten Start entsteht `bridge.json` (Port,
  Zufalls-Token, Server-Adresse) im Datenordner: `%APPDATA%\LRFrameFlow` bzw.
  `~/Library/Application Support/LRFrameFlow` (überschreibbar mit `LRFF_BRIDGE_DATA_DIR`).
  Jeder `/v1`-Aufruf braucht den Header `X-LRFF-Token`.
- **Outbox:** Fotos und Jobs landen zuerst in `bridge.sqlite3`. Eine Hintergrundschleife
  baut Vorschauen, lädt hoch, legt Jobs an (fester `Idempotency-Key`) und pollt den Status.
  Netzfehler, 5xx/429 und nicht erreichbare Dateien (abgesteckte Platte) → neuer Versuch mit
  Backoff (2 s … 5 min). Abgelehnte Anfragen (4xx) und kaputte Dateien → `failed` mit Grund.
- **Vorschau = unbearbeitetes Bild:** bei RAW das größte eingebettete Kamera-JPEG, bei
  JPEG/TIFF/PNG die Datei selbst; längste Seite ≤ 1200 px.

## Entwickeln

```bash
# Kern: Tests + Lint (schnell, ohne Tauri)
cargo test -p lrff-bridge-core
cargo clippy -p lrff-bridge-core --all-targets -- -D warnings

# Ohne Fenster laufen lassen
cargo run -p lrff-bridge-core --bin lrff-bridge-headless

# Desktop-App
npm install
npm run dev        # Debug-Fenster
npm run build      # Installer (MSI/NSIS bzw. .dmg)
```

Windows braucht die MSVC Build Tools und WebView2 (bei Windows 11 vorinstalliert).

## Bekannte Grenzen

- Schließen des Fensters beendet die Bridge (Tray-Modus folgt).
- Fotos, die schon hochgeladen sind, werden bei erneuter Registrierung nicht aktualisiert —
  die Server-API ist pro `lr_catalog_uuid` idempotent und übernimmt neue Develop-Settings nicht.
- Ein Train-Job liefert noch keine `profile_id` zurück; das Plugin findet das Profil über
  `GET /v1/profiles` und den Namen.
