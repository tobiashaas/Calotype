# Looks

Eight looks made for this project, free to use for anything (**CC0 1.0** — public domain
dedication). Every value is set by hand in [`tools/presets/build.py`](../tools/presets/build.py);
no values come from other products. Run the script after changing a look.

| Look (English / Deutsch) | Character |
|---|---|
| Warm & Soft / Warm & Weich | Gentle, warm skin tones, slightly lifted blacks, quiet greens |
| Bright & Airy / Hell & Luftig | Lifted shadows, low contrast, pastel greens and blues |
| Clean & Natural / Klar & Natürlich | True to life with a bit of crispness |
| Film Color / Film Farbe | Matte blacks, cool shadows, warm highlights, fine grain |
| Golden Evening / Goldener Abend | Warm midtones and highlights, calm blue sky |
| Cool & Modern / Kühl & Modern | Slightly cool, reduced greens, crisp detail |
| Film B&W / Film S/W | Punchy black and white with grain |
| Soft B&W / Weiches S/W | Gentle, low-contrast black and white |

The looks only carry what makes a *style*: tone curve, HSL, color grading, texture/clarity,
grain, vignette. Exposure, white balance and the tone sliders are left out — they depend on the
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
