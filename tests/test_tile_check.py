"""#157: step 3 checks the DSF it built for the faults that once reached
built tiles without any error (#146 UVs, #155 hubs, missing files)."""
import os
import struct

import numpy
import pytest

import O4_Cfg_Vars as CFGV
import O4_File_Names as FNAMES
import O4_Tile_Check as TCHECK
import O4_Tile_Utils as TILE
import O4_UI_Utils as UI

LAT, LON = 55, 12
ZL = 16


# --- a minimal DSF writer ----------------------------------------------------
def _atom(name, body):
    return name[::-1] + struct.pack("<I", len(body) + 8) + body


def _quantize(vals, scale, off):
    raw = numpy.round((numpy.asarray(vals, float) - off) / scale * 65535)
    raw = numpy.clip(raw, 0, 65535).astype("<u2")
    return raw, raw / 65535.0 * scale + off


def write_dsf(path, terrains, pool, patches):
    """pool: (n, 9) float rows lon, lat, elev, nx, ny, u, v, u2, v2;
    patches: list of (terrain index, flag, triangles as index triples)."""
    pool = numpy.asarray(pool, float)
    (n, planes) = pool.shape
    scal = [(1.0, LON), (1.0, LAT), (0.0, 0.0), (2.0, -1.0), (2.0, -1.0)]
    scal += [(1.0, 0.0)] * (planes - 5)
    body = struct.pack("<IB", n, planes)
    for p in range(planes):
        (scale, off) = scal[p]
        raw = (numpy.round(pool[:, p]).astype("<u2") if scale == 0
               else _quantize(pool[:, p], scale, off)[0])
        body += b"\x00" + raw.tobytes()
    geod = _atom(b"POOL", body) + _atom(
        b"SCAL", numpy.array(scal, "<f4").tobytes())
    tert = "".join(t + "\0" for t in terrains).encode("latin-1")
    cmds = b"\x01" + struct.pack("<H", 0)
    for (ter, flag, tris) in patches:
        cmds += b"\x04" + struct.pack("<H", ter)
        cmds += b"\x12" + struct.pack("<Bff", flag, 0.0, -1.0)
        tris = list(tris)
        for i in range(0, len(tris), 80):
            idx = [k for t in tris[i:i + 80] for k in t]
            cmds += b"\x17" + struct.pack(f"<B{len(idx)}H", len(idx), *idx)
    data = (b"XPLNEDSF" + struct.pack("<I", 1)
            + _atom(b"DEFN", _atom(b"TERT", tert)) + _atom(b"GEOD", geod)
            + _atom(b"CMDS", cmds) + b"\0" * 16)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def texture_of(lat, lon):
    """(til_y, til_x) of the ZL16 texture holding a point, as Ortho4XP
    names them (4096 pixels, top-left tile a multiple of 16)."""
    (gx, gy) = TCHECK._merc_texels(numpy.array([lon]), numpy.array([lat]), ZL)
    return int(gy[0] // 4096) * 16, int(gx[0] // 4096) * 16


def grid_tile(build_dir, nx=6, ny=6, uv_shift=0.0, sea=False, mask=False,
              hub=0, tex_missing=False):
    """A tile with one texture: a (nx x ny) grid of points inside it, two
    triangles per cell; hub adds that many thin triangles at one point."""
    (ty, tx) = texture_of(LAT + 0.5, LON + 0.5)
    suffix = "_sea" if sea else ""
    ter = f"terrain/{ty}_{tx}_BI{ZL}{suffix}.ter"
    # the texture spans 4096 px from (tx * 256, ty * 256); keep inside it
    lon0 = (tx * 256 + 200) / (2 ** ZL * 256) * 360 - 180
    lon1 = (tx * 256 + 3800) / (2 ** ZL * 256) * 360 - 180

    def lat_of(py):
        y = py / (2 ** ZL * 256)
        return numpy.degrees(numpy.arctan(numpy.sinh(numpy.pi * (1 - 2 * y))))
    lat0, lat1 = lat_of(ty * 256 + 3800), lat_of(ty * 256 + 200)
    lons = numpy.linspace(lon0, lon1, nx)
    lats = numpy.linspace(lat0, lat1, ny)
    pts = numpy.array([(x, y) for y in lats for x in lons])
    # as the DSF will store them, so the UVs below are exact
    pts[:, 0] = _quantize(pts[:, 0], 1.0, LON)[1]
    pts[:, 1] = _quantize(pts[:, 1], 1.0, LAT)[1]
    (gx, gy) = TCHECK._merc_texels(pts[:, 0], pts[:, 1], ZL)
    u = (gx - tx * 256) / 4096 + uv_shift / 4096
    v = 1 - (gy - ty * 256) / 4096
    pool = numpy.zeros((len(pts), 9))
    pool[:, 0:2] = pts
    if sea:
        pool[:, 5:7] = 1.0
        pool[:, 7], pool[:, 8] = u, v
    else:
        pool[:, 5], pool[:, 6] = u, v
        pool[:, 7], pool[:, 8] = u, v
    tris = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            a = j * nx + i
            tris += [(a, a + 1, a + nx + 1), (a, a + nx + 1, a + nx)]
    centre = (ny // 2) * nx + nx // 2
    # the same small triangle again and again: no long edge, one hub
    tris += [(centre, centre + 1, centre + nx + 1)] * hub
    patches = [(0, 1, tris)]
    if mask:
        patches.append((0, 2, tris[:4]))
    write_dsf(FNAMES.dsf_file(build_dir, LAT, LON), [ter], pool, patches)
    os.makedirs(os.path.join(build_dir, "terrain"), exist_ok=True)
    os.makedirs(os.path.join(build_dir, "textures"), exist_ok=True)
    dds = f"{ty}_{tx}_BI{ZL}.dds"
    with open(os.path.join(build_dir, ter), "w") as f:
        f.write(f"A\n800\nTERRAIN\n\nBASE_TEX_NOWRAP ../textures/{dds}\n")
    if not tex_missing:
        open(os.path.join(build_dir, "textures", dds), "wb").close()
    return ter


@pytest.fixture
def build_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(UI, "log", False)
    return str(tmp_path / "zOrtho4XP_+55+012")


# --- the checks ---------------------------------------------------------------
def test_clean_tile_has_no_warning(build_dir):
    grid_tile(build_dir)
    res = TCHECK.check_dsf(FNAMES.dsf_file(build_dir, LAT, LON), build_dir)
    assert res["triangles"] == 50
    assert res["uv_bad"] == 0 and res["missing_files"] == 0
    assert TCHECK.warnings_of(res) == []
    assert TCHECK.check_tile(build_dir, LAT, LON) == []
    assert TCHECK.read_result(build_dir, LAT, LON) == []


def test_hub_is_flagged_with_its_place(build_dir):
    # #155: tens of thousands of triangles around one vertex
    grid_tile(build_dir, hub=500)
    w = TCHECK.check_tile(build_dir, LAT, LON)
    assert len(w) == 1 and "triangles meet at one point" in w[0]
    assert TCHECK.read_result(build_dir, LAT, LON) == w


def test_texture_uv_offset_is_flagged(build_dir):
    # #146: UVs hundreds of texels from where the point lies
    grid_tile(build_dir, uv_shift=20)
    w = TCHECK.check_tile(build_dir, LAT, LON)
    assert any("texture coordinate(s) off by more than" in x for x in w)


def test_rounding_sized_uv_error_is_not_flagged(build_dir):
    grid_tile(build_dir, uv_shift=2)
    assert TCHECK.check_tile(build_dir, LAT, LON) == []


def test_sea_terrain_uv_is_read_from_planes_7_8(build_dir):
    # XP12 water: planes 5-6 hold water parameters, not a UV
    grid_tile(build_dir, sea=True)
    assert TCHECK.check_tile(build_dir, LAT, LON) == []
    grid_tile(build_dir, sea=True, uv_shift=20)
    assert TCHECK.check_tile(build_dir, LAT, LON)


def test_mask_patch_with_matching_uv_is_clean(build_dir):
    grid_tile(build_dir, mask=True)
    assert TCHECK.check_tile(build_dir, LAT, LON) == []


def test_missing_texture_is_flagged(build_dir):
    grid_tile(build_dir, tex_missing=True)
    w = TCHECK.check_tile(build_dir, LAT, LON)
    assert len(w) == 1 and "missing" in w[0] and ".dds" in w[0]


def test_unreadable_dsf_is_a_warning_not_an_error(build_dir):
    dsf = FNAMES.dsf_file(build_dir, LAT, LON)
    os.makedirs(os.path.dirname(dsf))
    with open(dsf, "wb") as f:
        f.write(b"XPLNEDSF\1\0\0\0" + b"\xff" * 40)
    w = TCHECK.check_tile(build_dir, LAT, LON)
    assert len(w) == 1 and "could not be read back" in w[0]
    assert TCHECK.read_result(build_dir, LAT, LON) == w


def test_missing_dsf_is_a_warning_not_an_error(build_dir):
    os.makedirs(build_dir)
    w = TCHECK.check_tile(build_dir, LAT, LON)
    assert len(w) == 1 and "could not be read back" in w[0]


def test_old_result_is_not_read_as_this_batch(build_dir):
    grid_tile(build_dir, hub=500)
    TCHECK.check_tile(build_dir, LAT, LON)
    path = FNAMES.tile_check_file(build_dir, LAT, LON)
    os.utime(path, (1000, 1000))
    assert TCHECK.read_result(build_dir, LAT, LON, since=2000) is None
    assert TCHECK.read_result(build_dir, LAT, LON, since=0)


def test_batch_summary_lists_check_warnings(tmp_path, monkeypatch):
    lines = []
    monkeypatch.setattr(UI, "lvprint", lambda lvl, *a: lines.append(
        " ".join(str(x) for x in a)))
    tiles = str(tmp_path) + os.sep
    grid_tile(FNAMES.build_dir(LAT, LON, tiles), hub=500)
    TCHECK.check_tile(FNAMES.build_dir(LAT, LON, tiles), LAT, LON)

    class Tile:
        custom_build_dir = tiles
    lines.clear()
    TILE._batch_summary(0, 2, [], Tile(), [(LAT, LON), (LAT, LON + 1)])
    text = "\n".join(lines)
    assert "Tile check warnings: 1 tile(s)" in text
    assert "CHECK: +55+012:" in text and "one point" in text


def test_setting_is_an_app_setting_on_by_default():
    assert CFGV.cfg_app_vars["tile_check"]["default"] is True
    assert CFGV.cfg_app_vars["tile_check"]["module"] == "UI"
    assert "tile_check" in CFGV.gui_app_vars_short
    assert UI.tile_check is True
