"""#49: a DDS is written under a temporary name and moved into place."""
import os
import time
import types

import pytest
from PIL import Image

import O4_File_Names as FNAMES
import O4_Imagery_Utils as IMG
import O4_Tile_Utils as TILE
import O4_UI_Utils as UI

ATTRS = (69952, 40576, 17, "TST")


@pytest.fixture
def setup(tmp_path, monkeypatch):
    jpeg_dir = tmp_path / "imagery"
    jpeg_dir.mkdir()
    Image.new("RGB", (64, 64), "green").save(
        jpeg_dir / FNAMES.jpeg_file_name_from_attributes(*ATTRS)
    )
    (tmp_path / "tile" / "textures").mkdir(parents=True)
    monkeypatch.setitem(IMG.providers_dict, "TST",
                        {"code": "TST", "color_filters": "none"})
    monkeypatch.setattr(FNAMES, "jpeg_file_dir_from_attributes",
                        lambda *a: str(jpeg_dir))
    monkeypatch.setattr(IMG, "failed_conversions", [])
    monkeypatch.setattr(IMG.time, "sleep", lambda s: None)
    monkeypatch.setattr(UI, "lvprint", lambda *a: None)
    tile = types.SimpleNamespace(
        build_dir=str(tmp_path / "tile"), lat=55, lon=12,
        imprint_masks_to_dds=False, mask_zl=14,
    )
    target = os.path.join(tile.build_dir, "textures",
                          FNAMES.dds_file_name_from_attributes(*ATTRS))
    return tile, target


def _textures(tile):
    return sorted(os.listdir(os.path.join(tile.build_dir, "textures")))


def _fake_converter(monkeypatch, exit_code, content=b"DDS complete"):
    calls = []

    def call(cmd, **kwargs):
        calls.append(cmd)
        with open(cmd[-1], "wb") as f:
            f.write(content)
        return exit_code

    monkeypatch.setattr(IMG.subprocess, "call", call)
    return calls


def test_success_puts_the_dds_in_place(setup, monkeypatch):
    tile, target = setup
    calls = _fake_converter(monkeypatch, 0)
    IMG.convert_texture(tile, *ATTRS)
    assert calls[0][-1] != target  # written under another name
    assert open(target, "rb").read() == b"DDS complete"
    assert _textures(tile) == [os.path.basename(target)]
    assert IMG.failed_conversions == []


def test_failed_converter_leaves_no_partial_dds(setup, monkeypatch):
    tile, target = setup
    _fake_converter(monkeypatch, 1, b"DDS cut off")
    IMG.convert_texture(tile, *ATTRS)
    assert _textures(tile) == []
    assert IMG.failed_conversions == [os.path.basename(target)]


def test_failed_converter_keeps_the_old_dds(setup, monkeypatch):
    tile, target = setup
    with open(target, "wb") as f:
        f.write(b"old DDS")
    _fake_converter(monkeypatch, 1, b"DDS cut off")
    IMG.convert_texture(tile, *ATTRS)
    assert open(target, "rb").read() == b"old DDS"
    assert _textures(tile) == [os.path.basename(target)]


def test_converter_that_writes_nothing_counts_as_failed(setup, monkeypatch):
    tile, target = setup
    monkeypatch.setattr(IMG.subprocess, "call", lambda cmd, **kw: 0)
    IMG.convert_texture(tile, *ATTRS)
    assert not os.path.exists(target)
    assert IMG.failed_conversions == [os.path.basename(target)]


def test_stale_temp_files_are_removed_fresh_ones_kept(tmp_path):
    old = tmp_path / ".tmp123_456_a.dds"
    new = tmp_path / ".tmp123_789_b.dds"
    keep = tmp_path / "c.dds"
    for p in (old, new, keep):
        p.write_bytes(b"x")
    past = time.time() - 7200
    os.utime(old, (past, past))
    TILE._remove_stale_temp_files(str(tmp_path))
    assert sorted(os.listdir(tmp_path)) == [".tmp123_789_b.dds", "c.dds"]
