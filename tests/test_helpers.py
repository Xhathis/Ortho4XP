"""Small pure helpers added by the fixes (#23, #28, #32)."""
import itertools

import pytest

import O4_Mesh_Utils as MESH
import O4_OSM_Utils as OSM
import O4_Tile_Utils as TILE
import O4_UI_Utils as UI


# --- #28: batch phases -------------------------------------------------------
def test_batch_phases_all_steps():
    flags = (True, True, True, True, True, False)
    assert TILE._batch_phases(flags) == [
        ("steps 1-2", (True, True, False, False, False, False)),
        ("steps 2.5-3", (False, False, True, True, True, False)),
    ]


def test_batch_phases_only_step3_keeps_override():
    assert TILE._batch_phases((False, False, False, True, False, True)) == [
        ("steps 2.5-3", (False, False, False, True, False, True))]


@pytest.mark.parametrize("flags", list(itertools.product([False, True], repeat=6)))
def test_batch_phases_cover_each_step_once(flags):
    phases = TILE._batch_phases(flags)
    for i in range(5):  # every ticked step runs in exactly one phase
        assert sum(steps[i] for (_, steps) in phases) == flags[i]
    assert all(steps[5] == flags[5] for (_, steps) in phases)
    names = [name for (name, _) in phases]
    assert names in ([], ["steps 1-2"], ["steps 2.5-3"], ["steps 1-2", "steps 2.5-3"])


# --- #32: Triangle4XP exit codes ----------------------------------------------
def test_tool_failure_names_stack_overflow():
    # Windows reports 0xC00000FD; Python shows it unsigned or negative.
    assert "stack overflow" in MESH._tool_failure(3221225725)
    assert "stack overflow" in MESH._tool_failure(-1073741571)


def test_tool_failure_other_codes():
    assert "crashed" in MESH._tool_failure(0xC0000005)  # access violation
    assert "exit code 2" in MESH._tool_failure(2)
    assert "OSM" in MESH._tool_failure(1)


# --- #23, #83: Overpass server order ------------------------------------------
@pytest.fixture
def servers(monkeypatch):
    monkeypatch.setattr(OSM, "overpass_server_choice", "DE")
    monkeypatch.setattr(UI, "vprint", lambda *a: None)
    return ["FR", "DE", "KU"]


def test_configured_server_first(servers):
    assert OSM._server_order(servers) == ["DE", "FR", "KU"]


def test_unknown_choice_keeps_file_order(servers, monkeypatch):
    monkeypatch.setattr(OSM, "overpass_server_choice", "XX")
    assert OSM._server_order(servers) == servers


def test_random_choice(servers, monkeypatch):
    monkeypatch.setattr(OSM, "overpass_server_choice", "random")
    orders = {tuple(OSM._server_order(servers)) for _ in range(60)}
    assert len(orders) > 1 and all(sorted(o) == sorted(servers) for o in orders)
    assert OSM._server_order(servers, shuffle=False) == servers
