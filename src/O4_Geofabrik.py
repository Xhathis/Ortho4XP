"""OSM layers from Geofabrik extracts first, Overpass as backup (#101).

Before step 1 asks Overpass for a layer, the tile's missing layers are
prepared from Geofabrik's .osm.pbf extracts (O4_OSM_Extract writes the
answers Overpass would give; the build reads them as before, #100):

1. Geofabrik's index-v1.json (regions with their outlines and URLs) is
   kept in geofabrik_dir, fetched again after INDEX_MAX_AGE days, and
   when an extract's URL answers 404 (at most once a day, #128).
2. The regions for a tile: the cheapest set of non-continent regions that
   covers the part of the tile inside any of them (choose_regions; region
   area stands in for file size, so a state beats its country and a
   country beats "alps" or "dach"). Sea outside every region needs no file.
   A tile only continents cover (an island in no country extract, e.g.
   Diego Garcia in "asia"), or with land outside its country regions
   that only a continent holds (gap_continents, #120), reads the
   continent file when it is on disk and is left to Overpass otherwise:
   a continent file is tens of GB and never downloaded here.
3. Each file is downloaded once (MD5 checked, temp name) into
   geofabrik_dir/extracts, named after its region id (alsace.osm.pbf,
   us__georgia.osm.pbf), not after Geofabrik's URL: their folder layout
   changed in 2026-11 and may again (#129). extracts/extracts.json records
   where each came from and how its updates went. A file whose data is
   older than geofabrik_max_age days gets Geofabrik's daily changes
   (pyosmium-up-to-date, a few MB a day) instead of a new download; when
   updates keep failing or the data is very old, it is downloaded again.
   A file that cannot be read is set aside and downloaded again. Files of
   the old layout are moved into extracts/ (migrate_store).
4. One read of the files per group of tiles: a batch prepares all its
   tiles before phase 1 (prepare_batch), grouped by the files they need.

Anything that fails here (no index, a download, an extraction gap) only
logs: the layer then comes from Overpass as before. Layers already cached
are kept, unless osm_cache_max_age is set: a cached layer older than that
many days is prepared again, and step 1 then prefers the newer answer to
the cache (the cache stays in use when no answer comes). Without it,
prepare_osm_extracts.py --check (compare_with_cache) shows what changed.
"""
import bz2
import csv
import datetime
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time

import O4_File_Names as FNAMES
import O4_OSM_Extract as EXTRACT
import O4_OSM_Utils as OSM
import O4_UI_Utils as UI

# Settings (Ortho4XP.cfg, app section).
osm_source = "geofabrik"  # "geofabrik": Geofabrik, then Overpass; "overpass"
geofabrik_dir = ""  # empty: OSM_data/Geofabrik
geofabrik_max_age = 1.0  # days: older data is updated before it is read
osm_cache_max_age = 0.0  # days: older cached layers are refreshed; 0 = never

BASE_URL = "https://download.geofabrik.de/"
INDEX_URL = BASE_URL + "index-v1.json"
INDEX_MAX_AGE = 30  # days
# An extract URL answering 404 fetches the index again, unless it is
# younger than this (#128).
INDEX_RECHECK = 1.0  # days
UPDATE_RUNS = 30  # pyosmium-up-to-date runs of up to 1 GB of changes each
UPDATE_TIMEOUT = 7200  # s per run; a hung pyosmium is killed (#129)
UPDATE_RECHECK = 3600  # s: an update that found nothing waits this long
# A file is downloaded again instead of updated when its updates failed this
# many preparations in a row, or its data is older than REFRESH_AGE days
# (a month of daily diffs is about as big as the file).
UPDATE_FAILURES_MAX = 3
REFRESH_AGE = 30  # days
STORE_DIR = "extracts"
CHUNK = 1 << 22
# group_tiles: groups that share a file are read as one up to this many
# tiles (a group that is bigger on its own is never split).
MAX_MERGED_TILES = 16
# Set while a batch runs after it prepared its tiles (prepare_batch): step 1
# of those tiles does not try again (a parallel worker gets it through the
# batch context).
batch_prepared = False
MIN_GAP = EXTRACT.MIN_GAP
# mark_containers: share of a region's outline the regions inside it must
# cover for it to count as made of them (index of 2026-11: composites
# 0.40-1.0, regions with enclaves 0.0003-0.14).
CONTAINER_MIN_SHARE = 0.25

_index_cache = {}  # path -> (mtime, regions)
# Within one preparation (prepare_tiles: a batch's, or one tile's), a file
# that failed to download or update is not asked for again: several tile
# groups can share a file, and each would start the whole download anew
# (Geofabrik objects to repeated downloads of the same file).
_failed_downloads = {}  # region id -> error message
_failed_updates = set()  # region ids
# Why fetching the index again after a 404 failed (one try per preparation).
_index_refresh_error = None


class GeofabrikError(Exception):
    pass


class GeofabrikNotFound(GeofabrikError):
    """The extract's URL answered 404 (in every folder layout tried)."""


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


def extract_path(rid):
    """The file of Geofabrik region rid (#129): one folder, a name from the
    region id alone, so a change of Geofabrik's URLs moves nothing."""
    return os.path.join(store_dir(), EXTRACT.store_name(rid))


def store_dir():
    return os.path.join(data_dir(), STORE_DIR)


def manifest_path():
    return os.path.join(store_dir(), "extracts.json")


def local_path(url):
    """Where files were kept before #129 (migrate_store moves them): the
    URL's path below the server's root (us/georgia and georgia have the
    same file name).

    Since 2026-11 Geofabrik puts every region in a folder of its own
    (europe/france/alsace/alsace-latest.osm.pbf, was
    europe/france/alsace-latest.osm.pbf; the old URLs redirect). That
    folder is left out, so the files downloaded before stay where they
    are, whichever form the index gives (#118)."""
    rel = url[len(BASE_URL):] if url.startswith(BASE_URL) else \
        url.rsplit("/", 1)[-1]
    parts = rel.split("/")
    # Exactly the region's name: us/us-virgin-islands-latest is the old
    # form (region us-virgin-islands in folder us), not the new one.
    if len(parts) >= 2 and parts[-1].split("-latest.", 1)[0] == parts[-2]:
        del parts[-2]
    return os.path.join(data_dir(), *parts)


# --- index and regions -----------------------------------------------------------
class Region:
    __slots__ = ("id", "url", "area", "size", "container", "updates")

    def __init__(self, rid, url, area, container=False, updates=None):
        (self.id, self.url, self.area, self.size) = (rid, url, area, area.area)
        self.container = container
        self.updates = updates  # replication server of the extract (index)

    def __repr__(self):
        return f"Region({self.id})"


def mark_containers(regions):
    """Flag the regions made of other regions (netherlands of its
    provinces, us-northeast of the states, norway of its 5 parts; the
    index's parent field misses the composites). Outside the regions it
    holds, a container's outline only adds sea (the Dutch North Sea, the
    Atlantic off New York): choose_regions does not make a file be read
    for that, as for the sea a continent adds.

    Holding a region is not enough: Geofabrik's outlines have enclaves
    (ceuta and melilla in morocco, bremen in niedersachsen, kaliningrad in
    northwestern-fed-district, berlin in brandenburg). Taken for containers,
    their land was treated as sea and never read (2026-11-14 batch: 4
    tiles failed on an open coastline, 9 built without roads and water
    there). So the smaller regions at least half inside it must cover
    CONTAINER_MIN_SHARE of the outline: composites cover 0.40 (australia,
    much ocean) to 1.0, regions with enclaves at most 0.14 (portugal with
    the azores; morocco 0.0003). Half, not all: alps holds no country
    whole, yet they cover 0.72 of it.
    """
    from shapely import strtree, ops
    tree = strtree.STRtree([r.area for r in regions])
    for r in regions:
        held = [regions[i].area for i in tree.query(r.area)
                if regions[i] is not r and regions[i].size < r.size
                and r.area.intersection(regions[i].area).area
                >= 0.5 * regions[i].size]
        r.container = bool(held) and (
            ops.unary_union(held).intersection(r.area).area
            >= CONTAINER_MIN_SHARE * r.size)
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
            regions.append(Region(props["id"], url, area,
                                  updates=props["urls"].get("updates")))
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


# Land that only a continent file holds (#120). choose_regions takes the
# part of a tile outside every country region for sea: true for nearly
# all of the 3,668 tiles a continent reaches beyond its countries, but
# not for islands in no country extract next to one that has a file
# (Dominica, Montserrat, Saba, the Turks and Caicos next to guadeloupe,
# the US Virgin Islands, the Bahamas): their cache refresh of 2026-11-14
# replaced good Overpass data with answers without them, and the tiles
# were built with those islands as sea. The tile's elevation file tells
# land from sea there.
GAP_EDGE = 0.002  # deg: outlines and DEM samples along a border
GAP_LAND_MIN = 4  # land samples (3" grid: ~0.03 km2) that count as land
GAP_GRID = 1201  # finer elevation files are read at this grid


def _land_samples(lat, lon):
    """(lons, lats) of the tile's elevation samples above 0 m, from its
    Viewfinder/SRTM .hgt (read only), or None without one."""
    import numpy
    path = FNAMES.viewfinderpanorama(lat, lon)
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    n = int(round((size // 2) ** 0.5))
    if n < 2 or n * n * 2 != size:
        return None
    alt = numpy.fromfile(path, dtype=">i2").reshape(n, n)
    step = max(1, (n - 1) // (GAP_GRID - 1))
    alt = alt[::step, ::step]
    (rows, cols) = numpy.nonzero(alt > 0)
    m = alt.shape[0] - 1
    return (lon + cols / m, lat + 1 - rows / m)


def gap_continents(lat, lon, regions):
    """The continents holding land of the tile that no country region
    covers (empty when its elevation file shows none, or there is no
    such file: then the old rule, sea, stands)."""
    import shapely
    from shapely import geometry, ops
    box = geometry.box(lon, lat, lon + 1, lat + 1)
    near = [r for r in regions if r.area.intersects(box)]
    countries = [r for r in near if r.id not in EXTRACT.CONTINENTS]
    continents = [r for r in near if r.id in EXTRACT.CONTINENTS]
    if not countries or not continents:
        return []
    cover = ops.unary_union([r.area.intersection(box) for r in countries])
    gap = ops.unary_union([r.area.intersection(box) for r in continents]) \
        .difference(cover.buffer(GAP_EDGE))
    if gap.area <= MIN_GAP:
        return []
    land = _land_samples(lat, lon)
    if land is None:
        return []
    inside = shapely.contains_xy(gap, *land)
    if inside.sum() < GAP_LAND_MIN:
        return []
    (xs, ys) = (land[0][inside], land[1][inside])
    return [r for r in continents if shapely.contains_xy(r.area, xs, ys).any()]


def _on_disk(regions):
    return all(os.path.isfile(extract_path(r.id)) for r in regions)


def group_tiles(plan):
    """[(ids, tiles)] from plan {tile: frozenset(region ids)}: tiles needing the
    same files share one read, and a tile whose files are a subset of a
    bigger group's joins that group (an extra file costs only its read).
    Then groups that share a file are read together (norway for the tiles
    on the Swedish and on the Finnish border was read twice, ~6 min each)
    while the merged group stays within MAX_MERGED_TILES: the extraction
    holds the data of all tiles of a group at once (up to ~1 GB for a
    dense tile), and borders chain whole continents. So no group is
    bigger than without the merging, or than MAX_MERGED_TILES."""
    groups = {}
    for (tile, urls) in plan.items():
        groups.setdefault(urls, []).append(tile)
    merged = {}
    for urls in sorted(groups, key=lambda u: (-len(u), sorted(u))):
        home = next((u for u in merged if urls <= u), None)
        merged.setdefault(home or urls, []).extend(groups[urls])
    out = []  # [[set of urls, [tiles]]]
    for urls in sorted(merged, key=lambda u: (len(merged[u]), sorted(u))):
        tiles = merged[urls]
        home = next((g for g in out if urls & g[0] and len(g[1]) + len(tiles)
                     <= MAX_MERGED_TILES), None)
        if home:
            home[0].update(urls)
            home[1].extend(tiles)
        else:
            out.append([set(urls), list(tiles)])
    return sorted((sorted(u), sorted(t)) for (u, t) in out)


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


def _expected_md5(s, urls):
    """The checksum from the first of urls' .md5 files that exists; None
    when none does (HTTP 404). Other failures raise."""
    for u in urls:
        with s.get(u + ".md5", timeout=(30, 60)) as r:
            if r.status_code == 404:
                continue
            r.raise_for_status()
            return _md5_of(r.text, u)
    return None


def url_variants(url):
    """url, then the same extract in Geofabrik's other folder layout
    (europe/france/alsace/alsace-latest.osm.pbf <->
    europe/france/alsace-latest.osm.pbf, #118).

    On 2026-11-21/22 the old URL of papua redirected to
    indonesia/papua/papua-latest.osm.pbf, without "asia/" (404), and our
    index (fetched every 30 days) still gave the old URLs: 5 tiles went to
    Overpass. Geofabrik fixed the redirect by 11-24; asking the new form
    ourselves no longer depends on their redirects (#127). Both forms give
    the same local_path."""
    if not url.startswith(BASE_URL) or "-latest." not in url:
        return [url]
    parts = url[len(BASE_URL):].split("/")
    rid = parts[-1].split("-latest.", 1)[0]
    if len(parts) >= 3 and parts[-2] == rid:
        other = parts[:-2] + parts[-1:]
    else:
        other = parts[:-1] + [rid, parts[-1]]
    return [url, BASE_URL + "/".join(other)]


def _download(url, path, md5=True, check=None):
    """Download url to path (temp name, os.replace). With md5, check the
    file against Geofabrik's .md5; check(temp path) may raise
    GeofabrikError to refuse the file.

    Since 2026-11 Geofabrik's ...-latest.osm.pbf redirects to the dated
    file (alsace-261119.osm.pbf), and only that one has a .md5 (#118): the
    checksum is asked for the URL the download ended at, which also keeps
    file and checksum together when a new day's file appears in between.
    Without any .md5 the size must match the announced Content-Length.
    """
    import requests
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = FNAMES.temp_path_for(path)
    try:
        with _session() as s:
            expected = None
            variants = url_variants(url)
            for (n, asked) in enumerate(variants):
                r = s.get(asked, stream=True, timeout=(30, 120))
                if r.status_code != 404 or n + 1 == len(variants):
                    break
                r.close()
                UI.vprint(1, f"    {asked}: not found (HTTP 404), trying "
                          f"{variants[n + 1]}")
            with r:
                if r.status_code == 404:
                    raise GeofabrikNotFound(
                        f"{url}: HTTP 404 Not Found"
                        + (f" (also {', '.join(variants[1:])})"
                           if len(variants) > 1 else ""))
                r.raise_for_status()
                if md5:
                    final = getattr(r, "url", None) or asked
                    expected = _expected_md5(
                        s, [final] + ([asked] if final != asked else []))
                    if expected is None:
                        UI.vprint(1, f"    No .md5 for {final}: checking the "
                                  "download's size only.")
                total = int(r.headers.get("Content-Length", 0))
                # requests decodes a gzip answer: Content-Length is then
                # the compressed size.
                if r.headers.get("Content-Encoding", "identity") != "identity":
                    total = 0
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
        if total and done != total:
            raise GeofabrikError(f"{url}: {done} of {total} bytes "
                                 "(download cut)")
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
    through a temp file), from the replication server the file names.
    True when up to date; False if the server could not be used (the file
    is left as it was)."""
    for _ in range(UPDATE_RUNS):
        tmp = FNAMES.temp_path_for(path)
        # Output to a file, not a pipe: a pipe nobody reads while the
        # process runs blocks it once the buffer is full.
        with tempfile.TemporaryFile() as log:
            proc = subprocess.Popen(
                [sys.executable, "-c", _UPDATE_CODE, "-v", "--size", "1024",
                 "-o", tmp, path],
                stdout=log, stderr=subprocess.STDOUT,
                env=UI.subprocess_env())
            complete = False
            timed_out = False
            try:
                start = time.monotonic()
                while proc.poll() is None:
                    if UI.stop_requested:
                        proc.kill()
                        proc.wait()
                        raise Stopped()
                    if time.monotonic() - start > UPDATE_TIMEOUT:
                        proc.kill()
                        proc.wait()
                        timed_out = True
                        break
                    time.sleep(0.5)
                complete = not timed_out and proc.returncode in (0, 1)
            finally:
                # Not on the exit code alone: on Windows a killed process
                # exits 1, the code for "more changes to come" (Stop used
                # to leave a temp file as big as the extract).
                if not complete and os.path.exists(tmp):
                    os.remove(tmp)
            log.seek(0)
            out = log.read().decode("utf-8", "replace")
        if not complete:
            why = (f"no end after {UPDATE_TIMEOUT} s" if timed_out
                   else f"exit {proc.returncode}")
            UI.lvprint(1, f"   WARNING: could not update {path} ({why}): "
                       f"{out.strip()[-300:]}")
            return False
        if os.path.exists(tmp):
            os.replace(tmp, path)
        if proc.returncode == 0:
            return True
    # Every run applied changes and said more are to come: closer, but not
    # up to date (counted as a failed update; a new download follows).
    UI.lvprint(1, f"   WARNING: {path} still not up to date after "
               f"{UPDATE_RUNS} update runs.")
    return False


def _remove_leftover_temps(path):
    """Temp files of path (FNAMES.temp_path_for) that a killed run left.
    Called under the store's lock: no other process is writing one."""
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


# --- the store: extracts by region id (#129) ------------------------------------
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime(TIME_FORMAT)


def read_manifest():
    """{region id: record} of extracts.json; {} when missing or broken (the
    files are found by name without it, only their history is lost)."""
    try:
        with open(manifest_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        UI.vprint(1, f"    {manifest_path()} unreadable ({e}), starting a new "
                  "one.")
        return {}


def _record(rid, **fields):
    """Update the manifest record of rid (under the store's lock); a field
    set to None is removed."""
    data = read_manifest()
    rec = data.setdefault(rid, {})
    for (k, v) in fields.items():
        if v is None:
            rec.pop(k, None)
        else:
            rec[k] = v
    FNAMES.write_text_atomic(manifest_path(),
                             json.dumps(data, indent=1, sort_keys=True))


def _store_lock():
    os.makedirs(store_dir(), exist_ok=True)
    return _FileLock(os.path.join(store_dir(), ".lock"))


def current_region(rid):
    """After rid's URL answered 404: the region as Geofabrik's index gives
    it now, fetching the index again unless it is younger than
    INDEX_RECHECK days; None when the index cannot be had or no longer has
    the region.

    The index is the one place that names every extract's URL; it was kept
    for INDEX_MAX_AGE (30) days, so a reorganisation of Geofabrik's folders
    (2026-11, #118) stayed broken for us until then wherever their
    redirects failed (#127). Following the index needs no guess about the
    new layout (#128)."""
    global _index_refresh_error
    path = index_path()
    if time.time() - os.path.getmtime(path) > INDEX_RECHECK * 86400:
        if _index_refresh_error:
            return None
        UI.vprint(1, f"    Fetching Geofabrik's index again (the URL of {rid} "
                  "is gone)")
        try:
            _download(INDEX_URL, path, md5=False, check=read_index)
        except (OSError, GeofabrikError) as e:
            _index_refresh_error = str(e)
            UI.vprint(1, f"    Could not fetch the index again ({e}).")
            return None
    return next((r for r in load_index(download=False) if r.id == rid), None)


def _fetch(region, path):
    """Download region's extract to path, following the index when its URL
    is gone (#128), and record it in the manifest."""
    url = region.url
    UI.vprint(1, f"    Downloading {url}")
    start = time.time()
    try:
        _download(url, path)
    except GeofabrikNotFound:
        new = current_region(region.id)
        if new is None or new.url == url:
            raise
        UI.lvprint(1, f"    Geofabrik: {url} is gone; the index now gives "
                   f"{new.url}.")
        url = new.url
        _download(url, path)
    UI.lvprint(1, f"    Geofabrik: downloaded {region.id} "
               f"({os.path.getsize(path) / 1e6:.0f} MB, "
               f"{time.time() - start:.0f} s).")
    _record(region.id, url=url, size=os.path.getsize(path),
            downloaded=_now(), update_failures=None, updated=None,
            checked=None, moved_from=None, broken=None)


def _looks_like_pbf(path):
    """The start of an .osm.pbf: a 4-byte big-endian BlobHeader size and
    the blob type "OSMHeader". Checked before pyosmium opens a file: when
    pyosmium fails on one, Windows keeps it open for the rest of the
    process, so it could no longer be set aside."""
    try:
        with open(path, "rb") as f:
            head = f.read(64)
    except OSError:
        return False
    n = int.from_bytes(head[:4], "big") if len(head) >= 8 else 0
    return 0 < n < 65536 and b"OSMHeader" in head[4:4 + min(n, 60)]


def _set_aside(rid, path, why):
    """A file that cannot be read: kept as <name>.broken (the last one
    only) for a look, out of the way of a new download."""
    broken = path + ".broken"
    UI.lvprint(1, f"   WARNING: Geofabrik extract {path} cannot be read "
               f"({why}); kept as {os.path.basename(broken)}, downloading it "
               "again.")
    try:
        os.replace(path, broken)
    except OSError as e:
        raise GeofabrikError(f"{path} cannot be read ({why}) nor set aside "
                             f"({e})")


def _header_server(path):
    """The replication server the file names, None without one."""
    import osmium
    reader = osmium.io.Reader(path, osmium.osm.osm_entity_bits.NOTHING)
    try:
        return reader.header().get("osmosis_replication_base_url") or None
    finally:
        reader.close()


def _bring_up_to_date(region, path, age):
    """Update (or download anew) region's extract whose data is age days
    old. The file stays usable as it is when this fails."""
    rid = region.id
    failures = read_manifest().get(rid, {}).get("update_failures", 0)
    if failures >= UPDATE_FAILURES_MAX or age > REFRESH_AGE:
        why = (f"its updates failed {failures} times in a row"
               if failures >= UPDATE_FAILURES_MAX
               else f"its data is {age:.0f} days old")
        _download_again(region, path, why)
        return
    UI.vprint(1, f"    Updating {rid} (data of {data_time(path):%Y-%m-%d %H:%M}"
              " UTC)")
    if _update(path):
        _record(rid, updated=_now(), checked=_now(), update_failures=None)
    elif region.updates and region.updates != _header_server(path):
        # The file names the update server Geofabrik gave when it was made
        # (older files: europe/norway-updates); the index names another
        # one today. A new download carries today's server. (Not pyosmium's
        # --server with --ignore-osmosis-headers: it finished the update,
        # then never exited, 2026-11-24.)
        _download_again(region, path, "its update server moved to "
                        f"{region.updates}")
    else:
        _failed_updates.add(rid)
        _record(rid, update_failures=failures + 1)
    UI.vprint(1, f"    {rid}: data of {data_time(path):%Y-%m-%d %H:%M} UTC")


def _download_again(region, path, why):
    """Replace region's extract by a new download; on failure the old file
    stays in use (no further try in this preparation)."""
    rid = region.id
    UI.lvprint(1, f"    Geofabrik: downloading {rid} again ({why}).")
    try:
        _fetch(region, path)
    except (GeofabrikError, OSError) as e:
        UI.lvprint(1, f"   WARNING: could not download {rid} again ({e}); "
                   "using the file as it is.")
        _failed_updates.add(rid)


def _recently_checked(rid):
    checked = read_manifest().get(rid, {}).get("checked")
    if not checked:
        return False
    try:
        t = datetime.datetime.strptime(checked, TIME_FORMAT).replace(
            tzinfo=datetime.timezone.utc)
    except (TypeError, ValueError):
        return False
    age = datetime.datetime.now(datetime.timezone.utc) - t
    return age.total_seconds() < UPDATE_RECHECK


def ensure_extract(region):
    """The local file of region's extract: downloaded if missing, updated
    if older than geofabrik_max_age days (or downloaded again, see
    _bring_up_to_date), set aside and downloaded again if it cannot be
    read. Locked against other processes."""
    rid = region.id
    path = extract_path(rid)
    with _store_lock():
        _remove_leftover_temps(path)
        age = None
        if os.path.isfile(path):
            marked = read_manifest().get(rid, {}).get("broken")
            if marked or not _looks_like_pbf(path):
                _set_aside(rid, path, marked or "not an .osm.pbf file")
            else:
                try:
                    age = _age_days(path)
                except (RuntimeError, ValueError) as e:
                    # pyosmium raises RuntimeError for a broken file; it
                    # used to escape prepare_tiles and end the preparation.
                    # The file stays open in this process (see
                    # _looks_like_pbf): set aside by the next preparation.
                    _record(rid, broken=str(e))
                    raise GeofabrikError(f"{path} cannot be read ({e}); it "
                                         "is set aside next time")
        if age is None:
            if rid in _failed_downloads:
                raise GeofabrikError(f"{_failed_downloads[rid]} (failed "
                                     "earlier in this run, not asked again)")
            try:
                _fetch(region, path)
            except (GeofabrikError, OSError) as e:
                _failed_downloads[rid] = str(e)
                raise
            return path
        if age > geofabrik_max_age and not _recently_checked(rid) \
                and rid not in _failed_updates:
            _bring_up_to_date(region, path, age)
    return path


def unused_extracts(regions):
    """[(file name, bytes)] of store files whose region the index no longer
    has (merged or renamed by Geofabrik): never read, for the user to
    delete."""
    known = {EXTRACT.store_name(r.id) for r in regions}
    try:
        names = os.listdir(store_dir())
    except OSError:
        return []
    return sorted((n, os.path.getsize(os.path.join(store_dir(), n)))
                  for n in names
                  if n.endswith(".osm.pbf") and n not in known)


def _old_layout_files():
    """.osm.pbf files below data_dir() outside the store (the layout before
    #129)."""
    out = []
    store = os.path.normcase(store_dir())
    for (root, dirs, files) in os.walk(data_dir()):
        if os.path.normcase(root) == store:
            dirs[:] = []
            continue
        out += [os.path.join(root, f) for f in files if f.endswith(".osm.pbf")]
    return out


def _plan_moves(regions, old_files):
    """([(old, new, region id)], [old files left]) of a migration."""
    by_old = {}
    for r in regions:
        for u in url_variants(r.url):
            by_old.setdefault(os.path.normcase(local_path(u)), r)
    (moves, left) = ([], [])
    for f in sorted(old_files):
        r = by_old.get(os.path.normcase(f))
        if r is None or os.path.exists(extract_path(r.id)) \
                or any(m[2] == r.id for m in moves):
            left.append(f)
            continue
        moves.append((f, extract_path(r.id), r.id))
    return (moves, left)


SIDE_SUFFIXES = (".lock", ".checked")


def _orphan_side_files():
    """.osm.pbf.lock / .osm.pbf.checked files of the old layout without
    their extract (a download that failed, 2026-11-21: papua's 404)."""
    out = []
    store = os.path.normcase(store_dir())
    for (root, dirs, files) in os.walk(data_dir()):
        if os.path.normcase(root) == store:
            dirs[:] = []
            continue
        names = set(files)
        out += [os.path.join(root, f) for f in files
                for suffix in SIDE_SUFFIXES
                if f.endswith(".osm.pbf" + suffix)
                and f[:-len(suffix)] not in names]
    return out


def migrate_store(regions, dry_run=False):
    """Move the extracts of the old layout (Geofabrik's URL paths, see
    local_path) into the store, named by region id: a rename on the same
    drive, nothing downloaded or deleted. Their .lock and .checked side
    files go (the store has one lock, the manifest keeps the check time),
    also those left without an extract. A file no region of the index
    matches, or whose region the store has already, stays where it is, as
    does one that cannot be moved (logged; the preparation goes on: an
    error here used to send every tile to Overpass). The moves are listed
    in extracts/moved_<time>.csv (undo_migration).

    Returns ([(old, new, region id)], [old files left])."""
    old_files = _old_layout_files()
    if not old_files and not _orphan_side_files():
        return ([], [])
    if dry_run:
        return _plan_moves(regions, old_files)
    urls = {r.id: r.url for r in regions}
    (moved, failed) = ([], [])
    folders = set()
    with _store_lock():
        # Planned under the lock: another process may have moved them.
        (moves, left) = _plan_moves(regions, _old_layout_files())
        log = None
        if moves:
            log = os.path.join(store_dir(), "moved_" + datetime.datetime.now()
                               .strftime("%Y%m%d_%H%M%S") + ".csv")
            with open(log, "w", encoding="utf-8", newline="") as f:
                out = csv.writer(f)
                out.writerow(("old", "new", "region"))
                for (old, new, rid) in moves:
                    checked = old + ".checked"
                    try:
                        check_time = (datetime.datetime.fromtimestamp(
                            os.path.getmtime(checked), datetime.timezone.utc)
                            .strftime(TIME_FORMAT)
                            if os.path.isfile(checked) else None)
                        os.replace(old, new)
                    except OSError as e:
                        failed.append(f"{os.path.relpath(old, data_dir())} "
                                      f"({e})")
                        left.append(old)
                        continue
                    out.writerow((old, new, rid))
                    f.flush()
                    moved.append((old, new, rid))
                    folders.add(os.path.dirname(old))
                    _record(rid, url=urls[rid], size=os.path.getsize(new),
                            moved_from=old, checked=check_time)
                    for side in (checked, old + ".lock"):
                        _remove_side_file(side)
        for side in _orphan_side_files():
            _remove_side_file(side)
            folders.add(os.path.dirname(side))
    _remove_empty_dirs(folders)
    if moved:
        UI.lvprint(1, f"    Geofabrik: moved {len(moved)} extract(s) into "
                   f"{store_dir()} (named by region id); list in "
                   f"{os.path.basename(log)}.")
    if failed:
        UI.lvprint(1, "   WARNING: Geofabrik: could not move into the store: "
                   + "; ".join(failed) + ". Tried again next time.")
    unmatched = [f for f in left if f not in {m[0] for m in moves}]
    if unmatched:
        UI.lvprint(1, f"    Geofabrik: {len(unmatched)} extract(s) of the old "
                   "layout match no region of the index (or a region the "
                   "store has) and stay where they are: "
                   + ", ".join(os.path.relpath(f, data_dir())
                               for f in unmatched))
    return (moved, left)


def _remove_side_file(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError as e:
        UI.vprint(1, f"    Could not remove {path} ({e}).")


def _remove_empty_dirs(folders):
    """Remove the given folders of the old layout and their parents while
    they are empty, up to (not including) data_dir(); other folders the
    user keeps there are left alone."""
    top = os.path.normcase(os.path.abspath(data_dir()))
    keep = {top, os.path.normcase(os.path.abspath(store_dir()))}
    for folder in sorted(folders, key=len, reverse=True):
        d = os.path.abspath(folder)
        while os.path.normcase(d) not in keep \
                and os.path.normcase(d).startswith(top + os.sep):
            try:
                os.rmdir(d)  # only an empty folder
            except OSError:
                break
            d = os.path.dirname(d)


def undo_migration(csv_path):
    """Move the files listed in a moved_<time>.csv back to the old layout
    (where the old place is free) and drop their manifest records. Returns
    the number moved back."""
    n = 0
    with _store_lock():
        with open(csv_path, encoding="utf-8", newline="") as f:
            rows = list(csv.reader(f))[1:]
        for row in rows:
            if len(row) != 3:
                continue
            (old, new, rid) = row
            if os.path.isfile(new) and not os.path.exists(old):
                os.makedirs(os.path.dirname(old), exist_ok=True)
                os.replace(new, old)
                _record(rid, **{k: None for k in read_manifest().get(rid, {})})
                n += 1
        data = read_manifest()
        empty = [rid for (rid, rec) in data.items() if not rec]
        if empty:
            for rid in empty:
                del data[rid]
            FNAMES.write_text_atomic(
                manifest_path(), json.dumps(data, indent=1, sort_keys=True))
    return n


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
def cache_is_stale(path, now=None):
    """A cached layer older than osm_cache_max_age days (file time: the
    cache is written when its data is fetched)."""
    if osm_cache_max_age <= 0:
        return False
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return False
    return ((now or time.time()) - mtime) / 86400 > osm_cache_max_age


def needed_layers(lat, lon, road_level, force=False):
    """{layer: statements} of the layers step 1 would otherwise ask
    Overpass for or take from a stale cache: no extract answer for these
    statements, not cached, cached longer than osm_cache_max_age or for
    other statements (road_level changed, #107), no custom coastline/water
    file."""
    layers = EXTRACT.layer_statements(road_level)
    if os.path.isfile(FNAMES.custom_coastline(lat, lon)) or \
            os.path.isdir(FNAMES.custom_coastline_dir(lat, lon)):
        layers.pop("coastline")
    if os.path.isfile(FNAMES.custom_water(lat, lon)) or \
            os.path.isdir(FNAMES.custom_water_dir(lat, lon)):
        layers.pop("water")
    if force:
        return layers
    wanted = {}
    for (layer, st) in layers.items():
        answer = EXTRACT.answer_path(lat, lon, layer)
        if os.path.isfile(answer) and EXTRACT.answer_fits(answer, st):
            continue
        cache = FNAMES.osm_cached(lat, lon, layer)
        if not os.path.isfile(cache) or cache_is_stale(cache) or \
                EXTRACT.cache_fits(cache, st) is False:
            wanted[layer] = st
    return wanted


def _cached(lat, lon, layer):
    return os.path.isfile(FNAMES.osm_cached(lat, lon, layer))


def _sea_answers(layers):
    """Empty answers for a tile outside every Geofabrik region."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return {layer: EXTRACT.answer_xml(
        st, "no Geofabrik region (open sea)",
        now.strftime("%Y-%m-%dT%H:%M:%SZ"), {}, {}, {})
        for (layer, st) in layers.items()}


def plan_tiles(wanted, regions):
    """({tile: frozenset(region ids)}, {tile: reason left to Overpass}, [sea
    tiles]) for wanted {tile: layers}."""
    (plan, left, sea) = ({}, {}, [])
    for (lat, lon) in wanted:
        (chosen, kind) = choose_regions(lat, lon, regions)
        if kind == "sea":
            sea.append((lat, lon))
            continue
        if kind == "continent":
            from shapely import geometry
            box = geometry.box(lon, lat, lon + 1, lat + 1)
            extra = [r for r in regions if r.id in EXTRACT.CONTINENTS
                     and r.area.intersects(box)]
            what = "only in"
        else:
            extra = gap_continents(lat, lon, regions)
            what = "land outside the country extracts, only in"
        # A continent file is tens of GB: read only one already on disk
        # (put there by hand, e.g. central-america for the Caribbean).
        if extra and not _on_disk(extra):
            left[(lat, lon)] = (f"{what} "
                                + ", ".join(sorted(r.id for r in extra))
                                + " (not downloaded)")
            continue
        if extra and kind == "land":
            UI.vprint(1, f"    Geofabrik: {FNAMES.short_latlon(lat, lon)} "
                      "has land only in " + ", ".join(r.id for r in extra)
                      + ", read as well.")
        plan[(lat, lon)] = frozenset(r.id for r in chosen + extra)
    return (plan, left, sea)


def prepare_tiles(wanted, write=True):
    """Prepare answers for wanted {(lat, lon): {layer: statements}}.

    Returns ({tile: {layer: answer}}, {tile: reason} of the tiles left to
    Overpass). With write, the answers are stored where step 1 reads them
    as soon as their group is read, and answer is the answer's size in
    bytes (a batch's answers would not fit in memory together); without,
    answer is the content. Raises Stopped on Stop, GeofabrikError when
    the index cannot be had.
    """
    if not wanted:
        return ({}, {})
    # A new preparation (the next batch or build) may try failed files again.
    _failed_downloads.clear()
    _failed_updates.clear()
    global _index_refresh_error
    _index_refresh_error = None
    regions = load_index()
    migrate_store(regions)
    by_id = {r.id: r for r in regions}
    (plan, left, sea) = plan_tiles(wanted, regions)
    done = {}

    def keep(answers):
        for ((lat, lon), layers) in answers.items():
            if write:
                for (layer, content) in layers.items():
                    EXTRACT.write_answer(EXTRACT.answer_path(lat, lon, layer),
                                         content)
                layers = {layer: len(c) for (layer, c) in layers.items()}
            done[(lat, lon)] = layers

    # A refresh never replaces a cache with an empty sea answer: the
    # cache may hold an islet outside every region (Overpass had it).
    keep({tile: _sea_answers({layer: st
                              for (layer, st) in wanted[tile].items()
                              if not _cached(*tile, layer)})
          for tile in sea})
    for (urls, tiles) in group_tiles(plan):
        # A file that cannot be had fails only the tiles that need it: a
        # merged group used to send all its tiles to Overpass (batch C,
        # 2026-11-20: alsace and jihocesky failed 18 of 20 tiles, #118).
        (paths, missing) = ({}, {})
        for u in sorted(urls):
            try:
                paths[u] = ensure_extract(by_id[u])
            except (GeofabrikError, OSError) as e:
                missing[u] = e
        for tile in [t for t in tiles if plan[t] & missing.keys()]:
            u = min(plan[tile] & missing.keys())
            left[tile] = f"no extract file ({missing[u]})"
            tiles.remove(tile)
        if not tiles:
            continue
        needed = sorted(set().union(*(plan[t] for t in tiles)))
        files = [paths[u] for u in needed]
        names = ", ".join(needed)
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
        keep(answers)
        del answers
        left.update(failed)
    return (done, left)


def _report(done, left, wanted):
    done = [t for (t, layers) in done.items() if layers]
    if done:
        UI.lvprint(1, "    Geofabrik: OSM data prepared for "
                   + " ".join(FNAMES.short_latlon(*t) for t in sorted(done)))
    for (tile, reason) in sorted(left.items()):
        name = FNAMES.short_latlon(*tile)
        if all(_cached(*tile, layer) for layer in wanted.get(tile, ())):
            # Only stale caches were asked for: they stay in use.
            UI.lvprint(1, f"    Geofabrik: OSM data of {name} not "
                       f"refreshed ({reason}); its cached layers are used.")
        else:
            UI.lvprint(1, f"    Geofabrik: no local OSM data for {name} "
                       f"({reason}); Overpass will be asked.")


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
        wanted = {(tile.lat, tile.lon): wanted}
        _report(*prepare_tiles(wanted), wanted)
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
        _report(*prepare_tiles(wanted), wanted)
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
        osm_layer.write_to_file(tmp, statements)
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
