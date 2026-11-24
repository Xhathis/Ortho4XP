"""The DFA combined provider and the Denmark_DF extent (DF itself needs a
personal token in the untracked Providers/Denmark/DF.lay)."""
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


def test_df_token_file_is_ignored_by_git():
    with open(os.path.join(REPO, ".gitignore"), encoding="utf-8") as f:
        assert "Providers/Denmark/DF.lay" in f.read().split()


def test_dfa_puts_df_over_go2(img):
    if "DF" not in img.providers_dict:
        pytest.skip("no Providers/Denmark/DF.lay (needs a personal token)")
    layers = [(r["layer_code"], r["extent_code"], r["priority"])
              for r in img.combined_providers_dict["DFA"]]
    assert layers == [("DF", "Denmark_DF", "high"), ("GO2", "global", "high")]


@pytest.mark.parametrize("lon, lat, covered", [
    (12.656, 55.618, True),    # Kastrup
    (10.588, 57.721, True),    # Skagen
    (9.43, 54.79, False),      # Flensburg, Germany
    (13.00, 55.60, False),     # Malmo, Sweden
    (11.50, 56.80, False),     # Kattegat, open sea
])
def test_denmark_extent_follows_df_coverage(img, lon, lat, covered):
    d = 0.002
    assert bool(img.has_data((lon, lat + d, lon + d, lat), "Denmark_DF")) is covered
