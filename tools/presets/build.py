"""Build the project's own looks as Lightroom Classic / Camera Raw presets.

    python tools/presets/build.py            # writes presets/*.xmp and presets/looks.json

Every look is designed here from scratch (no values from other products): a tone curve for
contrast and black level, HSL, color grading, texture/clarity, grain and vignette. Exposure,
white balance and the tone sliders are left out on purpose — those depend on the photo and come
from the trained profile (see libs/edit-serializer/style.py); as plain presets the looks then
work on any photo. Released under CC0 (see presets/README.md).
"""

from __future__ import annotations

import json
import uuid
from xml.sax.saxutils import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "presets"
GROUP = "Calotype"
NS = uuid.UUID("6f1c4b52-7a0e-4c55-9b7e-2f3a1d0c9e11")   # stable preset UUIDs per name

# Curve points (input, output), 0–255. A lifted first point = matte blacks; a lowered last
# point = softer highlights; points below/above the diagonal in the middle = contrast.
LOOKS: list[dict] = [
    {
        "name": "Warm & Soft",
        "name_de": "Warm & Weich",
        "about_de": "Sanfte, warme Hauttöne, leicht angehobene Schwarztöne, ruhiges Grün. Porträts, Familien.",
        "about": "Gentle, warm skin tones; slightly lifted blacks; quiet greens. Portraits, families.",
        "curve": [(0, 10), (64, 66), (128, 132), (192, 196), (255, 250)],
        "settings": {
            "Clarity2012": -5, "Texture": -6, "Vibrance": 8, "Saturation": -4,
            "HueAdjustmentGreen": 10, "SaturationAdjustmentGreen": -15, "LuminanceAdjustmentOrange": 5,
            "SaturationAdjustmentOrange": -3,
            "ColorGradeHighlightHue": 45, "ColorGradeHighlightSat": 12,
            "ColorGradeShadowHue": 30, "ColorGradeShadowSat": 6,
            "ColorGradeBlending": 60, "PostCropVignetteAmount": -8,
        },
    },
    {
        "name": "Bright & Airy",
        "name_de": "Hell & Luftig",
        "about_de": "Hell und offen: angehobene Schatten, wenig Kontrast, pastellige Grün- und Blautöne. Hochzeiten, Lifestyle.",
        "about": "Light and open: lifted shadows, low contrast, pastel greens and blues. Weddings, lifestyle.",
        "curve": [(0, 20), (60, 72), (128, 142), (200, 214), (255, 252)],
        "settings": {
            "Clarity2012": -8, "Dehaze": -3, "Vibrance": 5, "Saturation": -8,
            "SaturationAdjustmentGreen": -25, "LuminanceAdjustmentGreen": 10,
            "LuminanceAdjustmentBlue": 10, "SaturationAdjustmentBlue": -6,
            "LuminanceAdjustmentOrange": 8, "SaturationAdjustmentOrange": -5,
            "ColorGradeHighlightHue": 50, "ColorGradeHighlightSat": 6, "ColorGradeBlending": 70,
        },
    },
    {
        "name": "Clean & Natural",
        "name_de": "Klar & Natürlich",
        "about_de": "Naturgetreu mit etwas Knackigkeit. Business, Teamfotos, Produkte.",
        "about": "True-to-life with a bit of crispness. Business, team photos, products.",
        "curve": [(0, 0), (64, 58), (128, 128), (192, 198), (255, 255)],
        "settings": {
            "Clarity2012": 8, "Texture": 6, "Vibrance": 10,
            "SaturationAdjustmentOrange": -6, "SaturationAdjustmentBlue": 5,
        },
    },
    {
        "name": "Film Color",
        "name_de": "Film Farbe",
        "about_de": "Matte Schwarztöne, kühle Schatten, warme Lichter, gedämpftes Grün und feines Korn.",
        "about": "Matte blacks, cool shadows, warm highlights, muted greens and fine grain.",
        "curve": [(0, 24), (40, 44), (128, 130), (220, 224), (255, 246)],
        "settings": {
            "Saturation": -10, "Vibrance": 4, "Clarity2012": -3,
            "HueAdjustmentGreen": 18, "SaturationAdjustmentGreen": -20,
            "HueAdjustmentBlue": -8, "SaturationAdjustmentBlue": -10, "SaturationAdjustmentRed": -8,
            "ColorGradeShadowHue": 200, "ColorGradeShadowSat": 12,
            "ColorGradeHighlightHue": 40, "ColorGradeHighlightSat": 14, "ColorGradeBlending": 50,
            "GrainAmount": 18, "GrainSize": 25, "GrainFrequency": 50, "PostCropVignetteAmount": -10,
        },
    },
    {
        "name": "Golden Evening",
        "name_de": "Goldener Abend",
        "about_de": "Warme Mitteltöne und Lichter, ruhiger blauer Himmel. Porträts draußen, Events in der Dämmerung.",
        "about": "Warm midtones and highlights, calm blue sky. Outdoor portraits, events at dusk.",
        "curve": [(0, 6), (64, 60), (128, 130), (192, 200), (255, 252)],
        "settings": {
            "Vibrance": 6, "Clarity2012": 2,
            "HueAdjustmentYellow": -6, "SaturationAdjustmentYellow": 5, "SaturationAdjustmentOrange": 6,
            "SaturationAdjustmentBlue": -15, "LuminanceAdjustmentBlue": -5,
            "ColorGradeMidtoneHue": 38, "ColorGradeMidtoneSat": 10,
            "ColorGradeHighlightHue": 45, "ColorGradeHighlightSat": 18,
            "ColorGradeShadowHue": 220, "ColorGradeShadowSat": 8, "ColorGradeBlending": 55,
            "PostCropVignetteAmount": -6,
        },
    },
    {
        "name": "Cool & Modern",
        "name_de": "Kühl & Modern",
        "about_de": "Klar, leicht kühl, wenig Grün, knackige Details. Architektur, Corporate, Stadt.",
        "about": "Clean, slightly cool, reduced greens, crisp detail. Architecture, corporate, city.",
        "curve": [(0, 6), (70, 60), (128, 128), (190, 198), (255, 252)],
        "settings": {
            "Clarity2012": 10, "Texture": 8, "Saturation": -6,
            "SaturationAdjustmentOrange": -10, "SaturationAdjustmentGreen": -30,
            "SaturationAdjustmentBlue": -5,
            "ColorGradeShadowHue": 210, "ColorGradeShadowSat": 10,
            "ColorGradeHighlightHue": 190, "ColorGradeHighlightSat": 4, "ColorGradeBlending": 50,
        },
    },
    {
        "name": "Film B&W",
        "name_de": "Film S/W",
        "about_de": "Kräftiges Schwarz-Weiß mit tiefen Schwarztönen, leuchtender Haut und Korn.",
        "about": "Punchy black and white with deep blacks, glowing skin and grain.",
        "bw": True,
        "curve": [(0, 10), (50, 40), (128, 130), (200, 215), (255, 250)],
        "settings": {
            "Clarity2012": 12, "Texture": 4,
            "GrayMixerRed": 10, "GrayMixerOrange": 15, "GrayMixerYellow": 5, "GrayMixerGreen": -10,
            "GrayMixerAqua": -10, "GrayMixerBlue": -15, "GrayMixerPurple": 0, "GrayMixerMagenta": 5,
            "GrainAmount": 25, "GrainSize": 25, "GrainFrequency": 55, "PostCropVignetteAmount": -15,
        },
    },
    {
        "name": "Soft B&W",
        "name_de": "Weiches S/W",
        "about_de": "Sanftes Schwarz-Weiß mit wenig Kontrast und angehobenen Schwarztönen. Stille Momente, Neugeborene.",
        "about": "Gentle, low-contrast black and white with lifted blacks. Quiet moments, newborns.",
        "bw": True,
        "curve": [(0, 30), (64, 74), (128, 138), (192, 198), (255, 240)],
        "settings": {
            "Clarity2012": -6,
            "GrayMixerRed": 5, "GrayMixerOrange": 10, "GrayMixerYellow": 5, "GrayMixerGreen": 0,
            "GrayMixerAqua": 0, "GrayMixerBlue": -5, "GrayMixerPurple": 0, "GrayMixerMagenta": 0,
            "GrainAmount": 10, "GrainSize": 20, "GrainFrequency": 50,
        },
    },
]


# Retouch: Lightroom's own AI masks with gentle local adjustments. A preset only stores the mask
# *definition*; Lightroom finds subject / sky / skin … on each photo (photo:updateAISettings).
# Mask types (Lightroom's format): subtype 1 = subject, 2 = sky, 0 + category 22 = background,
# 3 + category = part of a person (2 face skin, 3 iris and pupil, 8 eye sclera, 12 teeth).
# Local values are stored as -1…1 (slider value / 100).
RETOUCH_GROUP = "Calotype Retouch"
RETOUCH: list[dict] = [
    {
        "id": "subject", "name": "Lift subject", "name_de": "Person hervorheben",
        "about": "Brightens the people a little and opens their shadows, so they stand out from the scene.",
        "about_de": "Hellt die Personen leicht auf und öffnet ihre Schatten, damit sie sich vom Umfeld abheben.",
        "masks": [(1, None, "Subject")],
        "local": {"LocalExposure2012": 0.06, "LocalShadows2012": 0.12, "LocalHighlights2012": -0.05,
                  "LocalClarity2012": 0.04},
    },
    {
        "id": "background", "name": "Calm background", "name_de": "Hintergrund beruhigen",
        "about": "Slightly darker, less saturated and softer background.",
        "about_de": "Hintergrund etwas dunkler, weniger gesättigt und weicher.",
        "masks": [(0, 22, "Background")],
        "local": {"LocalExposure2012": -0.08, "LocalSaturation": -0.08, "LocalClarity2012": -0.05},
    },
    {
        "id": "skin", "name": "Soften skin", "name_de": "Haut sanfter",
        "about": "Reduces fine skin texture without making faces look plastic.",
        "about_de": "Mildert feine Hautstruktur, ohne Gesichter künstlich wirken zu lassen.",
        "masks": [(3, 2, "Face Skin")],
        "local": {"LocalTexture": -0.15, "LocalClarity2012": -0.05},
    },
    {
        "id": "eyes", "name": "Clearer eyes", "name_de": "Augen klarer",
        "about": "A touch of brightness and clarity in the eyes.",
        "about_de": "Etwas mehr Helligkeit und Klarheit in den Augen.",
        "masks": [(3, 8, "Eye Sclera"), (3, 3, "Iris and Pupil")],
        "local": {"LocalExposure2012": 0.06, "LocalClarity2012": 0.08, "LocalSaturation": 0.03},
    },
    {
        "id": "teeth", "name": "Brighten teeth", "name_de": "Zähne aufhellen",
        "about": "Slightly brighter, less yellow teeth.",
        "about_de": "Zähne etwas heller und weniger gelb.",
        "masks": [(3, 12, "Teeth")],
        "local": {"LocalExposure2012": 0.06, "LocalSaturation": -0.25},
    },
    {
        "id": "sky", "name": "Deepen sky", "name_de": "Himmel vertiefen",
        "about": "Holds back bright skies and gives them a little more color.",
        "about_de": "Hält helle Himmel zurück und gibt ihnen etwas mehr Farbe.",
        "masks": [(2, None, "Sky")],
        "local": {"LocalExposure2012": -0.06, "LocalHighlights2012": -0.15, "LocalSaturation": 0.06,
                  "LocalDehaze": 0.05},
    },
]


def retouch_xmp(r: dict) -> str:
    """A preset that adds one AI-mask correction named "Calotype <id>"."""
    uid = lambda key: str(uuid.uuid5(NS, key)).replace("-", "").upper()  # noqa: E731
    head = {
        "PresetType": "Normal", "Cluster": "", "UUID": uid("retouch-" + r["id"]),
        "SupportsAmount": "False", "SupportsColor": "True", "SupportsMonochrome": "True",
        "SupportsHighDynamicRange": "True", "SupportsNormalDynamicRange": "True",
        "SupportsSceneReferred": "True", "SupportsOutputReferred": "True", "CameraModelRestriction": "",
        "Copyright": "CC0 — Calotype contributors", "ContactInfo": "",
        "Version": "15.4", "ProcessVersion": "15.4", "HasSettings": "True",
    }
    lines = [
        '<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>',
        '<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Calotype">',
        ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">',
        '  <rdf:Description rdf:about=""',
        '    xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"',
    ] + [f'    crs:{k}="{escape(v)}"' for k, v in head.items()]
    lines[-1] += ">"
    lines += _alt("Name", r["name"], r["name_de"]) + _alt("ShortName", "") + _alt("SortName", "")
    lines += _alt("Group", RETOUCH_GROUP) + _alt("Description", r["about"], r["about_de"])
    local = "".join(f'\n       crs:{k}="{v}"' for k, v in r["local"].items())
    lines += [
        "   <crs:MaskGroupBasedCorrections>", "    <rdf:Seq>", "     <rdf:li>", "      <rdf:Description",
        '       crs:What="Correction"', '       crs:CorrectionAmount="1"', '       crs:CorrectionActive="true"',
        f'       crs:CorrectionName="Calotype {r["id"]}"',
        f'       crs:CorrectionSyncID="{uid("group-" + r["id"])}"{local}>',
        "      <crs:CorrectionMasks>", "       <rdf:Seq>",
    ]
    for i, (sub, cat, name) in enumerate(r["masks"]):
        lines += [
            "        <rdf:li",
            '         crs:What="Mask/Image"', '         crs:MaskActive="true"', f'         crs:MaskName="{name}"',
            '         crs:MaskBlendMode="0"', '         crs:MaskInverted="false"',
            f'         crs:MaskSyncID="{uid(f"mask-{r["id"]}-{i}")}"', '         crs:MaskValue="1"',
            '         crs:MaskVersion="1"', f'         crs:MaskSubType="{sub}"',
            *([f'         crs:MaskSubCategoryID="{cat}"'] if cat is not None else []),
            '         crs:ReferencePoint="0.500000 0.500000"', '         crs:ErrorReason="0"/>',
        ]
    lines += ["       </rdf:Seq>", "      </crs:CorrectionMasks>", "      </rdf:Description>", "     </rdf:li>",
              "    </rdf:Seq>", "   </crs:MaskGroupBasedCorrections>",
              "  </rdf:Description>", " </rdf:RDF>", "</x:xmpmeta>", '<?xpacket end="w"?>', ""]
    return "\n".join(lines)


def _alt(tag: str, text: str, de: str | None = None) -> list[str]:
    items = [f'     <rdf:li xml:lang="x-default">{escape(text)}</rdf:li>']
    if de:   # Lightroom shows the German name when it runs in German
        items.append(f'     <rdf:li xml:lang="de-DE">{escape(de)}</rdf:li>')
    return [f"   <crs:{tag}>", "    <rdf:Alt>", *items, "    </rdf:Alt>", f"   </crs:{tag}>"]


def slug(name: str) -> str:
    """"Warm & Soft" → "warm-soft", "Film B&W" → "film-bw"."""
    words = "".join(c for c in name.lower().replace("&", "") if c.isalnum() or c == " ").split()
    return "-".join(words)


def preset_xmp(look: dict) -> str:
    settings = dict(look["settings"])
    settings["ConvertToGrayscale"] = "True" if look.get("bw") else "False"
    attrs = {
        "PresetType": "Normal", "Cluster": "", "UUID": str(uuid.uuid5(NS, look["name"])).replace("-", "").upper(),
        "SupportsAmount": "False", "SupportsColor": "False" if look.get("bw") else "True",
        "SupportsMonochrome": "True", "SupportsHighDynamicRange": "True",
        "SupportsNormalDynamicRange": "True", "SupportsSceneReferred": "True",
        "SupportsOutputReferred": "True", "CameraModelRestriction": "",
        "Copyright": "CC0 — Calotype contributors", "ContactInfo": "",
        "Version": "15.4", "ProcessVersion": "15.4", "HasSettings": "True",
        "ToneCurveName2012": "Custom",
        **{k: str(v) for k, v in settings.items()},
    }
    lines = [
        '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>',
        '<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Calotype">',
        ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">',
        '  <rdf:Description rdf:about=""',
        '    xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"',
    ]
    lines += [f'    crs:{k}="{escape(v, {chr(34): "&quot;"})}"' for k, v in attrs.items()]
    lines[-1] += ">"

    def seq(tag: str, points: list[tuple[int, int]]) -> list[str]:
        return ([f"   <crs:{tag}>", "    <rdf:Seq>"] + [f"     <rdf:li>{x}, {y}</rdf:li>" for x, y in points]
                + ["    </rdf:Seq>", f"   </crs:{tag}>"])

    lines += _alt("Name", look["name"], look.get("name_de")) + _alt("ShortName", "") + _alt("SortName", "")
    lines += _alt("Group", GROUP) + _alt("Description", look["about"], look.get("about_de"))
    lines += seq("ToneCurvePV2012", look["curve"])
    for channel in ("Red", "Green", "Blue"):
        lines += seq(f"ToneCurvePV2012{channel}", [(0, 0), (255, 255)])
    lines += ["  </rdf:Description>", " </rdf:RDF>", "</x:xmpmeta>", '<?xpacket end="w"?>', ""]
    return "\n".join(lines)


def main() -> int:
    OUT.mkdir(exist_ok=True)
    index = []
    for look in LOOKS:
        path = OUT / f"{slug(look['name'])}.xmp"
        path.write_text(preset_xmp(look), encoding="utf-8")
        flat = [float(v) for p in look["curve"] for v in p]
        index.append({"name": look["name"], "name_de": look.get("name_de"), "file": path.name,
                      "about": look["about"], "about_de": look.get("about_de"), "bw": bool(look.get("bw")),
                      "settings": {**look["settings"], "ToneCurvePV2012": flat,
                                   "ConvertToGrayscale": bool(look.get("bw"))}})
        print(f"wrote {path.relative_to(ROOT)}")
    (OUT / "looks.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    retouch_dir = OUT / "retouch"
    retouch_dir.mkdir(exist_ok=True)
    for r in RETOUCH:
        path = retouch_dir / f"{r['id']}.xmp"
        path.write_text(retouch_xmp(r), encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)}")
    (retouch_dir / "retouch.json").write_text(json.dumps(
        [{k: r[k] for k in ("id", "name", "name_de", "about", "about_de", "local")} | {"group": RETOUCH_GROUP}
         for r in RETOUCH], indent=1, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
