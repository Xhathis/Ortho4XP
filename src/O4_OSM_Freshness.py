"""Has OSM changed since a tile's cached layers were downloaded?

A build reuses OSM_data/<tile>/<tile>_<layer>.osm.bz2 forever. The cache
keeps no OSM ids, versions or dates (update_dicosm renumbers everything),
so the only date it has is the file's modification time, written right
after the download.

For each cached layer one Overpass request asks, over the tile's bbox and
with the layer's own queries:
  1. how many elements match now (out count), and
  2. how many of them, or of the ways and nodes they pull in, were created
     or edited after the download (newer:).
A layer is unchanged when (2) is 0 and (1) equals the count of matching
elements in the cache file. The count catches what newer: cannot: a deleted
way, or a way that lost the queried tag (it no longer matches, so the set
shrinks). This costs about as much server time as downloading the layer
again, but the answer is a few hundred bytes and says which tiles are worth
rebuilding.

Pure functions here; check_osm_cache.py does the requests.
"""

import bz2
import os
import re
import time

import O4_File_Names as FNAMES
import O4_Vector_Map as VMAP

# In the order a build reads them.
LAYERS = ("coastline", "airports", "big_roads", "small_roads", "water")

# A download's data is a little older than the cache file (osm_base lags
# the live database, and the file is written after the download). Anything
# edited within this margin before the file was written counts as newer:
# a false "changed" is harmless, a missed edit is not.
DEFAULT_MARGIN = 3600

_STATEMENT = re.compile(r'^(node|way|rel)\["([^"]+)"(?:="([^"]*)")?\]$')
_TYPE = {"node": "n", "way": "w", "rel": "r"}
_ELEMENT = re.compile(r'^\s*<(node|way|relation) id=')
_TAG = re.compile(r'<tag k="([^"]*)" v="([^"]*)"')
_TYPE_OF_ELEMENT = {"node": "n", "way": "w", "relation": "r"}


def cached_layers(lat, lon):
    """[(layer, path)] of the tile's cached layers, in LAYERS order."""
    return [
        (layer, FNAMES.osm_cached(lat, lon, layer))
        for layer in LAYERS
        if os.path.isfile(FNAMES.osm_cached(lat, lon, layer))
    ]


def cached_tiles():
    """(lat, lon) of every tile folder in OSM_data with a cached layer."""
    tiles = []
    if not os.path.isdir(FNAMES.OSM_dir):
        return tiles
    for group in sorted(os.listdir(FNAMES.OSM_dir)):
        group_dir = os.path.join(FNAMES.OSM_dir, group)
        if not os.path.isdir(group_dir):
            continue
        for name in sorted(os.listdir(group_dir)):
            tile = parse_tile(name)
            if tile and cached_layers(*tile):
                tiles.append(tile)
    return tiles


def parse_tile(text):
    """(lat, lon) from "+55+012" (or "55,12"), None if it is not a tile."""
    m = re.fullmatch(r"([+-]\d{1,2})([+-]\d{1,3})", text.strip())
    if not m:
        m = re.fullmatch(r"\s*(-?\d{1,2})\s*[, ]\s*(-?\d{1,3})\s*", text)
    if not m:
        return None
    lat, lon = int(m.group(1)), int(m.group(2))
    if not (-90 <= lat < 90 and -180 <= lon < 180):
        return None
    return (lat, lon)


def read_config_value(config_file, wanted):
    """A setting's text from an Ortho4XP config file, None if absent.

    Read directly instead of through O4_Config_Utils, which would load the
    whole global config into every module (and create one if missing).
    """
    try:
        with open(config_file, encoding="utf-8", errors="replace") as f:
            for line in f:
                key, _, value = line.partition("=")
                if key.strip() == wanted:
                    return value.strip()
    except OSError:
        return None
    return None


def read_road_level(config_file):
    """road_level from an Ortho4XP config file, None if absent or bad."""
    value = read_config_value(config_file, "road_level")
    try:
        return int(float(value)) if value is not None else None
    except ValueError:
        return None


def tile_road_level(lat, lon, global_config="Ortho4XP.cfg", build_dir=""):
    """The road_level a rebuild of the tile would use.

    The tile's own config wins over the global one, as in a build.
    """
    tile_config = os.path.join(
        FNAMES.build_dir(lat, lon, build_dir),
        "Ortho4XP_" + FNAMES.short_latlon(lat, lon) + ".cfg",
    )
    level = read_road_level(tile_config)
    if level is None:
        level = read_road_level(global_config)
    return level


def layer_statements(layer, road_level):
    """The Overpass statements (without bbox) a build uses for the layer."""
    queries = {
        "coastline": VMAP.COASTLINE_QUERIES,
        "airports": VMAP.AIRPORT_QUERIES,
        "big_roads": VMAP.BIG_ROAD_QUERIES,
        "small_roads": VMAP.small_road_queries(road_level or 2),
        "water": VMAP.WATER_QUERIES,
    }[layer]
    return [s for q in queries for s in ([q] if isinstance(q, str) else q)]


def parse_statement(statement):
    """('w', key, value) for 'way["key"="value"]'; value None for a key only."""
    m = _STATEMENT.match(statement)
    if not m:
        raise ValueError("unsupported statement: " + statement)
    return (_TYPE[m.group(1)], m.group(2), m.group(3))


def _matches(osm_type, tags, criteria):
    for (t, key, value) in criteria:
        if t == osm_type and key in tags and (value is None or tags[key] == value):
            return True
    return False


def cache_counts(path, statements):
    """Count the cached elements that match the statements.

    Returns ({"n": .., "w": .., "r": ..}, set of highway values seen), the
    latter for road_level_gaps. Only elements carrying a queried tag count:
    relation member ways and way nodes come along untagged.
    """
    criteria = [parse_statement(s) for s in statements]
    counts = {"n": 0, "w": 0, "r": 0}
    highways = set()
    osm_type, tags = None, {}

    def close():
        if osm_type and _matches(osm_type, tags, criteria):
            counts[osm_type] += 1
            if osm_type == "w" and "highway" in tags:
                highways.add(tags["highway"])

    with bz2.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            m = _ELEMENT.match(line)
            if m:
                close()
                osm_type, tags = _TYPE_OF_ELEMENT[m.group(1)], {}
                continue
            m = _TAG.search(line)
            if m and osm_type:
                tags[m.group(1)] = m.group(2)
        close()
    return counts, highways


def road_level_gaps(road_level, highways):
    """Highway values road_level asks for that the small_roads cache lacks.

    The cache file has the same name at every road_level, so a tile cached
    at a lower level is rebuilt from it without the extra road types. A
    whole degree of land with no service road at all is not plausible, so
    a missing type means the cache predates the level. (tertiary is in
    every level >= 2 and says nothing.)
    """
    wanted = []
    if (road_level or 0) >= 3:
        wanted += ["unclassified", "residential"]
    if (road_level or 0) >= 4:
        wanted.append("service")
    if (road_level or 0) >= 5:
        wanted.append("track")
    return [h for h in wanted if h not in highways]


def since_date(path, margin=DEFAULT_MARGIN):
    """UTC date for newer:, margin seconds before the file was written."""
    return time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(os.path.getmtime(path) - margin)
    )


def count_query(statements, bbox, since, server_timeout=300):
    """Overpass QL giving two counts: matches now, then edited since."""
    union = "".join(s + str(bbox) + ";" for s in statements)
    return (
        f"[out:xml][timeout:{server_timeout}];"
        f"({union})->.m;"
        ".m out count;"
        "(.m;>>;)->.a;"
        f'nwr.a(newer:"{since}");'
        "out count;"
    )


_COUNT = re.compile(r'<count id="[^"]*">(.*?)</count>', re.S)
_COUNT_TAG = re.compile(r'<tag k="(nodes|ways|relations)" v="(\d+)"/>')
_OSM_BASE = re.compile(r'<meta osm_base="([^"]+)"')
_REMARK = re.compile(r"<remark>(.*?)</remark>", re.S)


def parse_count_answer(content):
    """(osm_base, now, newer) from a count_query answer.

    now and newer are {"n", "w", "r"} dicts. Raises ValueError on anything
    else: Overpass reports a timeout or memory error with HTTP 200 and a
    <remark>, so a missing count must not read as zero.
    """
    text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content
    remark = _REMARK.search(text)
    if remark:
        raise ValueError("server remark: " + " ".join(remark.group(1).split()))
    if "</osm>" not in text[-20:]:
        raise ValueError("cut answer (no closing </osm>)")
    blocks = _COUNT.findall(text)
    if len(blocks) != 2:
        raise ValueError(f"{len(blocks)} count blocks instead of 2")
    result = []
    for block in blocks:
        values = dict(_COUNT_TAG.findall(block))
        if len(values) != 3:
            raise ValueError("incomplete count block")
        result.append({
            "n": int(values["nodes"]),
            "w": int(values["ways"]),
            "r": int(values["relations"]),
        })
    base = _OSM_BASE.search(text)
    return (base.group(1) if base else "", result[0], result[1])


def layer_verdict(cached, now, newer):
    """(changed, text) for one layer, from cache_counts and the answer."""
    edited = newer["n"] + newer["w"] + newer["r"]
    parts = []
    if edited:
        parts.append(
            f"{edited} edited/new (nodes {newer['n']}, ways {newer['w']}, "
            f"relations {newer['r']})"
        )
    for t, name in (("n", "nodes"), ("w", "ways"), ("r", "relations")):
        if now[t] != cached[t]:
            parts.append(f"{name} {cached[t]} -> {now[t]}")
    if not parts:
        return (False, "unchanged")
    return (True, "; ".join(parts))
