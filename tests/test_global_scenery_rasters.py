"""#50: reading the Global Scenery rasters: missing DSF, broken DSF, no folder."""
import os
import struct

import numpy
import pytest

import O4_DSF_Utils as DSF
import O4_File_Names as FNAMES
import O4_Overlay_Utils as OVL
import O4_UI_Utils as UI


def _atom(tag, payload):
    return tag + struct.pack("<I", 8 + len(payload)) + payload


def _dsf_bytes(elev, bathy):
    nmed = _atom(b"NMED", b"sim/elevation\0sim/bathymetry\0")
    nfed = _atom(b"NFED", nmed)
    smed = _atom(
        b"SMED",
        _atom(b"IMED", b"\0" * 20)
        + _atom(b"DMED", elev.astype(numpy.int16).tobytes())
        + _atom(b"IMED", b"\0" * 20)
        + _atom(b"DMED", bathy.astype(numpy.int16).tobytes()),
    )
    return b"XPLNEDSF" + struct.pack("<I", 1) + nfed + smed + b"\0" * 16


@pytest.fixture
def gs(tmp_path, monkeypatch):
    src = tmp_path / "Global Scenery"
    (src / "Earth nav data" / "+50+010").mkdir(parents=True)
    tmp = tmp_path / "tmp"
    tmp.mkdir()
    monkeypatch.setattr(OVL, "custom_overlay_src", str(src))
    monkeypatch.setattr(OVL, "custom_overlay_src_alternate", "")
    monkeypatch.setattr(FNAMES, "Tmp_dir", str(tmp))
    logged = []
    monkeypatch.setattr(UI, "lvprint", lambda level, *a: logged.append(
        " ".join(str(x) for x in a)))
    dsf = src / "Earth nav data" / "+50+010" / "+55+012.dsf"
    return dsf, tmp, logged


def test_rasters_are_read(gs):
    dsf, tmp, logged = gs
    elev = numpy.arange(100, 200)
    bathy = numpy.full(100, 150)
    dsf.write_bytes(_dsf_bytes(elev, bathy))
    (bDEMN, bDEMS) = DSF.extract_elevation_and_bathymetry_data(55, 12)
    assert bDEMN == b"sim/elevation\0sim/bathymetry\0"
    assert bDEMS.count(b"DMED") == 2
    assert logged == [] and os.listdir(tmp) == []


def test_tile_without_global_dsf_builds_without_rasters_and_warns(gs):
    dsf, tmp, logged = gs
    assert DSF.extract_elevation_and_bathymetry_data(55, 12) == (b"", b"")
    assert len(logged) == 1 and "WARNING" in logged[0] and "+55+012" in logged[0]


def test_corrupt_global_dsf_fails(gs):
    dsf, tmp, logged = gs
    dsf.write_bytes(b"this is no DSF at all")
    assert DSF.extract_elevation_and_bathymetry_data(55, 12) is None
    assert "ERROR" in logged[0]
    assert os.listdir(tmp) == []


def test_unreadable_global_dsf_fails(gs, monkeypatch):
    dsf, tmp, logged = gs
    dsf.write_bytes(_dsf_bytes(numpy.zeros(100), numpy.zeros(100)))

    def no_space(*a, **k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(DSF.shutil, "copy", no_space)
    assert DSF.extract_elevation_and_bathymetry_data(55, 12) is None
    assert "No space left" in logged[0]


def test_no_global_scenery_folder_fails(gs, monkeypatch):
    dsf, tmp, logged = gs
    monkeypatch.setattr(OVL, "custom_overlay_src", "")
    assert DSF.extract_elevation_and_bathymetry_data(55, 12) is None
    assert "custom_overlay_src" in logged[0]
