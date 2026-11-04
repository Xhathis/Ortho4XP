"""O4_File_Names: tile, folder and file naming."""
import os
import threading

import pytest

import O4_File_Names as FNAMES


@pytest.mark.parametrize("lat,lon,short,rounded,hem", [
    (55, 12, "+55+012", "+50+010", "N55E012"),
    (-5, -67, "-05-067", "-10-070", "S05W067"),
    (43, -66, "+43-066", "+40-070", "N43W066"),
    (0, 0, "+00+000", "+00+000", "N00E000"),
    (-1, -1, "-01-001", "-10-010", "S01W001"),
    (-10, -70, "-10-070", "-10-070", "S10W070"),
    (9, 179, "+09+179", "+00+170", "N09E179"),
    (-90, -180, "-90-180", "-90-180", "S90W180"),
])
def test_latlon_names(lat, lon, short, rounded, hem):
    assert FNAMES.short_latlon(lat, lon) == short
    # X-Plane groups DSFs in 10x10 degree folders named by the south-west
    # corner: tile -05-067 is in -10-070.
    assert FNAMES.round_latlon(lat, lon) == rounded
    assert FNAMES.long_latlon(lat, lon) == os.path.join(rounded, short)
    assert FNAMES.hem_latlon(lat, lon) == hem


def test_build_dir_variants():
    assert FNAMES.build_dir(55, 12, "") == os.path.join(FNAMES.Tile_dir, "zOrtho4XP_+55+012")
    # A trailing separator means "a folder for all tiles".
    assert FNAMES.build_dir(55, 12, "D:/out/") == os.path.join("D:/out", "zOrtho4XP_+55+012")
    assert FNAMES.build_dir(55, 12, "D:\\out\\") == os.path.join("D:\\out", "zOrtho4XP_+55+012")
    # No trailing separator: that exact folder (grouped tiles).
    assert FNAMES.build_dir(55, 12, "D:/grouped") == "D:/grouped"


def test_tile_files():
    d = "B"
    assert FNAMES.mesh_file(d, 55, 12) == os.path.join(d, "Data+55+012.mesh")
    assert FNAMES.dsf_file(d, -5, -67) == os.path.join(
        d, "Earth nav data", os.path.join("-10-070", "-05-067") + ".dsf")
    assert FNAMES.osm_cached(55, 12, "water") == os.path.join(
        FNAMES.OSM_dir, "+50+010", "+55+012", "+55+012_water.osm.bz2")


class _Tile:
    lat, lon, build_dir = 55, 12, "B"

    def __init__(self, iterate):
        self.iterate = iterate


def test_mesh_input_output_files():
    assert FNAMES.input_node_file(_Tile(0)) == os.path.join("B", "Data+55+012.node")
    assert FNAMES.input_poly_file(_Tile(2)) == os.path.join("B", "Data+55+012.2.poly")
    assert FNAMES.output_ele_file(_Tile(0)) == os.path.join("B", "Data+55+012.1.ele")
    assert FNAMES.output_node_file(_Tile(2)) == os.path.join("B", "Data+55+012.3.node")
    assert FNAMES.alt_file(_Tile(0)) == os.path.join("B", "Data+55+012.alt")


def test_imagery_names():
    # Real names from the +55+012 builds: <y>_<x>_<provider><zl>
    assert FNAMES.dds_file_name_from_attributes(69904, 40800, 17, "Arc") == "40800_69904_Arc17.dds"
    assert FNAMES.jpeg_file_name_from_attributes(69904, 40800, 17, "Arc") == "40800_69904_Arc17.jpg"
    assert FNAMES.dds_file_name_from_attributes(1, 2, 16, "GO2", "png") == "2_1_GO216.png"
    assert FNAMES.geotiff_file_name_from_attributes(1, 2, 16, "GO2") == "2_1_GO216-WGS84.tif"
    # g2xpl counts y from the bottom: 2**zl - 16 - y.
    assert FNAMES.dds_file_name_from_attributes(16, 32, 8, "g2xpl_16") == "8_16_208.dds"
    assert FNAMES.legacy_mask(8736, 5088) == "5088_8736.png"
    assert FNAMES.mask_file(8736, 5088, 14, "Arc") == "5088_8736_ZL14.png"


@pytest.mark.parametrize("imagery_dir,expected", [
    ("normal", os.path.join("+55+012", "Arc_17")),
    ("grouped", os.path.join("+50+010", "+55+012", "Arc_17")),
    ("code", os.path.join("Arc", "Arc_17")),
    ("Denmark", os.path.join("Denmark", "Arc_17")),
])
def test_jpeg_dir(imagery_dir, expected):
    provider = {"code": "Arc", "imagery_dir": imagery_dir}
    assert FNAMES.jpeg_file_dir_from_attributes(55, 12, 17, provider) == os.path.join(
        FNAMES.Imagery_dir, expected)
    assert FNAMES.jpeg_file_dir_from_attributes(55, 12, 17, None) == "."


@pytest.mark.parametrize("source,suffix", [
    ("View", ".hgt"), ("SRTM", "_SRTMv3.hgt"), ("ALOS", "_ALOS3W30.tif"),
    ("NED1/3", "_NED13.tif"), ("NED1", "_NED1.tif"),
])
def test_elevation_names(source, suffix):
    # Elevation_data/<10 degree block>/N55E012<suffix>; the default source
    # (View) is the name a user's own .hgt file must have.
    assert FNAMES.elevation_data(source, 55, 12) == os.path.join(
        FNAMES.Elevation_dir, "+50+010", "N55E012" + suffix)


def test_temp_path_is_beside_target_and_unique_per_thread():
    target = os.path.join("some", "dir", "img.jpg")
    names = []
    t = threading.Thread(target=lambda: names.append(FNAMES.temp_path_for(target)))
    t.start()
    t.join()
    mine = FNAMES.temp_path_for(target)
    for name in (mine, names[0]):
        assert os.path.dirname(name) == os.path.dirname(target)
        assert name.endswith("_img.jpg")  # PIL picks the format by extension
        assert os.path.basename(name).startswith(".tmp")
    assert mine != names[0]


def test_finish_temp_file(tmp_path):
    target = tmp_path / "a.bin"
    tmp = FNAMES.temp_path_for(str(target))
    open(tmp, "wb").write(b"new")
    FNAMES.finish_temp_file(tmp, str(target))
    assert target.read_bytes() == b"new" and not os.path.exists(tmp)


def test_finish_temp_file_when_target_is_locked(tmp_path, monkeypatch):
    # Windows refuses to replace a file another process has open: the
    # other copy is complete, so the temp file is just dropped.
    target = tmp_path / "a.bin"
    target.write_bytes(b"other process")
    tmp = FNAMES.temp_path_for(str(target))
    open(tmp, "wb").write(b"mine")

    def locked(src, dst):
        raise PermissionError("in use")
    monkeypatch.setattr(FNAMES.os, "replace", locked)
    FNAMES.finish_temp_file(tmp, str(target))
    assert target.read_bytes() == b"other process" and not os.path.exists(tmp)


def test_finish_temp_file_reraises_without_target(tmp_path, monkeypatch):
    tmp = tmp_path / ".tmp_x"
    tmp.write_bytes(b"x")

    def locked(src, dst):
        raise PermissionError("in use")
    monkeypatch.setattr(FNAMES.os, "replace", locked)
    with pytest.raises(PermissionError):
        FNAMES.finish_temp_file(str(tmp), str(tmp_path / "missing.bin"))
