"""The override pack carries its airports' 3D from Global Airports (#124)."""
import hashlib
import json
import os
import struct

import pytest

import O4_File_Names as FNAMES
import O4_UI_Utils as UI
import O4_XP_Airports as XPAPT

from test_xp_override import APT_DAT, make_tile


def flt(i):
    """FILTER i (comment 8: uint16 1, int32 index)."""
    return struct.pack("<BBHi", 32, 6, 1, i)


POOL3 = bytes([1, 3, 0])            # pool select 3 (state)
DEF2 = bytes([3, 2])                # definition 2 (state)
OBJ = bytes([7, 5, 0])              # object 5
MODE = struct.pack("<BBHi", 32, 6, 2, 1)  # the other Global Airports comment
POLY = bytes([12, 1, 0, 2, 4, 0, 5, 0])   # polygon, 2 indices
NESTED_RANGE = bytes([15, 0x2d, 0, 3, 0, 0, 0x29, 0, 0x31, 0, 0x37, 0])
CHAIN = bytes([9, 2, 1, 0, 2, 0])   # network chain, 2 indices


def make_dsf(path, props, cmds, extra_atoms=((b"NFED", b"defs"),)):
    """A DSF file as X-Plane writes them: header, atoms, MD5."""
    def atom(aid, payload):
        return aid + struct.pack("<I", 8 + len(payload)) + payload
    prop = b"".join(k.encode() + b"\x00" + v.encode() + b"\x00"
                    for (k, v) in props)
    body = b"XPLNEDSF" + struct.pack("<I", 1)
    body += atom(b"DAEH", atom(b"PORP", prop))
    for (aid, payload) in extra_atoms:
        body += atom(aid, payload)
    body += atom(b"SDMC", cmds)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(body + hashlib.md5(body).digest())


BASE_PROPS = [("sim/west", "-52"), ("sim/overlay", "1")]


def ga_props(*groups):
    """aptid groups: (icao, [exclusion values])."""
    out = list(BASE_PROPS)
    for (icao, excl) in groups:
        out.append(("sim/filter/aptid", icao))
        out += [("sim/exclude_obj", e) for e in excl]
    out.append(("sim/require_object", "1/3"))
    return out


@pytest.mark.parametrize("cmd", [
    POOL3, DEF2, OBJ, MODE, POLY, NESTED_RANGE, CHAIN, flt(7),
    bytes([2, 1, 2, 3, 4]), bytes([8, 0, 0, 9, 0]), bytes([13, 1, 0, 0, 0, 9, 0]),
    bytes([14, 1, 0, 2, 2, 0, 0, 1, 0, 1, 5, 0]), bytes([11, 1, 1, 2, 3, 4]),
    bytes([23, 1, 4, 0]), bytes([24, 1, 0, 0, 4, 0]), bytes([16]),
    bytes([17, 1]), bytes([18, 1]) + struct.pack("<ff", 0, 1),
    bytes([33, 2, 0, 9, 9]), bytes([34, 1, 0, 0, 0, 9]),
])
def test_command_lengths(cmd):
    assert XPAPT._cmd_end(cmd + b"\xff", 0) == len(cmd)


def test_unknown_command_raises():
    with pytest.raises(ValueError):
        XPAPT._cmd_end(bytes([99, 0]), 0)


def test_filter_properties_keeps_wanted_groups_with_their_exclusions():
    props = [("sim/exclude_for", "lonely")] + ga_props(
        ("XAAA", ["a1"]), ("BGGH", ["b1", "b2"]), ("XCCC", []),
        ("CROS", ["c1"]))
    (kept, renumber) = XPAPT.filter_properties(props, ["BGGH", "CROS"])
    assert renumber == {1: 0, 3: 1}
    assert kept == BASE_PROPS + [
        ("sim/filter/aptid", "BGGH"), ("sim/exclude_obj", "b1"),
        ("sim/exclude_obj", "b2"), ("sim/filter/aptid", "CROS"),
        ("sim/exclude_obj", "c1"), ("sim/require_object", "1/3")]


def test_filter_commands_keeps_blocks_and_all_state():
    cmds = (POOL3 + OBJ             # unfiltered drawing: left out
            + flt(0) + DEF2 + OBJ + MODE + POLY   # other airport
            + flt(1) + OBJ + NESTED_RANGE          # wanted, becomes 0
            + flt(2) + POOL3 + CHAIN               # other airport
            + flt(1) + OBJ)                        # wanted again
    out = XPAPT.filter_commands(cmds, {1: 0})
    assert out == (POOL3 + DEF2 + MODE + flt(0) + OBJ + NESTED_RANGE
                   + POOL3 + flt(0) + OBJ)


def test_filter_commands_all_kept_is_identity():
    cmds = flt(0) + POOL3 + OBJ + MODE + flt(1) + POLY + flt(0) + CHAIN
    assert XPAPT.filter_commands(cmds, {0: 0, 1: 1}) == cmds


def test_filter_commands_cut_off_raises():
    with pytest.raises(ValueError):
        XPAPT.filter_commands(flt(0) + POLY[:-1], {0: 0})


def test_filter_dsf_writes_a_valid_dsf(tmp_path):
    src = str(tmp_path / "ga" / "+64-052.dsf")
    make_dsf(src, ga_props(("XAAA", ["a"]), ("BGGH", ["b"])),
             flt(0) + OBJ + flt(1) + POOL3 + POLY)
    dst = str(tmp_path / "pack" / "+64-052.dsf")
    os.makedirs(os.path.dirname(dst))
    assert XPAPT.filter_dsf(src, dst, ["BGGH"])
    (_head, atoms, order, props) = XPAPT.read_dsf(dst)  # checksum checked
    assert order == ["HEAD", "DEFN", "CMDS"]
    assert atoms["DEFN"] == b"defs"
    assert atoms["CMDS"] == flt(0) + POOL3 + POLY
    assert ("sim/filter/aptid", "XAAA") not in props
    assert ("sim/exclude_obj", "b") in props
    assert XPAPT.dsf_airport_ids(dst) == ["BGGH"]
    assert not [f for f in os.listdir(tmp_path / "pack") if f != "+64-052.dsf"]
    # None of the airports: nothing written.
    other = str(tmp_path / "pack" / "other.dsf")
    assert not XPAPT.filter_dsf(src, other, ["CROS"])
    assert not os.path.exists(other)


def test_read_dsf_rejects_broken_files(tmp_path):
    path = str(tmp_path / "x.dsf")
    make_dsf(path, BASE_PROPS, OBJ)
    data = open(path, "rb").read()
    for bad in (data[:-1] + bytes([data[-1] ^ 1]),   # checksum
                b"7z\xbc\xaf\x27\x1c" + data,         # compressed
                b"NOTADSF" + data):
        with open(path, "wb") as f:
            f.write(bad)
        with pytest.raises(ValueError):
            XPAPT.read_dsf(path)


@pytest.fixture
def xp(tmp_path, monkeypatch):
    monkeypatch.setattr(FNAMES, "Tmp_dir", str(tmp_path / "tmp"))
    monkeypatch.setattr(UI, "log", False)
    gs = tmp_path / "X-Plane" / "Global Scenery"
    src = gs / "X-Plane 12 Global Scenery"
    src.mkdir(parents=True)
    apt = gs / "Global Airports" / "Earth nav data" / "apt.dat"
    apt.parent.mkdir(parents=True)
    apt.write_bytes(APT_DAT.encode("utf-8"))
    tiles = tmp_path / "Tiles"
    tiles.mkdir()
    return (str(src), str(apt), str(tiles), str(tmp_path / "pack"))


def ga_dsf(apt, lat, lon):
    return XPAPT.ga_dsf_path(apt, lat, lon)


def test_update_puts_the_airports_3d_in_the_pack(xp):
    (src, apt, tiles, pack) = xp
    # BGGH's 3D in its tile; CROS's in a neighbour of its boundary tiles;
    # a tile with only another airport gets no pack DSF.
    make_dsf(ga_dsf(apt, 64, -52), ga_props(("BGGH", ["e"])),
             flt(0) + OBJ)
    make_dsf(ga_dsf(apt, 11, 11), ga_props(("XAAA", []), ("CROS", [])),
             flt(0) + OBJ + flt(1) + POLY)
    make_dsf(ga_dsf(apt, 64, -51), ga_props(("XAAA", [])), flt(0) + OBJ)
    make_tile(tiles, 64, -52, ["BGGH"])
    make_tile(tiles, 10, 10, ["CROS"])
    make_tile(tiles, 10, 11, ["CROS"])
    assert XPAPT.update_override_pack((src,), tiles, pack) == 2
    bggh = FNAMES.dsf_file(pack, 64, -52)
    cros = FNAMES.dsf_file(pack, 11, 11)
    assert XPAPT.dsf_airport_ids(bggh) == ["BGGH"]
    assert XPAPT.read_dsf(cros)[1]["CMDS"] == flt(0) + POLY
    assert not os.path.exists(FNAMES.dsf_file(pack, 64, -51))
    stamp = json.load(open(os.path.join(pack, XPAPT.PACK_STAMP)))
    assert stamp["version"] == XPAPT.PACK_VERSION
    # BGGH leaves the pack: its DSF goes, CROS's stays.
    XPAPT.write_marker(FNAMES.build_dir(64, -52, tiles + os.sep), [])
    assert XPAPT.update_override_pack((src,), tiles, pack) == 1
    assert not os.path.exists(bggh) and os.path.exists(cros)


def test_pack_of_123_is_redone(xp):
    """A pack written before #124 (stamp without version) gets its 3D."""
    (src, apt, tiles, pack) = xp
    make_dsf(ga_dsf(apt, 64, -52), ga_props(("BGGH", [])), flt(0) + OBJ)
    make_tile(tiles, 64, -52, ["BGGH"])
    assert XPAPT.update_override_pack((src,), tiles, pack) == 1
    stamp_file = os.path.join(pack, XPAPT.PACK_STAMP)
    stamp = json.load(open(stamp_file))
    del stamp["version"]
    with open(stamp_file, "w") as f:
        json.dump(stamp, f)
    os.remove(FNAMES.dsf_file(pack, 64, -52))
    assert XPAPT.update_override_pack((src,), tiles, pack) == 1
    assert os.path.exists(FNAMES.dsf_file(pack, 64, -52))


def test_broken_source_dsf_warns_and_retries_next_time(xp, monkeypatch):
    (src, apt, tiles, pack) = xp
    path = ga_dsf(apt, 64, -52)
    make_dsf(path, ga_props(("BGGH", [])), flt(0) + bytes([99]))
    make_tile(tiles, 64, -52, ["BGGH"])
    lines = []
    monkeypatch.setattr(UI, "lvprint", lambda lvl, *a: lines.append(" ".join(a)))
    assert XPAPT.update_override_pack((src,), tiles, pack) == 1
    assert any("WARNING" in line and "+64-052" in line for line in lines)
    assert os.path.exists(os.path.join(pack, XPAPT.PACK_APT_DAT))
    assert not os.path.exists(os.path.join(pack, XPAPT.PACK_STAMP))
    assert not os.path.exists(FNAMES.dsf_file(pack, 64, -52))
    # Fixed source: the next update writes it.
    make_dsf(path, ga_props(("BGGH", [])), flt(0) + OBJ)
    assert XPAPT.update_override_pack((src,), tiles, pack) == 1
    assert os.path.exists(FNAMES.dsf_file(pack, 64, -52))
    assert os.path.exists(os.path.join(pack, XPAPT.PACK_STAMP))


def test_failed_rewrite_keeps_the_last_pack_dsf(xp, monkeypatch):
    # #132: X-Plane holds the pack DSF open, so it cannot be replaced: it
    # used to be deleted by the sweep of stale DSFs (BGGH without 3D).
    (src, apt, tiles, pack) = xp
    make_dsf(ga_dsf(apt, 64, -52), ga_props(("BGGH", [])), flt(0) + OBJ)
    make_tile(tiles, 64, -52, ["BGGH"])
    assert XPAPT.update_override_pack((src,), tiles, pack) == 1
    bggh = FNAMES.dsf_file(pack, 64, -52)
    before = open(bggh, "rb").read()
    os.remove(os.path.join(pack, XPAPT.PACK_STAMP))  # make it redo the pack
    real = os.replace

    def replace(a, b):
        if os.path.normcase(b) == os.path.normcase(bggh):
            raise PermissionError(13, "in use")
        return real(a, b)

    monkeypatch.setattr(XPAPT.os, "replace", replace)
    lines = []
    monkeypatch.setattr(UI, "lvprint", lambda lvl, *a: lines.append(" ".join(a)))
    assert XPAPT.update_override_pack((src,), tiles, pack) == 1
    assert open(bggh, "rb").read() == before
    assert any("WARNING" in line and "in use" in line for line in lines)


def test_stale_dsf_that_cannot_be_removed_warns(xp, monkeypatch):
    (src, apt, tiles, pack) = xp
    make_dsf(ga_dsf(apt, 64, -52), ga_props(("BGGH", [])), flt(0) + OBJ)
    make_tile(tiles, 64, -52, ["BGGH"])
    stale = FNAMES.dsf_file(pack, 10, 10)
    make_dsf(stale, ga_props(("CROS", [])), flt(0) + OBJ)

    def remove(path):
        raise PermissionError(13, "in use")

    monkeypatch.setattr(XPAPT.os, "remove", remove)
    lines = []
    monkeypatch.setattr(UI, "lvprint", lambda lvl, *a: lines.append(" ".join(a)))
    # Used to raise out of update_override_pack before apt.dat was written.
    assert XPAPT.update_override_pack((src,), tiles, pack) == 1
    assert os.path.exists(os.path.join(pack, XPAPT.PACK_APT_DAT))
    assert any("not removed" in line for line in lines)
    assert not os.path.exists(os.path.join(pack, XPAPT.PACK_STAMP))
