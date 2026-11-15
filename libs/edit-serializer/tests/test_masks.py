from calotype_edit_serializer.masks import mask_kind, mask_values, shared_masks


def ai(sub, cat=None, **kw):
    m = {"What": "Mask/Image", "MaskSubType": sub, "MaskBlendMode": 0, "MaskInverted": False}
    if cat is not None:
        m["MaskSubCategoryID"] = cat
    m.update(kw)
    return m


def group(*masks, **values):
    return {"What": "Correction", "CorrectionAmount": 1, "CorrectionActive": True,
            "CorrectionMasks": list(masks), **values}


def test_kinds_of_ai_masks():
    assert mask_kind(group(ai(1))) == "subject"
    assert mask_kind(group(ai(2))) == "sky"
    assert mask_kind(group(ai(0, 22))) == "background"
    assert mask_kind(group(ai(3, 2))) == "skin"
    assert mask_kind(group(ai(3, 8), ai(3, 3))) == "eyes"
    assert mask_kind(group(ai(3, 12))) == "teeth"


def test_not_a_learnable_mask():
    brush = {"What": "Mask/Paint", "MaskBlendMode": 0}
    assert mask_kind(group(brush)) is None
    assert mask_kind(group(ai(1), ai(2))) is None                    # two kinds
    assert mask_kind(group(ai(1, MaskInverted=True))) is None         # everything but the subject
    assert mask_kind(group(ai(3, 1))) is None                         # a person part we have no preset for
    assert mask_kind(group(ai(1), CorrectionActive=False)) is None
    assert mask_kind(group()) is None


def test_refining_masks_do_not_change_the_kind():
    subtract = {"What": "Mask/Paint", "MaskBlendMode": 1}
    assert mask_kind(group(ai(1), subtract)) == "subject"


def test_values_with_amount_and_xmp_strings():
    s = {"MaskGroupBasedCorrections": [
        group(ai(1), LocalShadows2012=0.2, LocalExposure2012=0.1, LocalCurveRefineSaturation=100,
              CorrectionAmount=0.5),
        group(ai("2"), LocalHighlights2012="-0.3", CorrectionActive="true"),
    ]}
    v = mask_values(s)
    assert v["subject"]["LocalShadows2012"] == 0.1
    assert v["subject"]["LocalExposure2012"] == 0.05
    assert "LocalCurveRefineSaturation" not in v["subject"]
    assert v["sky"]["LocalHighlights2012"] == -0.3
    assert mask_values({}) == {}


def test_shared_masks_median_and_share():
    def photo(shadows=None, sky=None):
        groups = []
        if shadows is not None:
            groups.append(group(ai(1), LocalShadows2012=shadows))
        if sky is not None:
            groups.append(group(ai(2), LocalHighlights2012=sky))
        return {"MaskGroupBasedCorrections": groups}

    examples = [photo(0.15), photo(0.2, -0.2), photo(0.28), photo()]
    out = shared_masks(examples)
    assert out == {"subject": {"LocalShadows2012": 0.2}}   # sky on 1 of 4 photos: not shared
    assert shared_masks([photo(0.0), photo(0.001)]) == {}  # a mask without adjustment
    assert shared_masks([]) == {}
