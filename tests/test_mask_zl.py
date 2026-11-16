"""mask_zl above the tile's imagery zoom level (#109)."""
from types import SimpleNamespace

import pytest

import O4_Mask_Utils as MASK
import O4_UI_Utils as UI


@pytest.fixture
def lines(monkeypatch):
    seen = []
    monkeypatch.setattr(UI, "lvprint", lambda *a: seen.append(
        " ".join(str(x) for x in a[1:])))
    return seen


def tile(default_zl, mask_zl, zones=()):
    zone_list = [([72, -40, 72, -39, 73, -39, 72, -40], zl, "GO2")
                 for zl in zones]
    return SimpleNamespace(lat=72, lon=-40, default_zl=default_zl,
                           mask_zl=mask_zl, zone_list=zone_list,
                           build_dir="")


def test_zl15_tile_gets_masks(lines):
    t = tile(15, 16)
    # Before: no mask name, so build_dsf gave water triangles no imagery.
    assert MASK.mask_name_for_texture(t, 23456, 12345, 15) == ""
    MASK.fit_mask_zl(t)
    assert t.mask_zl == 15
    assert MASK.mask_name_for_texture(t, 23456, 12345, 15) != ""
    assert len(lines) == 1 and "mask_zl 16" in lines[0] \
        and "ZL15" in lines[0] and "+72-040" in lines[0]


def test_lowest_zone_decides(lines):
    t = tile(16, 16, zones=(18, 14))
    MASK.fit_mask_zl(t)
    assert t.mask_zl == 14 and len(lines) == 1


@pytest.mark.parametrize("default_zl,mask_zl", [(16, 16), (17, 14), (16, 15)])
def test_mask_zl_at_or_below_stays(lines, default_zl, mask_zl):
    t = tile(default_zl, mask_zl, zones=(18,))
    MASK.fit_mask_zl(t)
    assert t.mask_zl == mask_zl and lines == []


def test_string_zoom_levels(lines):
    # The GUI may hand the zoom level over as text.
    t = tile("15", 16)
    MASK.fit_mask_zl(t)
    assert t.mask_zl == 15
