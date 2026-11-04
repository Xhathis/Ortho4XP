"""O4_Config_Utils: reading and writing tile configs.

conftest.py runs the tests in an empty temporary folder, so importing
O4_Config_Utils creates a default Ortho4XP.cfg there, not in the repo.
"""
import os

import pytest

import O4_Config_Utils as CFG


def test_config_compatibility_strips_old_quotes():
    assert CFG.config_compatibility('"Arc"') == "Arc"
    assert CFG.config_compatibility("'Arc'") == "Arc"
    assert CFG.config_compatibility("Arc") == "Arc"
    assert CFG.config_compatibility("") == ""


def test_default_global_config_was_created_in_sandbox():
    assert os.path.isfile(CFG.global_cfg_file)
    assert os.path.dirname(CFG.global_cfg_file) == os.getcwd()


@pytest.fixture
def tile(tmp_path):
    return CFG.Tile(55, 12, str(tmp_path) + os.sep)


def _write_cfg(tile, text):
    os.makedirs(tile.build_dir, exist_ok=True)
    path = os.path.join(tile.build_dir, "Ortho4XP_+55+012.cfg")
    with open(path, "w") as f:
        f.write(text)
    return path


def test_read_tile_config_types(tile):
    _write_cfg(tile, "\n".join([
        "# comment",
        "",
        "default_website=GO2",
        "default_zl=16",
        "curvature_tol=1.5",
        "cover_airports_with_highres=ICAO",
        "use_masks_for_inland=True",
        "zone_list=[]",
        "custom_dem=",
    ]) + "\n")
    assert tile.read_from_config() == 1
    assert tile.default_website == "GO2"
    assert tile.default_zl == 16 and isinstance(tile.default_zl, int)
    assert tile.curvature_tol == 1.5 and isinstance(tile.curvature_tol, float)
    assert tile.cover_airports_with_highres == "ICAO"  # a str option
    assert tile.use_masks_for_inland is True
    assert tile.zone_list == []
    assert tile.custom_dem == ""


def test_read_tile_config_skips_bad_lines(tile):
    before = tile.curvature_tol
    _write_cfg(tile, "no_equals_sign\nunknown_key=1\ncurvature_tol=abc\ndefault_zl=18\n")
    assert tile.read_from_config() == 1
    assert tile.curvature_tol == before  # bad value: kept the old one
    assert tile.default_zl == 18


def test_read_old_style_config(tile):
    # Configs from version <= 1.20 quoted strings and appended zones.
    zone = [[55, 12, 55, 12.5, 55.5, 12.5, 55.5, 12, 55, 12], 18, "Arc"]
    _write_cfg(tile, "default_website='Arc'\nzone_list=[]\nzone_list.append("
               + repr(zone) + ")\n")
    assert tile.read_from_config() == 1
    assert tile.default_website == "Arc"
    assert tile.zone_list == [zone]


def test_tile_config_round_trip(tile):
    tile.default_website, tile.default_zl, tile.curvature_tol = "GO2", 16, 1.25
    os.makedirs(tile.build_dir, exist_ok=True)
    assert tile.write_to_config() == 1
    again = CFG.Tile(55, 12, os.path.dirname(tile.build_dir) + os.sep)
    assert again.read_from_config() == 1
    for var in CFG.list_tile_vars:
        if var != "zone_list":  # written from the global zone list
            assert getattr(again, var) == getattr(tile, var), var


def test_write_to_config_keeps_a_backup(tile):
    os.makedirs(tile.build_dir, exist_ok=True)
    tile.default_zl = 16
    tile.write_to_config()
    tile.default_zl = 17
    tile.write_to_config()
    bak = os.path.join(tile.build_dir, "Ortho4XP_+55+012.cfg.bak")
    assert "default_zl=16" in open(bak).read()


def test_write_to_config_to_given_file(tile, tmp_path):
    # The config_file argument used to crash: the .bak name was only set
    # when no file was given (UnboundLocalError).
    path = str(tmp_path / "copy.cfg")
    tile.default_zl = 15
    assert tile.write_to_config(path) == 1
    assert "default_zl=15" in open(path).read()
    tile.default_zl = 14
    assert tile.write_to_config(path) == 1
    assert "default_zl=15" in open(path + ".bak").read()


def test_no_config_found(tmp_path, monkeypatch):
    tile = CFG.Tile(55, 12, str(tmp_path) + os.sep)
    monkeypatch.setattr(CFG, "global_cfg_file", str(tmp_path / "missing.cfg"))
    assert tile.read_from_config() == 0
