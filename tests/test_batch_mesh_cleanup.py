"""cleaning_level 3 in batches: meshes kept until every step 2.5 is done (#42).

Tile folders are made under pytest's tmp_path through a custom build dir
ending in a slash (one folder per tile, as in the user's Tiles folder).
"""
import os

import pytest

import O4_File_Names as FNAMES
import O4_Tile_Utils as TILE
import O4_UI_Utils as UI


class FakeTile:
    def __init__(self, build_root):
        self.custom_build_dir = str(build_root) + os.sep
        self.lat = self.lon = 0


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(UI, "log", False)
    monkeypatch.setattr(UI, "cleaning_level", 3)
    lines = []
    monkeypatch.setattr(
        UI, "lvprint", lambda level, *a: lines.append(" ".join(map(str, a))))
    UI.is_working = False
    UI.stop_requested = False
    return FakeTile(tmp_path), lines


def build_dir(tile, lat, lon):
    return FNAMES.build_dir(lat, lon, tile.custom_build_dir)


def mesh(tile, lat, lon):
    return FNAMES.mesh_file(build_dir(tile, lat, lon), lat, lon)


def apt(tile, lat, lon):
    return os.path.join(
        build_dir(tile, lat, lon), "Data" + FNAMES.short_latlon(lat, lon) + ".apt")


def make_mesh(tile, lat, lon):
    os.makedirs(build_dir(tile, lat, lon), exist_ok=True)
    for p in (mesh(tile, lat, lon), apt(tile, lat, lon)):
        open(p, "w").close()


GRID = [(lat, lon) for lat in (10, 11, 12) for lon in (20, 21, 22)]


# --- _remove_meshes_after_batch ---------------------------------------------
def test_removes_mesh_and_apt_of_built_tiles(env):
    tile, _ = env
    for t in GRID:
        make_mesh(tile, *t)
    TILE._remove_meshes_after_batch(tile, GRID[:4], [], True)
    for t in GRID[:4]:
        assert not os.path.exists(mesh(tile, *t))
        assert not os.path.exists(apt(tile, *t))
    for t in GRID[4:]:  # not built by this batch
        assert os.path.exists(mesh(tile, *t))


def test_keeps_meshes_next_to_a_failed_tile(env):
    tile, lines = env
    for t in GRID:
        make_mesh(tile, *t)
    built = [t for t in GRID if t != (12, 22)]
    TILE._remove_meshes_after_batch(
        tile, built, [("+12+022", TILE.BATCH_STEPS[2])], True)
    kept = {(11, 21), (11, 22), (12, 21)}
    for t in built:
        assert os.path.exists(mesh(tile, *t)) == (t in kept), t
    assert any("Mesh kept" in l and "+11+021" in l for l in lines)


def test_sea_neighbour_does_not_keep_meshes(env):
    tile, lines = env
    make_mesh(tile, 11, 21)
    TILE._remove_meshes_after_batch(
        tile, [(11, 21)], [("+12+022", TILE.SEA_SKIPPED)], True)
    assert not os.path.exists(mesh(tile, 11, 21))
    assert lines == []


@pytest.mark.parametrize("level, do_dsf", [(2, True), (1, True), (3, False)])
def test_nothing_removed_below_level_3_or_without_step_3(env, monkeypatch,
                                                         level, do_dsf):
    tile, _ = env
    monkeypatch.setattr(UI, "cleaning_level", level)
    make_mesh(tile, 11, 21)
    TILE._remove_meshes_after_batch(tile, [(11, 21)], [], do_dsf)
    assert os.path.exists(mesh(tile, 11, 21))


def test_antimeridian_neighbour(env):
    tile, _ = env
    make_mesh(tile, 0, 179)
    TILE._remove_meshes_after_batch(
        tile, [(0, 179)], [("+00-180", TILE.BATCH_STEPS[0])], True)
    assert os.path.exists(mesh(tile, 0, 179))


# --- meshes kept by an earlier batch -------------------------------------------
def dsf(tile, lat, lon):
    return FNAMES.dsf_file(build_dir(tile, lat, lon), lat, lon)


def make_dsf(tile, lat, lon, age=0):
    """A built tile: DSF written after the mesh (age > 0: before it)."""
    os.makedirs(os.path.dirname(dsf(tile, lat, lon)), exist_ok=True)
    open(dsf(tile, lat, lon), "w").close()
    m = os.path.getmtime(mesh(tile, lat, lon)) if os.path.exists(
        mesh(tile, lat, lon)) else 1_000_000
    os.utime(dsf(tile, lat, lon), (m + 10 - age, m + 10 - age))


CENTER = (11, 21)
RING = [t for t in GRID if t != CENTER]


def earlier_batch_kept_ring(tile):
    """The ring was built by an earlier batch, which kept its meshes
    because the center failed in step 1 (folder, no mesh, no DSF)."""
    for t in RING:
        make_mesh(tile, *t)
        make_dsf(tile, *t)
    os.makedirs(build_dir(tile, *CENTER), exist_ok=True)


def test_rerun_removes_meshes_kept_by_earlier_batch(env):
    tile, lines = env
    earlier_batch_kept_ring(tile)
    make_mesh(tile, *CENTER)  # the rerun built the center
    TILE._remove_meshes_after_batch(tile, [CENTER], [], True)
    for t in GRID:
        assert not os.path.exists(mesh(tile, *t)), t
        assert not os.path.exists(apt(tile, *t)), t
    for t in RING:
        assert os.path.exists(dsf(tile, *t))  # only mesh and .apt go
    assert any("kept by an earlier batch" in l and "+10+020" in l
               for l in lines)


def test_kept_mesh_stays_next_to_another_unbuilt_tile(env):
    tile, _ = env
    earlier_batch_kept_ring(tile)
    os.makedirs(build_dir(tile, 12, 23), exist_ok=True)  # also failed
    make_mesh(tile, *CENTER)
    TILE._remove_meshes_after_batch(tile, [CENTER], [], True)
    for t in RING:
        assert os.path.exists(mesh(tile, *t)) == (t in {(11, 22), (12, 22)}), t


def test_kept_mesh_stays_next_to_a_tile_awaiting_masks(env):
    # (12, 23) ran steps 1-2 again after its DSF: its step 2.5 is ahead.
    tile, _ = env
    earlier_batch_kept_ring(tile)
    make_mesh(tile, 12, 23)
    make_dsf(tile, 12, 23, age=20)
    make_mesh(tile, *CENTER)
    TILE._remove_meshes_after_batch(tile, [CENTER], [], True)
    assert os.path.exists(mesh(tile, 11, 22))
    assert os.path.exists(mesh(tile, 12, 22))
    assert not os.path.exists(mesh(tile, 10, 20))


def test_kept_mesh_of_unbuilt_or_rebuilt_tile_stays(env):
    tile, _ = env
    earlier_batch_kept_ring(tile)
    os.remove(dsf(tile, 10, 20))          # never got its DSF
    make_dsf(tile, 10, 22, age=20)        # mesh newer than its DSF
    make_mesh(tile, *CENTER)
    TILE._remove_meshes_after_batch(tile, [CENTER], [], True)
    assert os.path.exists(mesh(tile, 10, 20))
    assert os.path.exists(mesh(tile, 10, 22))
    assert not os.path.exists(mesh(tile, 12, 21))


def test_kept_mesh_stays_next_to_a_tile_failed_now(env):
    tile, _ = env
    earlier_batch_kept_ring(tile)
    make_mesh(tile, *CENTER)
    TILE._remove_meshes_after_batch(
        tile, [CENTER], [("+12+023", TILE.BATCH_STEPS[0])], True)
    assert os.path.exists(mesh(tile, 12, 22))
    assert os.path.exists(mesh(tile, 11, 22))
    assert not os.path.exists(mesh(tile, 10, 21))


def test_meshes_farther_away_are_not_touched(env):
    tile, _ = env
    make_mesh(tile, 15, 25)
    make_dsf(tile, 15, 25)
    make_mesh(tile, *CENTER)
    TILE._remove_meshes_after_batch(tile, [CENTER], [], True)
    assert os.path.exists(mesh(tile, 15, 25))


def test_kept_meshes_stay_below_level_3(env, monkeypatch):
    tile, _ = env
    monkeypatch.setattr(UI, "cleaning_level", 2)
    earlier_batch_kept_ring(tile)
    TILE._remove_meshes_after_batch(tile, [CENTER], [], True)
    assert all(os.path.exists(mesh(tile, *t)) for t in RING)


# --- sequential batch -----------------------------------------------------------
def fake_steps(tile, seen, monkeypatch, fail=()):
    """Phase 1 writes the mesh; phase 2 records the neighbour meshes its
    step 2.5 would see, then does what build_tile does at level 3."""

    def one(t, lat, lon, do_osm, do_mesh, do_mask, do_dsf, do_ovl, override):
        if do_mesh:
            make_mesh(tile, lat, lon)
        if do_mask:
            if (lat, lon) in fail:
                return TILE.BATCH_STEPS[2]
            seen[(lat, lon)] = {
                n for n in GRID if n != (lat, lon)
                and abs(n[0] - lat) <= 1 and abs(n[1] - lon) <= 1
                and os.path.exists(mesh(tile, *n))
            }
        if do_dsf and UI.cleaning_level > 2 and not TILE.keep_mesh_after_step3:
            TILE._remove_mesh_files(build_dir(tile, lat, lon), lat, lon)
        return None

    monkeypatch.setattr(TILE, "_build_one_tile", one)


def neighbours_in_grid(lat, lon):
    return {n for n in GRID if n != (lat, lon)
            and abs(n[0] - lat) <= 1 and abs(n[1] - lon) <= 1}


def test_sequential_batch_masks_see_every_neighbour(env, monkeypatch):
    tile, _ = env
    monkeypatch.setattr(TILE, "batch_parallel_tiles", 1)
    seen = {}
    fake_steps(tile, seen, monkeypatch)
    assert TILE.build_tile_list(tile, GRID, 1, 1, 1, 1, 0, 0) == 1
    for t in GRID:
        assert seen[t] == neighbours_in_grid(*t), t
        assert not os.path.exists(mesh(tile, *t))  # removed at the end
    assert TILE.keep_mesh_after_step3 is False


def test_sequential_batch_with_a_failure(env, monkeypatch):
    tile, _ = env
    monkeypatch.setattr(TILE, "batch_parallel_tiles", 1)
    seen = {}
    fake_steps(tile, seen, monkeypatch, fail={(10, 20)})
    assert TILE.build_tile_list(tile, GRID, 1, 1, 1, 1, 0, 0) == 0
    for t in GRID:
        assert os.path.exists(mesh(tile, *t)) == (
            t == (10, 20) or t in neighbours_in_grid(10, 20)), t


def test_single_build_still_removes_at_once():
    # Outside a batch build_tile deletes the mesh right after step 3.
    assert TILE.keep_mesh_after_step3 is False


def test_stop_keeps_meshes(env, monkeypatch):
    tile, _ = env
    monkeypatch.setattr(TILE, "batch_parallel_tiles", 1)
    seen = {}
    fake_steps(tile, seen, monkeypatch)
    real = TILE._build_one_tile

    def stop_at_fifth(t, lat, lon, *flags):
        if flags[2] and len(seen) == 4:
            UI.stop_requested = True
            return TILE.BATCH_STEPS[2]
        return real(t, lat, lon, *flags)

    monkeypatch.setattr(TILE, "_build_one_tile", stop_at_fifth)
    monkeypatch.setattr(UI, "exit_message_and_bottom_line", lambda *a: None)
    assert TILE.build_tile_list(tile, GRID, 1, 1, 1, 1, 0, 0) == 0
    assert all(os.path.exists(mesh(tile, *t)) for t in GRID)
    assert TILE.keep_mesh_after_step3 is False
    UI.stop_requested = False


# --- parallel batch -------------------------------------------------------------
def test_worker_keeps_its_mesh(monkeypatch):
    flag = []
    monkeypatch.setattr(
        TILE, "_build_one_tile",
        lambda t, lat, lon, *f: flag.append(TILE.keep_mesh_after_step3))
    monkeypatch.setattr(TILE, "keep_mesh_after_step3", False)
    assert TILE.batch_worker(type("T", (), {"lat": 1, "lon": 2})(),
                             "001100") == 0
    assert flag == [True]


def test_parallel_phase_reports_built_tiles(env, monkeypatch, tmp_path):
    tile, _ = env
    monkeypatch.setattr(FNAMES, "Tmp_dir", str(tmp_path))
    monkeypatch.setattr(TILE.time, "sleep", lambda s: None)
    codes = {"1": 0, "2": 12, "3": 0}

    class FakeProc:
        def __init__(self, args, **kw):
            self.code = codes[args[args.index("--batch-worker") + 1]]

        def poll(self):
            return self.code

    monkeypatch.setattr(TILE.subprocess, "Popen", FakeProc)
    built = []
    TILE._run_batch_phase(tile, [(1, 0), (2, 0), (3, 0)], (0,) * 6, 3,
                          last_phase=True, context_file="", built=built)
    assert sorted(built) == [(1, 0), (3, 0)]
    built.clear()
    TILE._run_batch_phase(tile, [(1, 0)], (0,) * 6, 3,
                          last_phase=False, context_file="", built=built)
    assert built == []  # phase 1 builds nothing yet
