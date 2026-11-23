# Looks

Eighteen looks made for this project, free to use for anything (**CC0 1.0** — public domain
dedication). Every value is set by hand in [`tools/presets/build.py`](../tools/presets/build.py);
no values come from other products. Run the script after changing a look.

| Look | Character |
|---|---|
| Warm & Soft | Gentle, warm skin tones, slightly lifted blacks, quiet greens |
| Bright & Airy | Lifted shadows, low contrast, pastel greens and blues |
| Clean & Natural | True to life with a bit of crispness |
| Film Color | Matte blacks, cool shadows, warm highlights, fine grain |
| Golden Evening | Warm midtones and highlights, calm blue sky |
| Cool & Modern | Slightly cool, reduced greens, crisp detail |
| Soft Glow | Warm, soft glow in the highlights (Lightroom 16 glow; older versions ignore it) |
| Film B&W | Punchy black and white with grain |
| Soft B&W | Gentle, low-contrast black and white |
| Pastel Morning | Dreamy and bright, soft highlights, a hint of peach and lilac |
| Quiet Portrait | Soft skin, gentle contrast, muted colors, light vignette |
| Old Postcard | Faded blacks, amber highlights, teal shadows, grain |
| Charcoal | Deep, dense black and white with dark skies |
| Silver Haze | Bright, airy black and white with glowing skin |
| Wedding Emotional | The maintainer's own wedding look (26 weddings 2020–2023): matte shadows through the channel curves, restrained reds and yellows, fine grain, a light vignette |
| Wedding Golden Light | Golden hour wedding mood: rich warm autumn tones, lifted shadow curve |
| Lively Moments | Crisp, lively look for family and child portraits |
| Cinematic Drama | Moody, cinematic contrast look with deep shadows and muted vibrance |

The looks only carry what makes a *style*: tone curve, HSL, color grading, texture/clarity,
grain, vignette, glow. Exposure, white balance and the tone sliders are left out — they depend on the
photo. So the looks work on any photo, and as the style layer of a trained profile the profile
sets exposure and white balance per photo while the look adds the style.

## Retouch (Lightroom AI masks)

`retouch/` holds six presets that each add one of Lightroom's own AI masks with gentle local
adjustments: *Lift subject, Calm background, Soften skin, Clearer eyes, Brighten teeth, Deepen
sky* (German: *Person hervorheben, Hintergrund beruhigen, Haut sanfter, Augen klarer, Zähne
aufhellen, Himmel vertiefen*). They store only the mask *definition*; Lightroom finds the subject,
sky … on each photo. The plugin applies them together with a profile (apply dialog), lets
Lightroom detect the masks (`photo:updateAISettings`, Lightroom 13.3+), removes masks that found
nothing, keeps the photographer's own masks and saves the original as the snapshot
*Calotype: before*. The approach (mask presets + `updateAISettings`) follows
[Retoucan](https://github.com/joemalott/retoucan) (MIT) — thanks!

`retouch/retouch.json` is the manifest of the retouch kinds: id, preset file, correction name
(`Calotype <id>`), Lightroom mask types (`MaskSubType` / `MaskSubCategoryID`), English and German
titles and the local values.

### Adding a retouch kind

The kinds are defined in **one place**: the `RETOUCH` list in
[`tools/presets/build.py`](../tools/presets/build.py). To add one:

1. Add an entry there (id, preset names, German plugin title `title_de`, descriptions, the AI
   masks as `(MaskSubType, MaskSubCategoryID or None, name)`, local values).
2. Run `python tools/presets/build.py`. It writes the preset, the manifest, the mask kinds
   edit-serializer learns (`libs/edit-serializer/src/calotype_edit_serializer/retouch_kinds.py`),
   the plugin's list (`apps/lr-plugin/Calotype.lrplugin/RetouchKinds.lua`) and the German title
   (`TranslatedStrings_de.txt`).
3. Add the new `.xmp` to the Bridge's embed list (`apps/bridge/core/src/presets.rs`; its test
   `presets_on_disk_are_all_embedded` fails until you do).
4. Commit everything. `libs/edit-serializer/tests/test_presets.py` fails while a generated file
   is out of sync.

## Use

- **Automatic:** the Bridge installs all presets on start (`install_presets` in `bridge.json`,
  on by default); restart Lightroom once afterwards.
- **Lightroom Classic / Camera Raw by hand:** Develop → Presets → `+` → *Import Presets…* and pick the
  `.xmp` files (or copy them to `%APPDATA%\Adobe\CameraRaw\Settings` on Windows,
  `~/Library/Application Support/Adobe/CameraRaw/Settings` on macOS, then restart Lightroom).
  They appear in the group *Calotype*, with German names when Lightroom runs in German.
- **As a profile's style layer (folder mode):**
  `calotype-folder train <dir> --name "Weddings" --style presets/film-color.xmp`
- `looks.json` holds the same settings for programs and other converters.
