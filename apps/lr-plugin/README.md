# Lightroom Classic Plugin (Lua)

Die Oberfläche von LR-FrameFlow in Lightroom. Das Plugin spricht nur mit der lokalen
[Bridge](../bridge/README.md); Vorschau, Upload, Wiederholungen und Server-Kommunikation
erledigt die Bridge ([ADR 004](../../docs/adr/004-bridge-localhost-architecture.md)).

## Installieren

1. Bridge-App einmal starten (legt `bridge.json` mit Port und Token an).
2. Lightroom Classic: **Datei → Zusatzmodul-Manager → Hinzufügen** → Ordner
   `apps/lr-plugin/LRFrameFlow.lrplugin` wählen.

## Menüpunkte

**Bibliothek → Zusatzmoduloptionen** (und **Datei → Zusatzmoduloptionen**):

| Menüpunkt | Was passiert |
|---|---|
| Train profile from selected photos... | Fragt Name, Genre, Farbe/SW ab. Übergibt die Fotos (Pfad + aktuelle Develop-Settings als Lernziel) an die Bridge und wartet auf das Training. Mindestens 3 Fotos, nur RAW **oder** nur JPEG/TIFF. |
| Apply profile to selected photos... | Zeigt fertige Profile, übergibt die passenden Fotos, wartet und schreibt die vorhergesagten Werte mit `photo:applyDevelopSettings` in **einem** Katalog-Schritt (Bearbeiten → Rückgängig wirkt). |
| Bridge status... | Läuft die Bridge? Server erreichbar? Wie viele Profile sind fertig? |

Abbrechen im Fortschrittsbalken beendet nur das Warten — die Bridge arbeitet weiter.

## Dateien

| Datei | Zweck |
|---|---|
| `Info.lua` | Plugin-Manifest, Menüeinträge |
| `BridgeClient.lua` | HTTP zur Bridge (`X-LRFF-Token`), liest `bridge.json` |
| `PhotoData.lua` | UUID, Pfad, Develop-Settings, EXIF pro Foto; RAW vs. JPEG/TIFF |
| `JobWait.lua` | Fotos registrieren, Job mit Fortschritt/Abbrechen abwarten |
| `TrainProfile.lua`, `ApplyProfile.lua`, `BridgeStatus.lua` | Menüaktionen |
| `Json.lua` | Kleiner JSON-Encoder/-Decoder (Lightroom bringt keinen mit) |
| `Log.lua` | Log-Datei `LRFrameFlow.log` in `Dokumente/LrClassicLogs` |

## Testen ohne Lightroom

Die Tests ersetzen Lightrooms SDK-Module durch Attrappen (Lua 5.1 / LuaJIT wie in Lightroom):

```bash
luajit apps/lr-plugin/tests/run.lua
```

## Erster echter Lightroom-Test (07.11.2026)

- ✅ Plugin lädt, findet `bridge.json` (`%APPDATA%\LRFrameFlow`), Bridge-Status zeigt Server und Profile.
- ✅ „Apply profile" auf 45 Canon-R6-Fotos: Vorschau → Bridge → Server → Worker → `applyDevelopSettings`, Look plausibel.
- 🐞 Behoben: Lightrooms Lua-Sandbox hat kein `os.getenv` (Tests bilden das jetzt nach).
- ⏳ Noch prüfen: Training aus Lightroom, JPEG/TIFF (`IncrementalTemperature`), Weißabgleich „Benutzerdefiniert" nach dem Anwenden, Stil-Profil mit S/W.
