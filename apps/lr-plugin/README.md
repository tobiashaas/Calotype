# Lightroom Classic Plugin (Lua)

The Calotype interface in Lightroom. The plugin talks only to the local
[Bridge](../bridge/README.md); previews, uploads, retries and server communication
are handled by the Bridge ([ADR 004](../../docs/adr/004-bridge-localhost-architecture.md)).

## Install

1. Start the Bridge app once (creates `bridge.json` with port and token).
2. Lightroom Classic: **File → Plug-in Manager → Add** → choose the folder
   `apps/lr-plugin/Calotype.lrplugin`. Coming from LR-FrameFlow: remove the old plugin first
   (new folder and identifier, see [ADR 006](../../docs/adr/006-rename-to-calotype.md)).

## Menu items

**Library → Plug-in Extras** (and **File → Plug-in Extras**):

| Menu item | What happens |
|---|---|
| Train profile from selected photos... | Asks for name, genre, color/B&W. Hands the photos (path + current develop settings as the learning target) to the Bridge and waits for training. At least 3 photos, only RAW **or** only JPEG/TIFF. |
| Sort selected photos (culling)... | Sorts the selection into the collections *Calotype > Culling <date> > Keep / Check / Sort out*. Photos you already rated (stars) or flagged teach it your taste; without enough of them it uses starter rules. Stars, flags and edits are not changed. |
| Apply profile to selected photos... | Shows finished profiles, hands over the matching photos, waits and writes the predicted values with `photo:applyDevelopSettings` in **one** catalog step (Edit → Undo works). Option *Straighten photos with clear lines*: levels photos with walls, door frames or a horizon (Lightroom crop keys, largest crop); photos you cropped or straightened yourself keep their crop. Option *Retouch*: adds Lightroom's AI masks (subject, background, skin, eyes, teeth, sky) from the Calotype retouch presets, lets Lightroom compute them, removes masks that found nothing, keeps your own masks and saves a snapshot "Calotype: before". |
| Bridge status... | Is the Bridge running? Is the server reachable? How many profiles are ready? |

Cancel in the progress bar only stops the waiting — the Bridge keeps working.

## Files

| File | Purpose |
|---|---|
| `Info.lua` | Plugin manifest (`xyz.calotype.lightroom`), menu entries, starts with Lightroom (`LrForceInitPlugin`) |
| `BridgeClient.lua` | HTTP to the Bridge (`X-Calotype-Token`), reads `bridge.json` |
| `PhotoData.lua` | UUID, path, develop settings, EXIF per photo; RAW vs. JPEG/TIFF |
| `JobWait.lua` | Register photos, wait for a job with progress/cancel |
| `TrainProfile.lua`, `ApplyProfile.lua`, `CullPhotos.lua`, `BridgeStatus.lua` | Menu items and their dialogs |
| `Actions.lua` | Train / apply / cull flows without dialogs, shared by the menu items and the automation channel |
| `Retouch.lua` | AI-mask retouch: find our presets, snapshot, `applyDevelopPreset`, `updateAISettings`, remove empty masks |
| `Automation.lua`, `AutomationCommands.lua`, `AutomationState.lua` | Opt-in automation channel for the end-to-end tests (whitelisted commands only) |
| `TranslatedStrings_de.txt` | German UI strings (English is the default) |
| `Json.lua` | Small JSON encoder/decoder (Lightroom ships none) |
| `Log.lua` | Log file `Calotype.log` in `%LOCALAPPDATA%\Adobe\Lightroom\Logs\LrClassicLogs` (Windows) |

## Testing without Lightroom

The tests replace Lightroom's SDK modules with stubs (Lua 5.1 / LuaJIT, as in Lightroom):

```bash
luajit apps/lr-plugin/tests/run.lua
```

## Lightroom SDK pitfalls (found the hard way)

- A plain `pcall` cannot yield in Lightroom — catalog reads inside it fail silently. Use `LrTasks.pcall`.
- No catalog calls inside a `table.sort` comparator (yield error); read values first (`batchGetRawMetadata`).
- `applyDevelopSettings` with new masks never returns — masks only via `applyDevelopPreset` + `photo:updateAISettings()`; removing and adding masks need separate transactions.
- `WhiteBalance = "As Shot"` via the SDK keeps the old Temperature value.

## Lightroom test history

- ✅ Plugin loads, finds `bridge.json` (`%APPDATA%\Calotype`), Bridge status shows server and profiles.
- ✅ "Apply profile" on 45 Canon R6 photos: preview → Bridge → server → worker → `applyDevelopSettings`, look plausible.
- 🐞 Fixed: Lightroom's Lua sandbox has no `os.getenv` (the tests now replicate this).
- ✅ Automated end-to-end tests in Lightroom 15.6 (`tools/lr_e2e/`): apply + restore, white balance "Custom", training from Lightroom, straighten (angle and crop arrive, own crops stay), culling (collections, nothing else touched), retouch (masks computed, own masks kept, no duplicates).
- ⏳ Re-run after the rename to Calotype (plugin must be added once again).
- ⏳ Still to check: JPEG/TIFF (`IncrementalTemperature`), style profile with B&W.
