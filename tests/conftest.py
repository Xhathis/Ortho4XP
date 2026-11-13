"""Test setup: import Ortho4XP's modules from src/, isolated from user data.

O4_File_Names builds every data path (Tiles, OSM_data, Masks, ...) from the
current directory when it is imported, and O4_Config_Utils reads
Ortho4XP.cfg from there, creating one if it is missing. So the tests switch
to an empty temporary directory before any test module (and with it any
Ortho4XP module) is imported: nothing is read from or written to the
user's folders, config or log.
"""
import os
import shutil
import sys
import tempfile

import pytest

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
_state = {}


def pytest_collection(session):
    # Runs after pytest has resolved its paths, before test modules are
    # imported: switching earlier would hide testpaths from pytest.
    _state["cwd"] = os.getcwd()
    _state["sandbox"] = tempfile.mkdtemp(prefix="o4xp_tests_")
    os.chdir(_state["sandbox"])
    sys.path.insert(0, SRC)
    import O4_File_Names as FNAMES
    import O4_UI_Utils as UI
    assert FNAMES.Tile_dir.startswith(_state["sandbox"]), FNAMES.Tile_dir
    UI.log = False  # lvprint must not append to an Ortho4XP.log anywhere
    UI.verbosity = 0


def pytest_unconfigure(config):
    if "sandbox" in _state:
        os.chdir(_state["cwd"])
        shutil.rmtree(_state["sandbox"], ignore_errors=True)


@pytest.fixture(autouse=True)
def no_geofabrik(monkeypatch):
    """Step 1 and batches take OSM data from Overpass (faked by the tests),
    never from a real Geofabrik download (#101). Not at collection time:
    importing O4_Config_Utils sets every setting to its default again.
    The Geofabrik tests switch it back on with monkeypatch."""
    import O4_Geofabrik as GEOFABRIK
    monkeypatch.setattr(GEOFABRIK, "osm_source", "overpass")
    monkeypatch.setattr(GEOFABRIK, "batch_prepared", False)


@pytest.fixture
def lines(monkeypatch):
    """lvprint lines of a batch run, with Overpass and the clock faked.

    Shared by the batch tests (#44, #79, #81, #82). Defined here, not in
    a test module, so pytest finds it without an import; the O4 modules
    are imported inside, after pytest_collection switched the cwd.
    """
    import O4_OSM_Utils as OSM
    import O4_Tile_Utils as TILE
    import O4_UI_Utils as UI

    monkeypatch.setattr(UI, "log", False)
    out = []
    monkeypatch.setattr(
        UI, "lvprint", lambda level, *a: out.append(" ".join(map(str, a))))
    monkeypatch.setattr(UI, "vprint", lambda *a: None)
    monkeypatch.setattr(UI, "exit_message_and_bottom_line", lambda *a: None)
    monkeypatch.setattr(TILE, "overpass_retry_wait", 0)
    # The batch pauses on the first Overpass failure (#83): no 5 min wait
    # for the probe on the real clock (tests of the probe set it).
    monkeypatch.setattr(TILE, "overpass_probe_interval", 0)
    # The batch tests were written for a pause after 3 tiles in a row (#81);
    # test_gate_pauses_on_first_failure checks the default (1, #83).
    monkeypatch.setattr(TILE, "overpass_pause_after", 3)
    monkeypatch.setattr(OSM, "overpass_gave_up", False)
    # Never ask the real Overpass from a test (#46).
    monkeypatch.setattr(OSM, "overpass_answers", lambda bbox=None: True)
    # The probe runs at once, not in a thread (#81).
    monkeypatch.setattr(TILE, "_run_in_background", lambda fn: [bool(fn())])
    UI.is_working = False
    UI.stop_requested = False
    UI.red_flag = False
    yield out
    UI.stop_requested = False
    UI.red_flag = False
