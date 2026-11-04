"""Small pure helpers added by the fixes (#23, #28, #32)."""
import itertools

import pytest

import O4_Mesh_Utils as MESH
import O4_OSM_Utils as OSM
import O4_Tile_Utils as TILE


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


# --- #23: Overpass server choice -----------------------------------------------
@pytest.fixture
def servers(monkeypatch):
    monkeypatch.setattr(OSM, "max_osm_tentatives", 8)
    monkeypatch.setattr(OSM, "overpass_server_choice", "DE")
    return ["DE", "FR", "KU"]


def test_fixed_server_first_half(servers):
    assert [OSM._pick_overpass_server(t, servers) for t in range(1, 5)] == ["DE"] * 4


def test_fixed_server_falls_back_in_second_half(servers):
    picks = [OSM._pick_overpass_server(t, servers) for t in range(5, 9)]
    # odd tentatives go to the other servers, even ones stay on DE
    assert picks[1] == picks[3] == "DE"
    assert picks[0] != "DE" and picks[2] != "DE"
    assert {picks[0], picks[2]} == {"FR", "KU"}


def test_unknown_choice_uses_first_server(servers, monkeypatch):
    monkeypatch.setattr(OSM, "overpass_server_choice", "XX")
    assert OSM._pick_overpass_server(1, servers) == "DE"


def test_random_choice_avoids_last_server(servers, monkeypatch):
    monkeypatch.setattr(OSM, "overpass_server_choice", "random")
    monkeypatch.setattr(OSM.get_overpass_data, "last_key", "FR", raising=False)
    picks = {OSM._pick_overpass_server(1, servers) for _ in range(50)}
    assert "FR" not in picks and picks <= {"DE", "KU"}
    assert OSM._pick_overpass_server(1, ["DE"]) == "DE"
