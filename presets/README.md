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

## Use

- **Lightroom Classic / Camera Raw:** Develop → Presets → `+` → *Import Presets…* and pick the
  `.xmp` files (or copy them to `%APPDATA%\Adobe\CameraRaw\Settings` on Windows,
  `~/Library/Application Support/Adobe/CameraRaw/Settings` on macOS, then restart Lightroom).
  They appear in the group *LR-FrameFlow*, with German names when Lightroom runs in German.
- **As a profile's style layer (folder mode):**
  `lrff-folder train <dir> --name "Weddings" --style presets/film-color.xmp`
- `looks.json` holds the same settings for programs and other converters.
