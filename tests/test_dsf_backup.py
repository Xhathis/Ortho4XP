"""#125: keep_dsf_backup decides whether step 3 keeps the previous DSF."""
import pytest

import O4_Cfg_Vars as CFGV
import O4_DSF_Utils as DSF
import O4_UI_Utils as UI


@pytest.fixture
def tile_dsf(tmp_path, monkeypatch):
    monkeypatch.setattr(UI, "log", False)
    dsf = tmp_path / "+55+012.dsf"
    return dsf


def test_default_keeps_backup_as_upstream():
    assert CFGV.cfg_app_vars["keep_dsf_backup"]["default"] is True
    assert UI.keep_dsf_backup is True


def test_setting_is_an_app_setting_in_the_gui():
    assert CFGV.cfg_app_vars["keep_dsf_backup"]["module"] == "UI"
    assert "keep_dsf_backup" in CFGV.list_app_vars
    assert "keep_dsf_backup" in CFGV.gui_app_vars_short


def test_on_moves_old_dsf_to_bak(tile_dsf, monkeypatch):
    monkeypatch.setattr(UI, "keep_dsf_backup", True)
    tile_dsf.write_bytes(b"old")
    DSF.set_aside_old_dsf(str(tile_dsf))
    assert not tile_dsf.exists()
    assert (tile_dsf.parent / "+55+012.dsf.bak").read_bytes() == b"old"


def test_on_without_old_dsf_does_nothing(tile_dsf, monkeypatch):
    monkeypatch.setattr(UI, "keep_dsf_backup", True)
    DSF.set_aside_old_dsf(str(tile_dsf))
    assert list(tile_dsf.parent.iterdir()) == []


def test_off_leaves_old_dsf_active_and_removes_old_bak(tile_dsf, monkeypatch):
    monkeypatch.setattr(UI, "keep_dsf_backup", False)
    tile_dsf.write_bytes(b"current")
    bak = tile_dsf.parent / "+55+012.dsf.bak"
    bak.write_bytes(b"older")
    DSF.set_aside_old_dsf(str(tile_dsf))
    assert tile_dsf.read_bytes() == b"current"
    assert not bak.exists()


def test_off_without_any_file_does_nothing(tile_dsf, monkeypatch):
    monkeypatch.setattr(UI, "keep_dsf_backup", False)
    DSF.set_aside_old_dsf(str(tile_dsf))
    assert list(tile_dsf.parent.iterdir()) == []


def test_off_with_unremovable_bak_warns(tile_dsf, monkeypatch):
    monkeypatch.setattr(UI, "keep_dsf_backup", False)
    tile_dsf.write_bytes(b"current")
    # A directory under the .bak name cannot be removed with os.remove.
    (tile_dsf.parent / "+55+012.dsf.bak").mkdir()
    lines = []
    monkeypatch.setattr(UI, "lvprint", lambda level, *a: lines.append(a))
    DSF.set_aside_old_dsf(str(tile_dsf))
    assert tile_dsf.read_bytes() == b"current"
    assert any("WARNING" in str(a[0]) for a in lines)


@pytest.mark.parametrize("text,value", [("False", False), ("True", True)])
def test_config_value_parses(text, value):
    assert CFGV.parse_cfg_value("keep_dsf_backup", text) is value
