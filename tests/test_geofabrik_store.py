"""#129: Geofabrik extracts stored by region id, with a manifest."""
import datetime
import importlib.util
import json
import os

import pytest

from shapely import geometry

import O4_Geofabrik as GEOFABRIK
import O4_OSM_Extract as EXTRACT
import O4_UI_Utils as UI
import O4_File_Names as FNAMES

B = GEOFABRIK.BASE_URL
BOX = geometry.box(0, 0, 1, 1)
REAL_DATA_TIME = GEOFABRIK.data_time


def region(rid, path, updates=None):
    return GEOFABRIK.Region(rid, B + path, BOX, updates=updates)


@pytest.fixture
def gf(tmp_path, monkeypatch):
    """Geofabrik's folder in tmp, logs collected (as in test_geofabrik)."""
    monkeypatch.setattr(GEOFABRIK, "geofabrik_dir", str(tmp_path / "gf"))
    monkeypatch.setattr(FNAMES, "OSM_dir", str(tmp_path / "OSM_data"))
    monkeypatch.setattr(UI, "vprint", lambda *a: None)
    lines = []
    monkeypatch.setattr(UI, "lvprint",
                        lambda level, *a: lines.append(" ".join(map(str, a))))
    monkeypatch.setattr(UI, "stop_requested", False)
    return lines


@pytest.fixture
def fresh(monkeypatch):
    monkeypatch.setattr(GEOFABRIK, "_failed_downloads", {})
    monkeypatch.setattr(GEOFABRIK, "_failed_updates", set())
    monkeypatch.setattr(GEOFABRIK, "_index_refresh_error", None)


def write(path, data=b"pbf"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


# --- names -----------------------------------------------------------------------
def test_names_by_region_id(gf):
    assert EXTRACT.store_name("alsace") == "alsace.osm.pbf"
    assert EXTRACT.store_name("us/georgia") == "us__georgia.osm.pbf"
    store = GEOFABRIK.store_dir()
    assert GEOFABRIK.extract_path("georgia") == os.path.join(
        store, "georgia.osm.pbf")
    assert GEOFABRIK.extract_path("us/georgia") != \
        GEOFABRIK.extract_path("georgia")
    assert store == os.path.join(GEOFABRIK.data_dir(), "extracts")


def test_index_gives_the_update_server(gf, tmp_path):
    index = {"features": [{"type": "Feature", "properties": {
        "id": "alsace", "urls": {
            "pbf": B + "europe/france/alsace/alsace-latest.osm.pbf",
            "updates": B + "europe/france/alsace/updates"}},
        "geometry": {"type": "Polygon",
                     "coordinates": [[[7, 47], [8, 47], [8, 49], [7, 47]]]}}]}
    (r,) = GEOFABRIK.parse_index(json.dumps(index))
    assert r.updates == B + "europe/france/alsace/updates"


# --- the move of the old layout ------------------------------------------------
REGIONS = [
    region("alsace", "europe/france/alsace/alsace-latest.osm.pbf"),
    region("us/georgia", "north-america/us/georgia/georgia-latest.osm.pbf"),
    region("georgia", "europe/georgia/georgia-latest.osm.pbf"),
    region("norway", "europe/norway/norway-latest.osm.pbf"),
]
OLD = {  # where #101-#128 kept them (local_path of the URLs)
    "alsace": "europe/france/alsace-latest.osm.pbf",
    "us/georgia": "north-america/us/georgia-latest.osm.pbf",
    "georgia": "europe/georgia-latest.osm.pbf",
}


def old_layout(with_side_files=True):
    top = GEOFABRIK.data_dir()
    paths = {}
    for (rid, rel) in OLD.items():
        path = os.path.join(top, *rel.split("/"))
        write(path, rid.encode())
        if with_side_files:
            write(path + ".lock", b"")
            write(path + ".checked", b"")
        paths[rid] = path
    gone = os.path.join(top, "europe", "atlantis-latest.osm.pbf")
    write(gone, b"no region")
    write(GEOFABRIK.index_path(), b"{}")
    return (paths, gone)


def test_dry_run_moves_nothing(gf):
    (paths, gone) = old_layout()
    (moves, left) = GEOFABRIK.migrate_store(REGIONS, dry_run=True)
    assert sorted(m[2] for m in moves) == ["alsace", "georgia", "us/georgia"]
    assert left == [gone]
    assert all(os.path.isfile(p) for p in paths.values())
    assert not os.path.exists(GEOFABRIK.store_dir())


def test_move_by_region_id(gf):
    (paths, gone) = old_layout()
    (moves, left) = GEOFABRIK.migrate_store(REGIONS)
    assert len(moves) == 3 and left == [gone]
    for (rid, old) in paths.items():
        new = GEOFABRIK.extract_path(rid)
        with open(new, "rb") as f:
            assert f.read() == rid.encode()  # the right file, not a copy
        assert not os.path.exists(old)
        assert not os.path.exists(old + ".lock")
        assert not os.path.exists(old + ".checked")
    manifest = GEOFABRIK.read_manifest()
    assert manifest["alsace"]["url"] == REGIONS[0].url
    assert manifest["alsace"]["moved_from"] == paths["alsace"]
    assert manifest["alsace"]["checked"].endswith("Z")
    # Old folders emptied by the move are gone; the unknown file stays.
    top = GEOFABRIK.data_dir()
    assert not os.path.exists(os.path.join(top, "north-america"))
    assert not os.path.exists(os.path.join(top, "europe", "france"))
    assert os.path.isfile(gone) and os.path.isfile(GEOFABRIK.index_path())
    assert any("moved 3 extract(s)" in line for line in gf)
    assert any("atlantis-latest.osm.pbf" in line for line in gf)
    # Nothing left to do the next time.
    assert GEOFABRIK.migrate_store(REGIONS) == ([], [gone])


def test_store_copy_wins(gf):
    (paths, _) = old_layout(with_side_files=False)
    write(GEOFABRIK.extract_path("alsace"), b"newer")
    (moves, left) = GEOFABRIK.migrate_store(REGIONS)
    assert "alsace" not in [m[2] for m in moves]
    assert paths["alsace"] in left and os.path.isfile(paths["alsace"])
    with open(GEOFABRIK.extract_path("alsace"), "rb") as f:
        assert f.read() == b"newer"


def test_undo_moves_back(gf):
    (paths, _) = old_layout()
    GEOFABRIK.migrate_store(REGIONS)
    (csv,) = [f for f in os.listdir(GEOFABRIK.store_dir())
              if f.startswith("moved_")]
    n = GEOFABRIK.undo_migration(os.path.join(GEOFABRIK.store_dir(), csv))
    assert n == 3
    for (rid, old) in paths.items():
        with open(old, "rb") as f:
            assert f.read() == rid.encode()
        assert not os.path.exists(GEOFABRIK.extract_path(rid))


def test_undo_drops_the_manifest_records(gf):
    old_layout()
    GEOFABRIK.migrate_store(REGIONS)
    (log,) = [f for f in os.listdir(GEOFABRIK.store_dir())
              if f.startswith("moved_")]
    GEOFABRIK.undo_migration(os.path.join(GEOFABRIK.store_dir(), log))
    assert GEOFABRIK.read_manifest() == {}


def test_undo_with_a_comma_in_the_path(gf, tmp_path, monkeypatch):
    # The CSV used to be split at the last two commas: a comma in the
    # store's path broke it.
    monkeypatch.setattr(GEOFABRIK, "geofabrik_dir", str(tmp_path / "a,b"))
    (paths, _) = old_layout()
    GEOFABRIK.migrate_store(REGIONS)
    (log,) = [f for f in os.listdir(GEOFABRIK.store_dir())
              if f.startswith("moved_")]
    assert GEOFABRIK.undo_migration(
        os.path.join(GEOFABRIK.store_dir(), log)) == 3
    assert all(os.path.isfile(p) for p in paths.values())


def test_undo_reads_the_first_csv_form(gf):
    # moved_20261124_073819.csv (the user's move) was written without the
    # csv module: plain "old,new,region" lines.
    (paths, _) = old_layout()
    GEOFABRIK.migrate_store(REGIONS)
    log = os.path.join(GEOFABRIK.store_dir(), "moved_old_form.csv")
    with open(log, "w", encoding="utf-8") as f:
        f.write("old,new,region\n")
        for (rid, old) in paths.items():
            f.write(f"{old},{GEOFABRIK.extract_path(rid)},{rid}\n")
    assert GEOFABRIK.undo_migration(log) == 3


def test_a_file_that_cannot_be_moved_stays(gf, monkeypatch):
    # One locked file used to end the whole preparation (every tile to
    # Overpass); now it stays, is named, and the others move.
    (paths, gone) = old_layout()
    real = os.replace

    def replace(a, b):
        if a == paths["alsace"]:
            raise PermissionError(13, "in use")
        return real(a, b)

    monkeypatch.setattr(GEOFABRIK.os, "replace", replace)
    (moves, left) = GEOFABRIK.migrate_store(REGIONS)
    assert sorted(m[2] for m in moves) == ["georgia", "us/georgia"]
    assert os.path.isfile(paths["alsace"]) and paths["alsace"] in left
    assert "alsace" not in GEOFABRIK.read_manifest()
    assert any("could not move" in line and "in use" in line for line in gf)
    monkeypatch.setattr(GEOFABRIK.os, "replace", real)
    (moves, _) = GEOFABRIK.migrate_store(REGIONS)  # the next time
    assert [m[2] for m in moves] == ["alsace"]


def test_moved_by_another_process_meanwhile(gf, monkeypatch):
    # The list is made again under the lock: what another process moved
    # in between is not moved twice (os.replace raised FileNotFoundError).
    (paths, _) = old_layout()
    real_lock = GEOFABRIK._store_lock

    class Other:
        def __enter__(self):
            os.makedirs(GEOFABRIK.store_dir(), exist_ok=True)
            os.replace(paths["alsace"], GEOFABRIK.extract_path("alsace"))
            self.lock = real_lock()
            return self.lock.__enter__()

        def __exit__(self, *a):
            return self.lock.__exit__(*a)

    monkeypatch.setattr(GEOFABRIK, "_store_lock", Other)
    (moves, _) = GEOFABRIK.migrate_store(REGIONS)
    assert sorted(m[2] for m in moves) == ["georgia", "us/georgia"]
    assert not any("could not move" in line for line in gf)


def test_side_files_without_an_extract_go(gf):
    # papua-latest.osm.pbf.lock was left by a 404 (2026-11-21), no extract.
    top = GEOFABRIK.data_dir()
    lock = os.path.join(top, "asia", "indonesia", "papua-latest.osm.pbf.lock")
    write(lock, b"")
    write(GEOFABRIK.index_path(), b"{}")
    GEOFABRIK.migrate_store(REGIONS)
    assert not os.path.exists(os.path.join(top, "asia"))


def test_folders_of_the_user_stay(gf):
    old_layout()
    mine = os.path.join(GEOFABRIK.data_dir(), "manual")
    os.makedirs(mine)
    GEOFABRIK.migrate_store(REGIONS)
    assert os.path.isdir(mine)
    assert not os.path.exists(os.path.join(GEOFABRIK.data_dir(), "north-america"))


def test_preparation_moves_first(gf, monkeypatch, fresh):
    calls = []
    monkeypatch.setattr(GEOFABRIK, "load_index", lambda: [])
    monkeypatch.setattr(GEOFABRIK, "migrate_store",
                        lambda regions: calls.append(regions))
    GEOFABRIK.prepare_tiles({(55, 12): {"water": "x"}}, write=False)
    assert calls == [[]]


def test_unused_extracts(gf):
    write(GEOFABRIK.extract_path("alsace"))
    write(GEOFABRIK.extract_path("lorraine"), b"12345")
    assert GEOFABRIK.unused_extracts(REGIONS) == [("lorraine.osm.pbf", 5)]


# --- damaged files, updates, downloads again ----------------------------------
@pytest.fixture
def downloads(monkeypatch):
    calls = []

    def download(url, path, md5=True, check=None):
        calls.append(url)
        write(path, b"new")

    monkeypatch.setattr(GEOFABRIK, "_download", download)
    monkeypatch.setattr(GEOFABRIK, "data_time", lambda p: datetime.datetime(
        2026, 11, 24, tzinfo=datetime.timezone.utc))
    return calls


def test_broken_file_set_aside_and_fetched_again(gf, fresh, downloads,
                                                 monkeypatch):
    # Not even the start of a PBF: never opened by pyosmium.
    monkeypatch.setattr(GEOFABRIK, "data_time", REAL_DATA_TIME)
    r = REGIONS[0]
    path = GEOFABRIK.extract_path(r.id)
    write(path, b"not a pbf at all")
    assert GEOFABRIK.ensure_extract(r) == path
    assert downloads == [r.url]
    with open(path + ".broken", "rb") as f:
        assert f.read() == b"not a pbf at all"
    with open(path, "rb") as f:
        assert f.read() == b"new"
    assert any("cannot be read" in line for line in gf)


PBF_START = (13).to_bytes(4, "big") + b"\x0a\x09OSMHeader" + b"\x18\x00"


def test_pbf_start_check(gf, tmp_path):
    good = tmp_path / "good.osm.pbf"
    good.write_bytes(PBF_START + b"rest")
    assert GEOFABRIK._looks_like_pbf(str(good))
    for data in (b"", b"<osm>", (70000).to_bytes(4, "big") + b"OSMHeader"):
        good.write_bytes(data)
        assert not GEOFABRIK._looks_like_pbf(str(good))


def test_unreadable_pbf_is_set_aside_next_time(gf, fresh, downloads,
                                               monkeypatch):
    # Looks like a PBF, pyosmium fails on it: this process cannot move it
    # (Windows keeps it open), the next preparation does.
    r = REGIONS[0]
    path = GEOFABRIK.extract_path(r.id)
    write(path, PBF_START + b"garbage")

    def unreadable(p):
        raise RuntimeError("PBF error: invalid BlobHeader size")

    monkeypatch.setattr(GEOFABRIK, "_age_days", unreadable)
    with pytest.raises(GEOFABRIK.GeofabrikError, match="set aside next"):
        GEOFABRIK.ensure_extract(r)
    assert GEOFABRIK.read_manifest()["alsace"]["broken"].startswith("PBF")
    assert downloads == []
    assert GEOFABRIK.ensure_extract(r) == path
    assert downloads == [r.url] and os.path.isfile(path + ".broken")
    assert "broken" not in GEOFABRIK.read_manifest()["alsace"]


@pytest.fixture
def old_file(gf, fresh, downloads, monkeypatch):
    r = region("norway", "europe/norway/norway-latest.osm.pbf",
               updates=B + "europe/norway/updates")
    write(GEOFABRIK.extract_path(r.id), PBF_START + b"old")
    age = [3]
    monkeypatch.setattr(GEOFABRIK, "_age_days", lambda p: age[0])
    updates = []
    result = [True]

    def update(path):
        updates.append(path)
        return result[0]

    monkeypatch.setattr(GEOFABRIK, "_update", update)
    monkeypatch.setattr(GEOFABRIK, "_header_server",
                        lambda p: B + "europe/norway-updates")
    return (r, age, updates, result, downloads)


def test_update_ok_is_recorded(old_file):
    (r, age, updates, result, downloads) = old_file
    GEOFABRIK.ensure_extract(r)
    assert len(updates) == 1 and downloads == []
    rec = GEOFABRIK.read_manifest()["norway"]
    assert "update_failures" not in rec and rec["updated"] == rec["checked"]


def test_moved_update_server_leads_to_a_new_download(old_file, gf):
    # The file names europe/norway-updates, the index europe/norway/updates.
    (r, age, updates, result, downloads) = old_file
    result[:] = [False]
    GEOFABRIK.ensure_extract(r)
    assert len(updates) == 1 and downloads == [r.url]
    assert "update_failures" not in GEOFABRIK.read_manifest()["norway"]
    assert any("update server moved" in line for line in gf)


def test_failed_update_on_todays_server_is_counted(old_file, monkeypatch):
    (r, age, updates, result, downloads) = old_file
    result[:] = [False]
    monkeypatch.setattr(GEOFABRIK, "_header_server", lambda p: r.updates)
    GEOFABRIK.ensure_extract(r)
    assert len(updates) == 1 and downloads == []
    assert GEOFABRIK.read_manifest()["norway"]["update_failures"] == 1


def test_failing_updates_lead_to_a_new_download(old_file, monkeypatch):
    (r, age, updates, result, downloads) = old_file
    result[:] = [False]
    monkeypatch.setattr(GEOFABRIK, "_header_server", lambda p: r.updates)
    for n in (1, 2, 3):
        monkeypatch.setattr(GEOFABRIK, "_failed_updates", set())
        GEOFABRIK.ensure_extract(r)
        assert GEOFABRIK.read_manifest()["norway"]["update_failures"] == n
    assert downloads == []
    monkeypatch.setattr(GEOFABRIK, "_failed_updates", set())
    updates.clear()
    GEOFABRIK.ensure_extract(r)  # the 4th time: downloaded again
    assert downloads == [r.url] and updates == []
    rec = GEOFABRIK.read_manifest()["norway"]
    assert "update_failures" not in rec and rec["url"] == r.url
    with open(GEOFABRIK.extract_path("norway"), "rb") as f:
        assert f.read() == b"new"


def test_very_old_data_is_downloaded_again(old_file, gf):
    (r, age, updates, result, downloads) = old_file
    age[0] = GEOFABRIK.REFRESH_AGE + 1
    GEOFABRIK.ensure_extract(r)
    assert downloads == [r.url] and updates == []
    assert any("downloading norway again" in line and "days old" in line
               for line in gf)


def test_failed_new_download_keeps_the_file(old_file, monkeypatch):
    (r, age, updates, result, downloads) = old_file
    age[0] = GEOFABRIK.REFRESH_AGE + 1

    def broken(url, path, md5=True, check=None):
        raise GEOFABRIK.GeofabrikError(f"{url}: HTTPError: 503")

    monkeypatch.setattr(GEOFABRIK, "_download", broken)
    assert GEOFABRIK.ensure_extract(r) == GEOFABRIK.extract_path("norway")
    with open(GEOFABRIK.extract_path("norway"), "rb") as f:
        assert f.read() == PBF_START + b"old"
    assert "norway" in GEOFABRIK._failed_updates


def test_broken_manifest_is_started_again(gf, monkeypatch):
    monkeypatch.setattr(UI, "vprint", lambda *a: None)
    write(GEOFABRIK.manifest_path(), b"{not json")
    assert GEOFABRIK.read_manifest() == {}
    with GEOFABRIK._store_lock():
        GEOFABRIK._record("alsace", url="u")
    assert GEOFABRIK.read_manifest() == {"alsace": {"url": "u"}}


# --- the tool ---------------------------------------------------------------------
def test_tool_knows_store_names():
    spec = importlib.util.spec_from_file_location(
        "prepare_osm_extracts",
        os.path.join(os.path.dirname(__file__), "..",
                     "prepare_osm_extracts.py"))
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    regions = [("us/georgia", "georgia-latest.osm.pbf", BOX)]
    (areas, unknown) = tool.given_areas(
        ["x/us__georgia.osm.pbf", "y/georgia-latest.osm.pbf", "z/a.pbf"],
        regions)
    assert len(areas) == 2 and unknown == ["z/a.pbf"]


def test_hung_update_is_killed(gf, tmp_path, monkeypatch):
    # pyosmium that never exits (seen with --ignore-osmosis-headers): killed
    # after UPDATE_TIMEOUT, no temp file left, the file unchanged.
    path = str(tmp_path / "x.osm.pbf")
    write(path, PBF_START + b"old")
    monkeypatch.setattr(GEOFABRIK, "UPDATE_TIMEOUT", 1)
    monkeypatch.setattr(GEOFABRIK, "_UPDATE_CODE",
                        "import time; print('done', flush=True); "
                        "time.sleep(60)")
    assert GEOFABRIK._update(path) is False
    assert os.listdir(tmp_path) == ["x.osm.pbf"]
    assert any("no end after 1 s" in line and "done" in line for line in gf)


def test_update_that_never_catches_up_fails(gf, tmp_path, monkeypatch):
    # Every run applied changes and exited 1 ("more to come"): the file was
    # recorded as up to date after UPDATE_RUNS runs.
    path = str(tmp_path / "x.osm.pbf")
    write(path, PBF_START + b"old")
    monkeypatch.setattr(GEOFABRIK, "UPDATE_RUNS", 2)
    monkeypatch.setattr(GEOFABRIK, "_UPDATE_CODE",
                        "import sys, shutil; a = sys.argv; "
                        "shutil.copy(a[-1], a[a.index('-o') + 1]); "
                        "sys.exit(1)")
    assert GEOFABRIK._update(path) is False
    assert os.listdir(tmp_path) == ["x.osm.pbf"]
    assert any("still not up to date after 2" in line for line in gf)
