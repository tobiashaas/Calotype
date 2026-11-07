# Lightroom Classic Plugin (Lua)

The LR-FrameFlow interface in Lightroom. The plugin talks only to the local
[Bridge](../bridge/README.md); previews, uploads, retries and server communication
are handled by the Bridge ([ADR 004](../../docs/adr/004-bridge-localhost-architecture.md)).

## Install

1. Start the Bridge app once (creates `bridge.json` with port and token).
2. Lightroom Classic: **File → Plug-in Manager → Add** → choose the folder
   `apps/lr-plugin/LRFrameFlow.lrplugin`.

## Menu items

**Library → Plug-in Extras** (and **File → Plug-in Extras**):

| Menu item | What happens |
|---|---|
| Train profile from selected photos... | Asks for name, genre, color/B&W. Hands the photos (path + current develop settings as the learning target) to the Bridge and waits for training. At least 3 photos, only RAW **or** only JPEG/TIFF. |
| Apply profile to selected photos... | Shows finished profiles, hands over the matching photos, waits and writes the predicted values with `photo:applyDevelopSettings` in **one** catalog step (Edit → Undo works). |
| Bridge status... | Is the Bridge running? Is the server reachable? How many profiles are ready? |

Cancel in the progress bar only stops the waiting — the Bridge keeps working.

## Files

| File | Purpose |
|---|---|
| `Info.lua` | Plugin manifest, menu entries |
| `BridgeClient.lua` | HTTP to the Bridge (`X-LRFF-Token`), reads `bridge.json` |
| `PhotoData.lua` | UUID, path, develop settings, EXIF per photo; RAW vs. JPEG/TIFF |
| `JobWait.lua` | Register photos, wait for a job with progress/cancel |
| `TrainProfile.lua`, `ApplyProfile.lua`, `BridgeStatus.lua` | Menu actions |
| `Json.lua` | Small JSON encoder/decoder (Lightroom ships none) |
| `Log.lua` | Log file `LRFrameFlow.log` in `%LOCALAPPDATA%\Adobe\Lightroom\Logs\LrClassicLogs` (Windows) |

## Testing without Lightroom

The tests replace Lightroom's SDK modules with stubs (Lua 5.1 / LuaJIT, as in Lightroom):

```bash
luajit apps/lr-plugin/tests/run.lua
```

## First real Lightroom test (2026-11-07)

- ✅ Plugin loads, finds `bridge.json` (`%APPDATA%\LRFrameFlow`), Bridge status shows server and profiles.
- ✅ "Apply profile" on 45 Canon R6 photos: preview → Bridge → server → worker → `applyDevelopSettings`, look plausible.
- 🐞 Fixed: Lightroom's Lua sandbox has no `os.getenv` (the tests now replicate this).
- ⏳ Still to check: training from Lightroom, JPEG/TIFF (`IncrementalTemperature`), white balance "Custom" after applying, style profile with B&W.
