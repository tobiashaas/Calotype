"""The project's own looks (presets/): valid presets, look settings only, in sync with the build."""

from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from lr_edit_serializer.style import PHOTO_DEPENDENT, is_style_key

ROOT = Path(__file__).resolve().parents[3]
PRESETS = ROOT / "presets"
CRS = "{http://ns.adobe.com/camera-raw-settings/1.0/}"
RDF = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"
META = {"PresetType", "Cluster", "UUID", "SupportsAmount", "SupportsColor", "SupportsMonochrome",
        "SupportsHighDynamicRange", "SupportsNormalDynamicRange", "SupportsSceneReferred",
        "SupportsOutputReferred", "CameraModelRestriction", "Copyright", "ContactInfo", "Version",
        "ProcessVersion", "HasSettings", "ToneCurveName2012"}


def _presets():
    return sorted(PRESETS.glob("*.xmp"))


def test_every_preset_is_a_valid_look_without_photo_dependent_values():
    names = set()
    assert len(_presets()) >= 8
    for path in _presets():
        desc = ET.parse(path).getroot().find(f"{RDF}RDF/{RDF}Description")
        keys = {k[len(CRS):] for k in desc.attrib if k.startswith(CRS)}
        assert not keys & PHOTO_DEPENDENT, path.name
        assert all(k in META or is_style_key(k) for k in keys), (path.name, keys - META)
        labels = {li.get("{http://www.w3.org/XML/1998/namespace}lang"): li.text
                  for li in desc.find(f"{CRS}Name").iter(f"{RDF}li")}
        assert labels.get("x-default") and labels.get("de-DE"), path.name
        assert labels["x-default"] not in names
        names.add(labels["x-default"])
        curve = [li.text for li in desc.find(f"{CRS}ToneCurvePV2012").iter(f"{RDF}li")]
        xs = [int(p.split(",")[0]) for p in curve]
        assert xs == sorted(xs) and xs[0] == 0 and xs[-1] == 255, path.name


def test_presets_are_in_sync_with_the_build_script(tmp_path):
    before = {p.name: p.read_text(encoding="utf-8") for p in [*_presets(), PRESETS / "looks.json"]}
    subprocess.run([sys.executable, str(ROOT / "tools/presets/build.py")], check=True, capture_output=True)
    after = {p.name: p.read_text(encoding="utf-8") for p in [*_presets(), PRESETS / "looks.json"]}
    assert after == before, "run tools/presets/build.py and commit the result"
    assert len(json.loads(before["looks.json"])) == len(_presets())
