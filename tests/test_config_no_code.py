"""Config values are read as data, never run as code (#84).

bool and list settings in Ortho4XP.cfg and tile configs, old-style
zone_list.append lines, and fake_headers / in_GUI in provider .lay files
went through exec() / eval(): a shared config or .lay file could run any
command. Each test plants a value that would create a marker file if it
were run.
"""
import os

import pytest

import O4_Cfg_Vars
import O4_Config_Utils as CFG
import O4_Imagery_Utils as IMG
import O4_UI_Utils as UI


def _payload(marker):
    path = str(marker).replace("\\", "/")
    return f"open('{path}', 'w')"


@pytest.fixture(autouse=True)
def _no_log(monkeypatch):
    monkeypatch.setattr(UI, "log", False)


@pytest.mark.parametrize("text, expected", [
    ("True", True), ("False", False), (" True", True), ("1", 1),
    ("True # comment", True),
])
def test_parse_bool(text, expected):
    assert O4_Cfg_Vars.parse_cfg_value("use_masks_for_inland", text) == expected


@pytest.mark.parametrize("text, expected", [
    ("[]", []), ("[0]", [0]), ("100", 100), ("[50, 100]", [50, 100]),
    ("[[[55.1, 12.1, 55.2, 12.2], 18, 'GO2']]",
     [[[55.1, 12.1, 55.2, 12.2], 18, "GO2"]]),
])
def test_parse_list(text, expected):
    var = "zone_list" if "GO2" in text else (
        "masks_width" if text in ("100", "[50, 100]") else "ovl_exclude_pol")
    assert O4_Cfg_Vars.parse_cfg_value(var, text) == expected


def test_parse_other_types_as_before():
    assert O4_Cfg_Vars.parse_cfg_value("default_zl", "16") == 16
    assert O4_Cfg_Vars.parse_cfg_value("curvature_tol", "1.5") == 1.5
    assert O4_Cfg_Vars.parse_cfg_value("default_website", "GO2") == "GO2"
    with pytest.raises(ValueError):
        O4_Cfg_Vars.parse_cfg_value("curvature_tol", "abc")
    with pytest.raises(KeyError):
        O4_Cfg_Vars.parse_cfg_value("no_such_setting", "1")


@pytest.mark.parametrize("text", [
    "true", "__import__('os').getcwd()", "[open('x')]", "2**3",
])
def test_parse_rejects_code(text):
    with pytest.raises(ValueError):
        O4_Cfg_Vars.parse_cfg_value("use_masks_for_inland", text)


def test_legacy_zone_line():
    zone = [[55.1, 12.1, 55.2, 12.2], 18, "GO2"]
    assert O4_Cfg_Vars.parse_legacy_zone(
        "zone_list.append([[55.1, 12.1, 55.2, 12.2], 18, 'GO2'])") == zone
    assert O4_Cfg_Vars.parse_legacy_zone(
        "self.zone_list.append([[55.1, 12.1, 55.2, 12.2], 18, 'GO2'])") == zone
    assert O4_Cfg_Vars.parse_legacy_zone("zone_list=[]") is None
    assert O4_Cfg_Vars.parse_legacy_zone(
        "zone_list.append(__import__('os').getcwd())") is None


@pytest.fixture
def tile(tmp_path):
    t = CFG.Tile(55, 12, str(tmp_path) + os.sep)
    t.zone_list = []
    return t


def _write_cfg(tile, lines):
    os.makedirs(tile.build_dir, exist_ok=True)
    path = os.path.join(tile.build_dir, "Ortho4XP_+55+012.cfg")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return path


def test_tile_config_value_is_not_run(tile, tmp_path):
    marker = tmp_path / "ran.txt"
    _write_cfg(tile, [
        "use_masks_for_inland=" + _payload(marker),
        "masks_width=[" + _payload(marker) + "]",
        "default_zl=16",
    ])
    assert tile.read_from_config() == 1
    assert not marker.exists()
    assert tile.default_zl == 16


def test_tile_config_legacy_zone_line(tile, tmp_path):
    marker = tmp_path / "ran.txt"
    _write_cfg(tile, [
        "zone_list.append([[55.1, 12.1, 55.2, 12.2], 18, 'GO2'])",
        "zone_list.append(" + _payload(marker) + ")",
    ])
    assert tile.read_from_config() == 1
    assert not marker.exists()
    assert tile.zone_list == [[[55.1, 12.1, 55.2, 12.2], 18, "GO2"]]


def test_global_setting_is_not_run(tmp_path):
    marker = tmp_path / "ran.txt"
    before = CFG.use_masks_for_inland
    with pytest.raises(ValueError):
        CFG.set_global_variables("use_masks_for_inland", _payload(marker))
    assert not marker.exists()
    assert CFG.use_masks_for_inland == before


def test_global_setting_in_other_module(monkeypatch):
    monkeypatch.setattr(IMG, "http_timeout", IMG.http_timeout)
    CFG.set_global_variables("http_timeout", "12.5")
    assert IMG.http_timeout == 12.5
    assert CFG.get_cfg_variable("http_timeout") == 12.5


def test_lay_value_with_name():
    value = "{'User-Agent': user_agent_generic, 'Referer': 'x'}"
    assert IMG.literal_with_names(value, {"user_agent_generic": "UA"}) == {
        "User-Agent": "UA", "Referer": "x"}


def test_lay_value_is_not_run(tmp_path):
    marker = tmp_path / "ran.txt"
    with pytest.raises(ValueError):
        IMG.literal_with_names(
            "{'a': " + _payload(marker) + "}", {"user_agent_generic": "UA"})
    assert not marker.exists()
