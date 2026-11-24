"""The FOA combined provider: FO only where its extent says it has data."""
import os

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def img(monkeypatch):
    import O4_File_Names as FNAMES
    import O4_Imagery_Utils as IMG
    monkeypatch.setattr(FNAMES, "Provider_dir", os.path.join(REPO, "Providers"))
    monkeypatch.setattr(FNAMES, "Extent_dir", os.path.join(REPO, "Extents"))
    monkeypatch.setattr(FNAMES, "Filter_dir", os.path.join(REPO, "Filters"))
    # fresh module dicts, put back after the test: the real providers must
    # not leak into later tests (fallback providers would be asked)
    for name in ("providers_dict", "extents_dict", "combined_providers_dict",
                 "color_filters_dict"):
        monkeypatch.setattr(IMG, name, dict(getattr(IMG, name)))
    IMG.initialize_color_filters_dict()
    IMG.initialize_extents_dict()
    IMG.initialize_providers_dict()
    IMG.initialize_combined_providers_dict()
    return IMG


def test_foa_puts_fo_over_arc(img):
    layers = [(r["layer_code"], r["extent_code"], r["priority"])
              for r in img.combined_providers_dict["FOA"]]
    # combine_textures draws the list bottom up: the first line is on top.
    assert layers == [("FO", "Faroe", "high"), ("Arc", "global", "high")]
    assert img.providers_dict["FO"]["request_type"] == "wms"


@pytest.mark.parametrize("lon, lat, covered", [
    (-6.775, 62.008, True),    # Torshavn
    (-7.277, 62.064, True),    # Vagar airport
    (-6.30, 62.00, False),     # open sea east of Eysturoy
    (-7.70, 61.40, False),     # open sea south-west of Suduroy
])
def test_faroe_extent_follows_fo_coverage(img, lon, lat, covered):
    d = 0.002  # about 100 x 200 m
    assert bool(img.has_data((lon, lat + d, lon + d, lat), "Faroe")) is covered
