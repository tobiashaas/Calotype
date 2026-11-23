"""The project's own looks (presets/): valid presets, look settings only, in sync with the build."""

from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from calotype_edit_serializer.masks import mask_kind
from calotype_edit_serializer.retouch_kinds import RETOUCH_IDS
from calotype_edit_serializer.style import PHOTO_DEPENDENT, is_style_key

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


PLUGIN = ROOT / "apps/lr-plugin/Calotype.lrplugin"
# Written by the build script from its RETOUCH list besides presets/ (the retouch kinds).
GENERATED = [ROOT / "libs/edit-serializer/src/calotype_edit_serializer/retouch_kinds.py",
             PLUGIN / "RetouchKinds.lua", PLUGIN / "TranslatedStrings_de.txt"]


def _all_files():
    return [*_presets(), PRESETS / "looks.json", *sorted((PRESETS / "retouch").iterdir()), *GENERATED]


def test_retouch_presets_carry_one_named_ai_mask_correction_each():
    retouch = sorted((PRESETS / "retouch").glob("*.xmp"))
    assert len(retouch) >= 6
    for path in retouch:
        desc = ET.parse(path).getroot().find(f"{RDF}RDF/{RDF}Description")
        groups = list(desc.find(f"{CRS}MaskGroupBasedCorrections").iter(f"{RDF}Description"))
        assert len(groups) == 1, path.name
        assert groups[0].get(f"{CRS}CorrectionName") == f"Calotype {path.stem}"
        masks = list(groups[0].find(f"{CRS}CorrectionMasks").iter(f"{RDF}li"))
        assert masks and all(m.get(f"{CRS}What") == "Mask/Image" for m in masks), path.name
        assert all(-1 <= float(v) <= 1 for k, v in groups[0].attrib.items() if k.startswith(f"{CRS}Local"))


def test_presets_are_in_sync_with_the_build_script(tmp_path):
    before = {p.name: p.read_text(encoding="utf-8") for p in _all_files()}
    subprocess.run([sys.executable, str(ROOT / "tools/presets/build.py")], check=True, capture_output=True)
    after = {p.name: p.read_text(encoding="utf-8") for p in _all_files()}
    changed = sorted(name for name in after if after[name] != before[name])
    assert not changed, f"run tools/presets/build.py and commit the result: {changed}"
    assert len(json.loads(before["looks.json"])) == len(_presets())


def test_every_retouch_preset_is_learned_as_its_own_kind():
    """The masks a retouch preset adds are the kind edit-serializer learns under its id."""
    manifest = json.loads((PRESETS / "retouch/retouch.json").read_text(encoding="utf-8"))
    assert [r["id"] for r in manifest] == list(RETOUCH_IDS)
    for r in manifest:
        desc = ET.parse(PRESETS / "retouch" / r["file"]).getroot().find(f"{RDF}RDF/{RDF}Description")
        xmp = next(desc.find(f"{CRS}MaskGroupBasedCorrections").iter(f"{RDF}Description"))
        group = {k[len(CRS):]: v for k, v in xmp.attrib.items() if k.startswith(CRS)}
        group["CorrectionMasks"] = [{k[len(CRS):]: v for k, v in li.attrib.items() if k.startswith(CRS)}
                                    for li in xmp.find(f"{CRS}CorrectionMasks").iter(f"{RDF}li")]
        assert group["CorrectionName"] == r["correction"]
        assert mask_kind(group) == r["id"], r["file"]
        for m in r["masks"]:   # each mask alone counts as the kind too
            one = {"What": "Mask/Image", "MaskSubType": m["subtype"], "MaskBlendMode": 0}
            if m["category"] is not None:
                one["MaskSubCategoryID"] = m["category"]
            assert mask_kind({**group, "CorrectionMasks": [one]}) == r["id"], (r["id"], m)
