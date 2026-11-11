"""#56: config files are replaced in one step, the old one kept as .bak."""
import os
from pathlib import Path

import pytest

import O4_Config_Utils as CFG
import O4_File_Names as FNAMES


def test_new_file_without_backup(tmp_path):
    path = str(tmp_path / "a.cfg")
    FNAMES.write_text_atomic(path, "x=1\n", backup=path + ".bak")
    assert Path(path).read_text() == "x=1\n"
    assert not os.path.exists(path + ".bak")
    assert os.listdir(tmp_path) == ["a.cfg"]


def test_old_file_goes_to_backup(tmp_path):
    path = str(tmp_path / "a.cfg")
    FNAMES.write_text_atomic(path, "x=1\n")
    FNAMES.write_text_atomic(path, "x=2\n", backup=path + ".bak")
    assert Path(path).read_text() == "x=2\n"
    assert Path(path + ".bak").read_text() == "x=1\n"


def test_failed_write_keeps_the_old_file(tmp_path, monkeypatch):
    # Before: the old file was moved to .bak first, so a failing write
    # left no config at all (or a cut one).
    path = str(tmp_path / "a.cfg")
    FNAMES.write_text_atomic(path, "x=1\n")

    real_open = open

    def failing_open(name, mode="r", *a, **k):
        f = real_open(name, mode, *a, **k)
        if "w" in mode:
            f.close()
            raise OSError(28, "No space left on device")
        return f

    monkeypatch.setattr("builtins.open", failing_open)
    with pytest.raises(OSError):
        FNAMES.write_text_atomic(path, "x=2\n", backup=path + ".bak")
    monkeypatch.undo()
    assert Path(path).read_text() == "x=1\n"
    assert sorted(os.listdir(tmp_path)) == ["a.cfg", "a.cfg.bak"]


def test_tile_write_to_config_keeps_backup(tmp_path):
    tile = CFG.Tile(55, 12, str(tmp_path) + os.sep)
    os.makedirs(tile.build_dir, exist_ok=True)
    tile.default_website = "Arc"
    assert tile.write_to_config() == 1
    path = os.path.join(tile.build_dir, "Ortho4XP_+55+012.cfg")
    first = Path(path).read_text()
    assert "default_website=Arc\n" in first
    tile.default_website = "GO2"
    assert tile.write_to_config() == 1
    assert "default_website=GO2\n" in Path(path).read_text()
    assert Path(path + ".bak").read_text() == first
    assert sorted(os.listdir(tile.build_dir)) == [
        "Ortho4XP_+55+012.cfg", "Ortho4XP_+55+012.cfg.bak"]


def test_tile_write_failure_keeps_old_config(tmp_path, monkeypatch):
    tile = CFG.Tile(55, 12, str(tmp_path) + os.sep)
    os.makedirs(tile.build_dir, exist_ok=True)
    assert tile.write_to_config() == 1
    path = os.path.join(tile.build_dir, "Ortho4XP_+55+012.cfg")
    before = Path(path).read_text()

    def fail(path, text, backup=None):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(FNAMES, "write_text_atomic", fail)
    monkeypatch.setattr(CFG.UI, "lvprint", lambda *a: None)
    monkeypatch.setattr(CFG.UI, "vprint", lambda *a: None)
    assert not tile.write_to_config()
    assert Path(path).read_text() == before
