"""build_overlay when the Global Scenery has no DSF for the tile."""
import os

import pytest

import O4_File_Names as FNAMES
import O4_Overlay_Utils as OVL
import O4_UI_Utils as UI


@pytest.fixture
def ovl(tmp_path, monkeypatch):
    monkeypatch.setattr(FNAMES, "Tmp_dir", str(tmp_path / "tmp"))
    os.makedirs(FNAMES.Tmp_dir)
    monkeypatch.setattr(OVL, "custom_overlay_src_alternate", "")
    monkeypatch.setattr(UI, "is_working", 0)
    monkeypatch.setattr(UI, "red_flag", False)
    lines = []
    monkeypatch.setattr(UI, "vprint", lambda *a: None)
    monkeypatch.setattr(UI, "logprint",
                        lambda *a: lines.append(" ".join(map(str, a))))
    monkeypatch.setattr(UI, "lvprint",
                        lambda level, *a: lines.append(" ".join(map(str, a))))
    return lines


def test_tile_without_dsf_is_a_warning(ovl, tmp_path, monkeypatch):
    src = tmp_path / "Global Scenery"
    os.makedirs(src / "Earth nav data" / "+30-030")
    monkeypatch.setattr(OVL, "custom_overlay_src", str(src))
    assert OVL.build_overlay(37, -25) == 1
    assert not UI.is_working
    assert any("WARNING: no overlay for tile +37-025" in line
               and "+37-025.dsf absent" in line for line in ovl)
    assert ovl[-1].endswith("normal exit.")
    assert not any("ERROR" in line for line in ovl)
    assert os.listdir(FNAMES.Tmp_dir) == []


def test_source_without_earth_nav_data_stays_an_error(ovl, tmp_path,
                                                      monkeypatch):
    monkeypatch.setattr(OVL, "custom_overlay_src", str(tmp_path / "nowhere"))
    assert OVL.build_overlay(37, -25) == 0
    assert not UI.is_working
    assert any("ERROR: overlay for tile +37-025 not extracted" in line
               and "absent" in line for line in ovl)


def test_unset_source_stays_an_error(ovl, monkeypatch):
    monkeypatch.setattr(OVL, "custom_overlay_src", "")
    assert OVL.build_overlay(37, -25) == 0
    assert any("custom_overlay_src is not set" in line for line in ovl)
