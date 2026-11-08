"""#76: use_decal_on_terrain puts the decal on land terrain only."""
import os
import types

import pytest

import O4_DSF_Utils as DSF


def _tile(tmp_path, decal):
    # The ratio_water overlay copies Utils/water_transition.png unless the
    # tile has it; Utils follows the cwd, a temp folder in the tests.
    os.makedirs(os.path.join(tmp_path, "textures"), exist_ok=True)
    open(os.path.join(tmp_path, "textures", "water_transition.png"),
         "wb").close()
    return types.SimpleNamespace(
        build_dir=str(tmp_path), use_decal_on_terrain=decal,
        terrain_casts_shadows=True, imprint_masks_to_dds=True, mask_zl=16,
    )


def _ter(tmp_path, tile, tri_type, is_overlay=False):
    name = DSF.create_terrain_file(
        tile, "40960_69984_Arc17.dds", 40960, 69984, 17, "Arc",
        tri_type, is_overlay,
    )
    with open(os.path.join(tmp_path, "terrain", name)) as f:
        return f.read()


@pytest.mark.parametrize("tri_type,is_overlay,want", [
    (0, False, True),           # land
    (1, False, False),          # inland water (XP12 water)
    (2, False, False),          # masked sea (XP12 water)
    (1, "ratio_water", False),  # inland water overlay
    (2, True, False),           # sea overlay
])
def test_decal_only_on_land(tmp_path, tri_type, is_overlay, want):
    text = _ter(tmp_path, _tile(tmp_path, True), tri_type, is_overlay)
    assert ("DECAL_LIB" in text) is want


def test_no_decal_when_off(tmp_path):
    for tri_type in (0, 1, 2):
        assert "DECAL_LIB" not in _ter(tmp_path, _tile(tmp_path, False),
                                       tri_type)
