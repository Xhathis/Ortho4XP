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
