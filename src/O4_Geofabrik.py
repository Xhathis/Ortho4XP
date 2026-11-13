"""OSM layers from Geofabrik extracts first, Overpass as backup (#101).

Before step 1 asks Overpass for a layer, the tile's missing layers are
prepared from Geofabrik's .osm.pbf extracts (O4_OSM_Extract writes the
answers Overpass would give; the build reads them as before, #100):

1. Geofabrik's index-v1.json (regions with their outlines and URLs) is
   kept in geofabrik_dir, fetched again after INDEX_MAX_AGE days.
2. The regions for a tile: the cheapest set of non-continent regions that
   covers the part of the tile inside any of them (choose_regions; region
   area stands in for file size, so a state beats its country and a
   country beats "alps" or "dach"). Sea outside every region needs no file.
   A tile only continents cover (an island in no country extract, e.g.
   Diego Garcia in "asia") is left to Overpass: a continent file is tens
   of GB.
3. Each file is downloaded once (MD5 checked, temp name) into
   geofabrik_dir with Geofabrik's folder layout. A file whose data is
   older than geofabrik_max_age days gets Geofabrik's daily changes
   (pyosmium-up-to-date, a few MB a day) instead of a new download.
4. One read of the files per group of tiles: a batch prepares all its
   tiles before phase 1 (prepare_batch), grouped by the files they need.

Anything that fails here (no index, a download, an extraction gap) only
logs: the layer then comes from Overpass as before. Layers already cached
are never touched; keeping them current is the job of
prepare_osm_extracts.py --check (compare_with_cache).
"""
import bz2
import datetime
import hashlib
import json
import os
import subprocess
import sys
import time

import O4_File_Names as FNAMES
import O4_OSM_Extract as EXTRACT
import O4_OSM_Utils as OSM
import O4_UI_Utils as UI

# Settings (Ortho4XP.cfg, app section).
osm_source = "geofabrik"  # "geofabrik": Geofabrik, then Overpass; "overpass"
geofabrik_dir = ""  # empty: OSM_data/Geofabrik
geofabrik_max_age = 1.0  # days: older data is updated before it is read

BASE_URL = "https://download.geofabrik.de/"
INDEX_URL = BASE_URL + "index-v1.json"
INDEX_MAX_AGE = 30  # days
UPDATE_RUNS = 30  # pyosmium-up-to-date runs of up to 1 GB of changes each
UPDATE_RECHECK = 3600  # s: an update that found nothing waits this long
CHUNK = 1 << 22
# Set while a batch runs after it prepared its tiles (prepare_batch): step 1
# of those tiles does not try again (a parallel worker gets it through the
# batch context).
batch_prepared = False
MIN_GAP = EXTRACT.MIN_GAP

_index_cache = {}  # path -> (mtime, regions)


class GeofabrikError(Exception):
    pass


class Stopped(Exception):
    pass


def _check_stop():
    if UI.stop_requested:
        raise Stopped()


# --- where things go -----------------------------------------------------------
def data_dir():
    return geofabrik_dir or os.path.join(FNAMES.OSM_dir, "Geofabrik")


def index_path():
    return os.path.join(data_dir(), "index-v1.json")


def local_path(url):
    """The file for a Geofabrik URL: its path below the server's root
    (us/georgia and georgia have the same file name)."""
    rel = url[len(BASE_URL):] if url.startswith(BASE_URL) else \
        url.rsplit("/", 1)[-1]
    return os.path.join(data_dir(), *rel.split("/"))


# --- index and regions -----------------------------------------------------------
class Region:
    __slots__ = ("id", "url", "area", "size", "container")

    def __init__(self, rid, url, area, container=False):
        (self.id, self.url, self.area, self.size) = (rid, url, area, area.area)
        self.container = container

    def __repr__(self):
        return f"Region({self.id})"


def mark_containers(regions):
    """Flag the regions that hold another region (netherlands holds its
    provinces, us-northeast the states, alps parts of 5 countries; the
    index's parent field misses the composites). Outside the regions it
    holds, a container's outline only adds sea (the Dutch North Sea, the
    Atlantic off New York): choose_regions does not make a file be read
    for that, as for the sea a continent adds."""
    from shapely import strtree
    tree = strtree.STRtree([r.area for r in regions])
    for r in regions:
        for i in tree.query(r.area):
            s = regions[i]
            if s is not r and s.size < r.size and \
                    r.area.intersection(s.area).area >= 0.9 * s.size:
                r.container = True
                break
    return regions


def parse_index(text):
    """[Region] of an index-v1.json text (regions with a .pbf and outline)."""
    import shapely
    from shapely import geometry
    regions = []
    for feature in json.loads(text)["features"]:
        props = feature.get("properties", {})
        url = props.get("urls", {}).get("pbf", "")
        if feature.get("geometry") and url:
            area = geometry.shape(feature["geometry"])
            if not area.is_valid:
                # Some outlines cross themselves (2026-11: a Chinese one);
                # GEOS refuses to intersect those.
                area = shapely.make_valid(area)
            regions.append(Region(props["id"], url, area))
    return mark_containers(regions)


def read_index(path):
    """[Region] of an index file; GeofabrikError if it is not a valid index
    (e.g. an HTML error page the server sent with HTTP 200)."""
    from shapely.errors import ShapelyError
    try:
        with open(path, encoding="utf-8") as f:
            return parse_index(f.read())
    except (ValueError, KeyError, TypeError, AttributeError,
            ShapelyError) as e:
        # ValueError covers JSONDecodeError and UnicodeDecodeError.
        raise GeofabrikError(f"{path} is not a valid Geofabrik index "
                             f"({type(e).__name__}: {e})")


def load_index(download=True):
    """The regions of Geofabrik's index, fetched when missing, old or
    broken. A download is checked before it replaces the old file, so a
    bad answer never stays for INDEX_MAX_AGE days."""
    path = index_path()
    old = (not os.path.isfile(path)
           or time.time() - os.path.getmtime(path) > INDEX_MAX_AGE * 86400)
    fetched = False
    if old and download:
        try:
            _download(INDEX_URL, path, md5=False, check=read_index)
            fetched = True
        except (OSError, GeofabrikError) as e:
            if not os.path.isfile(path):
                raise GeofabrikError(f"no Geofabrik index ({e})")
            UI.vprint(1, f"    Could not refresh {path} ({e}), using it.")
    if not os.path.isfile(path):
        raise GeofabrikError(f"no Geofabrik index {path}")
    mtime = os.path.getmtime(path)
    if _index_cache.get(path, (None,))[0] != mtime:
        try:
            regions = read_index(path)
        except GeofabrikError as e:
            if fetched or not download:
                raise
            # A broken file kept by an older version: fetch it again.
            UI.vprint(1, f"    {e}; fetching it again.")
            _download(INDEX_URL, path, md5=False, check=read_index)
            (mtime, regions) = (os.path.getmtime(path), read_index(path))
        _index_cache[path] = (mtime, regions)
    return _index_cache[path][1]


def choose_regions(lat, lon, regions):
    """(regions, kind) for a tile. kind "land": the regions to read (they
    cover every part of the tile that lies in a region holding no other,
    see mark_containers); "sea": no region touches the tile, nothing to
    read; "continent": only continents cover it (no regions returned: left
    to Overpass).

    Greedy set cover: the region covering the most of what is left per
    unit of its own area first, so small files win; then a chosen region
    the others cover after all is dropped (largest first).
    """
    from shapely import geometry, ops
    box = geometry.box(lon, lat, lon + 1, lat + 1)
    near = [r for r in regions if r.area.intersects(box)]
    countries = [r for r in near if r.id not in EXTRACT.CONTINENTS]
    if not near:
        return ([], "sea")
    if not countries:
        return ([], "continent")
    parts = {r.id: r.area.intersection(box) for r in countries}
    inner = [parts[r.id] for r in countries if not r.container]
    # A tile only containers reach (e.g. far out in a country's waters):
    # their outlines then are all there is to go by.
    target = ops.unary_union(inner or list(parts.values()))
    (left, chosen) = (target, [])
    while left.area > MIN_GAP:
        best = max((r for r in countries if r not in chosen),
                   key=lambda r: (parts[r.id].intersection(left).area / r.size,
                                  -r.size),
                   default=None)
        if best is None or parts[best.id].intersection(left).area <= MIN_GAP:
            break
        chosen.append(best)
        left = left.difference(parts[best.id])
    for r in sorted(chosen, key=lambda r: -r.size):
        rest = [parts[o.id] for o in chosen if o is not r]
        if rest and target.difference(ops.unary_union(rest)).area <= MIN_GAP:
            chosen.remove(r)
    return (sorted(chosen, key=lambda r: r.id), "land")


def group_tiles(plan):
    """[(urls, tiles)] from plan {tile: frozenset(urls)}: tiles needing the
    same files share one read, and a tile whose files are a subset of a
    bigger group's joins that group (an extra file costs only its read)."""
    groups = {}
    for (tile, urls) in plan.items():
        groups.setdefault(urls, []).append(tile)
    merged = {}
    for urls in sorted(groups, key=len, reverse=True):
        home = next((u for u in merged if urls <= u), None)
        merged.setdefault(home or urls, []).extend(groups[urls])
    return [(sorted(urls), sorted(tiles)) for (urls, tiles) in merged.items()]


# --- files: download and update --------------------------------------------------
def _session():
    import requests
    OSM._prefer_ipv4_without_ipv6_route()
    s = requests.Session()
    s.headers["User-Agent"] = "Ortho4XP"
    return s


def _md5_of(text, url):
    """The checksum of a .md5 answer ("<32 hex digits>  name")."""
    parts = text.split()
    digest = parts[0].lower() if parts else ""
    if len(digest) != 32 or any(c not in "0123456789abcdef" for c in digest):
        raise GeofabrikError(f"{url}.md5: no checksum in the answer "
                             f"({text[:60]!r})")
    return digest


def _download(url, path, md5=True, check=None):
    """Download url to path (temp name, os.replace). With md5, check the
    file against Geofabrik's url.md5; check(temp path) may raise
    GeofabrikError to refuse the file."""
    import requests
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = FNAMES.temp_path_for(path)
    try:
        with _session() as s:
            expected = None
            if md5:
                with s.get(url + ".md5", timeout=(30, 60)) as r:
                    r.raise_for_status()
                    expected = _md5_of(r.text, url)
            with s.get(url, stream=True, timeout=(30, 120)) as r:
                r.raise_for_status()
                total = int(r.headers.get("Content-Length", 0))
                (h, done, shown) = (hashlib.md5(), 0, time.time())
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(CHUNK):
                        _check_stop()
                        f.write(chunk)
                        h.update(chunk)
                        done += len(chunk)
                        if time.time() - shown > 30:
                            shown = time.time()
                            UI.vprint(1, f"      {done / 1e6:.0f} of "
                                      f"{total / 1e6:.0f} MB")
        if expected and h.hexdigest() != expected:
            raise GeofabrikError(f"{url}: MD5 mismatch (download cut?)")
        if check:
            check(tmp)
        os.replace(tmp, path)
    except requests.RequestException as e:
        raise GeofabrikError(f"{url}: {type(e).__name__}: {e}")
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def data_time(path):
    """The time of a file's data (Geofabrik's replication timestamp), as a
    UTC datetime; the file time if the header has none."""
    import osmium
    reader = osmium.io.Reader(path, osmium.osm.osm_entity_bits.NOTHING)
    try:
        ts = reader.header().get("osmosis_replication_timestamp")
    finally:
        reader.close()
    if ts:
        return datetime.datetime.strptime(
            ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    return datetime.datetime.fromtimestamp(os.path.getmtime(path),
                                           datetime.timezone.utc)


def _age_days(path):
    now = datetime.datetime.now(datetime.timezone.utc)
    return (now - data_time(path)).total_seconds() / 86400


_UPDATE_CODE = ("import sys; from osmium.tools.pyosmium_up_to_date import main;"
                " sys.exit(main())")


def _update(path):
    """Apply Geofabrik's changes since the file's data time (in place,
    through a temp file). True when up to date; False if the server could
    not be used (the file is left as it was)."""
    for _ in range(UPDATE_RUNS):
        tmp = FNAMES.temp_path_for(path)
        proc = subprocess.Popen(
            [sys.executable, "-c", _UPDATE_CODE, "-v", "--size", "1024",
             "-o", tmp, path],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            env=UI.subprocess_env())
        complete = False
        try:
            while proc.poll() is None:
                if UI.stop_requested:
                    proc.kill()
                    proc.wait()
                    raise Stopped()
                time.sleep(0.5)
            out = proc.stdout.read().decode("utf-8", "replace")
            complete = proc.returncode in (0, 1)
        finally:
            proc.stdout.close()
            # Not on the exit code alone: on Windows a killed process
            # exits 1, the code for "more changes to come" (Stop used to
            # leave a temp file as big as the extract).
            if not complete and os.path.exists(tmp):
                os.remove(tmp)
        if not complete:
            UI.lvprint(1, f"   WARNING: could not update {path} (exit "
                       f"{proc.returncode}): {out.strip()[-300:]}")
            return False
        if os.path.exists(tmp):
            os.replace(tmp, path)
        if proc.returncode == 0:
            return True
    return True


def _checked_path(path):
    return path + ".checked"


def _remove_leftover_temps(path):
    """Temp files of path (FNAMES.temp_path_for) that a killed run left.
    Called under path's lock: no other process is writing one."""
    (folder, name) = os.path.split(path)
    try:
        names = os.listdir(folder)
    except OSError:
        return
    for n in names:
        if n.startswith(".tmp") and n.endswith("_" + name):
            try:
                os.remove(os.path.join(folder, n))
                UI.vprint(1, f"    Removed the leftover temp file {n}.")
            except OSError as e:
                UI.vprint(1, f"    Could not remove {n} ({e}).")


def ensure_file(url):
    """The local file for url: downloaded if missing, updated if older
    than geofabrik_max_age days. Locked against other processes."""
    path = local_path(url)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with _FileLock(path + ".lock"):
        _remove_leftover_temps(path)
        if not os.path.isfile(path):
            UI.vprint(1, f"    Downloading {url}")
            start = time.time()
            _download(url, path)
            UI.lvprint(1, f"    Geofabrik: downloaded {os.path.basename(path)}"
                       f" ({os.path.getsize(path) / 1e6:.0f} MB, "
                       f"{time.time() - start:.0f} s).")
            return path
        age = _age_days(path)
        checked = _checked_path(path)
        recently = (os.path.isfile(checked)
                    and time.time() - os.path.getmtime(checked) < UPDATE_RECHECK)
        if age > geofabrik_max_age and not recently:
            UI.vprint(1, f"    Updating {os.path.basename(path)} (data of "
                      f"{data_time(path):%Y-%m-%d %H:%M} UTC)")
            if _update(path):
                with open(checked, "w"):
                    pass
            UI.vprint(1, f"    {os.path.basename(path)}: data of "
                      f"{data_time(path):%Y-%m-%d %H:%M} UTC")
    return path


class _FileLock:
    """An exclusive lock on a file, waited for (Stop ends the wait)."""

    def __init__(self, path):
        self.path = path
        self.f = None

    def __enter__(self):
        self.f = open(self.path, "a+")
        while True:
            try:
                OSM._lock_file(self.f)
                return self
            except OSError:
                if UI.stop_requested:
                    self.f.close()
                    raise Stopped()
                time.sleep(2)

    def __exit__(self, *exc):
        try:
            OSM._unlock_file(self.f)
        finally:
            self.f.close()


# --- what a tile needs ------------------------------------------------------------
def needed_layers(lat, lon, road_level, force=False):
    """{layer: statements} of the layers step 1 will ask Overpass for:
    not cached, no extract answer, no custom coastline/water file."""
    layers = EXTRACT.layer_statements(road_level)
    if os.path.isfile(FNAMES.custom_coastline(lat, lon)) or \
            os.path.isdir(FNAMES.custom_coastline_dir(lat, lon)):
        layers.pop("coastline")
    if os.path.isfile(FNAMES.custom_water(lat, lon)) or \
            os.path.isdir(FNAMES.custom_water_dir(lat, lon)):
        layers.pop("water")
    if force:
        return layers
    return {layer: st for (layer, st) in layers.items()
            if not os.path.isfile(FNAMES.osm_cached(lat, lon, layer))
            and not os.path.isfile(EXTRACT.answer_path(lat, lon, layer))}


def _sea_answers(layers):
    """Empty answers for a tile outside every Geofabrik region."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return {layer: EXTRACT.answer_xml(
        st, "no Geofabrik region (open sea)",
        now.strftime("%Y-%m-%dT%H:%M:%SZ"), {}, {}, {})
        for (layer, st) in layers.items()}


def plan_tiles(wanted, regions):
    """({tile: frozenset(urls)}, {tile: reason left to Overpass}, [sea
    tiles]) for wanted {tile: layers}."""
    (plan, left, sea) = ({}, {}, [])
    for (lat, lon) in wanted:
        (chosen, kind) = choose_regions(lat, lon, regions)
        if kind == "sea":
            sea.append((lat, lon))
        elif kind == "continent":
            left[(lat, lon)] = ("only in a continent extract, "
                                "not downloaded")
        else:
            plan[(lat, lon)] = frozenset(r.url for r in chosen)
    return (plan, left, sea)


def prepare_tiles(wanted, write=True):
    """Prepare answers for wanted {(lat, lon): {layer: statements}}.

    Returns ({tile: {layer: bytes}} of the answers, {tile: reason} of the
    tiles left to Overpass). With write, the answers are stored where
    step 1 reads them. Raises Stopped on Stop, GeofabrikError when the
    index cannot be had.
    """
    if not wanted:
        return ({}, {})
    regions = load_index()
    (plan, left, sea) = plan_tiles(wanted, regions)
    done = {}
    for tile in sea:
        done[tile] = _sea_answers(wanted[tile])
    for (urls, tiles) in group_tiles(plan):
        names = ", ".join(u.rsplit("/", 1)[-1] for u in urls)
        try:
            files = [ensure_file(u) for u in urls]
        except (GeofabrikError, OSError) as e:
            for tile in tiles:
                left[tile] = f"no extract file ({e})"
            continue
        UI.vprint(1, f"    Reading {names} for {len(tiles)} tile(s)")
        start = time.time()

        def log(message):
            _check_stop()
            UI.vprint(2, message)

        try:
            (answers, failed) = EXTRACT.extract_answers(
                files, {t: wanted[t] for t in tiles}, log=log)
        except (OSError, RuntimeError) as e:
            # pyosmium raises RuntimeError for a broken file.
            for tile in tiles:
                left[tile] = f"reading {names} failed ({e})"
            continue
        UI.vprint(1, f"    {names}: {time.time() - start:.0f} s")
        done.update(answers)
        left.update(failed)
    if write:
        for ((lat, lon), layers) in done.items():
            for (layer, content) in layers.items():
                EXTRACT.write_answer(EXTRACT.answer_path(lat, lon, layer),
                                     content)
    return (done, left)


def _report(done, left):
    if done:
        UI.lvprint(1, "    Geofabrik: OSM data prepared for "
                   + " ".join(FNAMES.short_latlon(*t) for t in sorted(done)))
    for (tile, reason) in sorted(left.items()):
        UI.lvprint(1, f"    Geofabrik: no local OSM data for "
                   f"{FNAMES.short_latlon(*tile)} ({reason}); Overpass will "
                   "be asked.")


def prepare_tile(tile):
    """Step 1 of a tile: its missing layers from Geofabrik first. False
    only on Stop; any failure leaves the layers to Overpass."""
    if osm_source != "geofabrik" or batch_prepared:
        return True
    wanted = needed_layers(tile.lat, tile.lon, tile.road_level)
    if not wanted:
        return True
    UI.vprint(0, "-> Preparing OSM data from Geofabrik")
    try:
        _report(*prepare_tiles({(tile.lat, tile.lon): wanted}))
    except Stopped:
        return False
    except (GeofabrikError, OSError) as e:
        UI.lvprint(1, f"   WARNING: Geofabrik extracts not used ({e}); "
                   "asking Overpass.")
    return True


def prepare_batch(wanted):
    """A batch's tiles {tile: {layer: statements}}, before its phase 1.
    False only on Stop."""
    if osm_source != "geofabrik":
        return True
    wanted = {t: layers for (t, layers) in wanted.items() if layers}
    if not wanted:
        return True
    UI.vprint(0, f"Preparing OSM data from Geofabrik for {len(wanted)} "
              "tile(s).")
    start = time.time()
    try:
        _report(*prepare_tiles(wanted))
    except Stopped:
        UI.lvprint(0, "Batch stopped while preparing OSM data.")
        return False
    except (GeofabrikError, OSError) as e:
        UI.lvprint(1, f"   WARNING: Geofabrik extracts not used ({e}); "
                   "asking Overpass.")
    UI.vprint(0, f"OSM data prepared in {UI.nicer_timer(time.time() - start)}.")
    return True


# --- freshness of cached layers ------------------------------------------------------
TAGS_OF_INTEREST = {"coastline": [], "airports": ["all"], "water": ["name"],
                    "big_roads": ["bridge", "tunnel"],
                    "small_roads": ["bridge", "tunnel"]}


def cache_bytes(layer, statements, answer):
    """The cache file content (uncompressed) step 1 makes from an answer."""
    (input_tags, target_tags) = OSM.layer_tags(statements,
                                               TAGS_OF_INTEREST[layer])
    osm_layer = OSM.OSM_layer()
    if not osm_layer.update_dicosm(answer, input_tags, target_tags):
        raise GeofabrikError(f"{layer}: answer not readable")
    tmp = FNAMES.temp_path_for(os.path.join(FNAMES.Tmp_dir, layer + ".osm.bz2"))
    try:
        osm_layer.write_to_file(tmp)
        with bz2.open(tmp, "rb") as f:
            return f.read()
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def way_keys(content):
    """{(tags, coordinates)} of the ways of a cache file's content: ids are
    renumbered by the cache writer, so ways are compared by content."""
    import re
    nodes = {nid: (la, lo) for (nid, la, lo) in re.findall(
        rb'<node id="(-?\d+)" lat="([^"]*)" lon="([^"]*)"', content)}
    keys = set()
    for body in re.findall(rb"<way id=.*?</way>", content, re.S):
        refs = re.findall(rb'<nd ref="(-?\d+)"', body)
        tags = tuple(sorted(re.findall(rb'<tag k="([^"]*)" v="([^"]*)"',
                                       body)))
        keys.add((tags, tuple(nodes.get(r, r) for r in refs)))
    return keys


def compare_with_cache(lat, lon, layer, statements, answer):
    """(same, ways only in the cache, ways only in the fresh data)."""
    with bz2.open(FNAMES.osm_cached(lat, lon, layer), "rb") as f:
        old = f.read()
    new = cache_bytes(layer, statements, answer)
    if old == new:
        return (True, 0, 0)
    (a, b) = (way_keys(old), way_keys(new))
    return (False, len(a - b), len(b - a))
