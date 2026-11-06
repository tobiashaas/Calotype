# ADR 004 — Bridge als lokaler Dienst, Plugin als Oberfläche

- **Status:** Akzeptiert
- **Datum:** 2026-11-06
- **Entscheider:** Maintainer
- **Ergänzt:** [ADR 002](002-bridge-tauri.md) (Tauri bleibt gesetzt)

## Kontext

ADR 002 legt Tauri fest, aber nicht, wie Plugin, Bridge und API zusammenspielen. Zwei
etablierte Muster am Markt (nur Architektur betrachtet, keine fremden Modelle oder Code):

- Lokaler **Rust-HTTP-Dienst auf `127.0.0.1`** mit SQLite für Job-/Album-Zustand, eine
  schlanke Oberfläche davor.
- **Lightroom-Plugin als Oberfläche**, das einen lokalen Prozess anstößt und die Ergebnisse
  als Develop-Settings in den Katalog schreibt.

Für uns zählen: Lightroom friert nie ein, nichts geht bei Netzabbrüchen verloren, und das
Modell lernt aus dem **unbearbeiteten** Bild, nicht aus dem fertigen Look.

## Entscheidung

1. **Plugin (Lua) = Oberfläche für den Fotografen.** Profil wählen, Training/Edit starten,
   Ergebnisse per `photo:applyDevelopSettings()` übernehmen (rückgängig machbar über
   Lightrooms Verlauf). Das Plugin spricht **nur mit der Bridge**, nie direkt mit der API.
2. **Bridge (Tauri, Rust-Kern) = lokaler Dienst.**
   - axum-HTTP-Server auf `127.0.0.1` (Standard-Port `47600`, konfigurierbar).
   - Lokaler Zugriffsschutz: Zufalls-Token beim ersten Start; Port und Token liegen in
     `bridge.json` im App-Datenverzeichnis, das Plugin liest sie von dort und sendet den
     Token als Header.
   - **SQLite-Outbox:** Uploads und Job-Anfragen werden zuerst lokal gespeichert, dann mit
     Wiederholung und Backoff an die API geschickt (gleicher `Idempotency-Key` je Versuch).
     Job-Status wird gepollt und lokal gecacht, das Plugin fragt nur die Bridge.
   - Tauri-Fenster nur für Status, Login/API-Adresse und Einstellungen.
3. **Modell-Input = unbearbeitetes Bild.** Die Bridge erzeugt die Vorschau selbst aus der
   Originaldatei (Pfad vom Plugin): bei RAW das eingebettete Kamera-JPEG, bei JPEG/TIFF die
   Datei selbst, jeweils verkleinert (längste Seite ≤ 1200 px). Die aktuellen
   Develop-Settings (`photo:getDevelopSettings()`) gehen als Trainingsziel mit. So passen
   Input (vorher) und Ziel (Entscheidung des Fotografen) zusammen.
4. **ML bleibt in Python** (Worker). Lokale Inferenz in der Bridge (ONNX) ist eine spätere
   Option, die Verträge bleiben dafür unverändert.

## Folgen / Trade-offs

- **Positiv:** Lightroom blockiert nicht (Plugin wartet nur auf localhost). Offline-fähig
  durch die Outbox. Kein Lightroom-Render für die Vorschau nötig, dadurch schnell und
  unabhängig vom aktuellen Look.
- **Negativ / Risiken:** Das eingebettete JPEG folgt dem Kamera-Bildstil, nicht Adobes
  Standardprofil — für das Training ist das konsistent, muss aber für jede Kamera vorhanden
  sein (Fallback: Lightroom-Export mit zurückgesetzten Einstellungen, offen). Zwei Prozesse
  statt einem: Die Bridge muss laufen, das Plugin zeigt sonst einen klaren Hinweis.
- **Offen:** Ob `getDevelopSettings()` für JPEG/TIFF wirklich
  `IncrementalTemperature`/`IncrementalTint` liefert, wird im ersten Plugin-Smoke-Test
  geprüft (Mapping in `libs/edit-serializer`).
