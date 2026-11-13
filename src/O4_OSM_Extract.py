"""OSM layers from local extracts (Geofabrik .osm.pbf) instead of Overpass.

prepare_osm_extracts.py reads one or more .osm.pbf files and writes, for
each tile and OSM layer, the answer Overpass would give to that layer's
queries: OSM_data/<10x10>/<tile>/<tile>_<layer>.extract.osm.bz2. A build
that finds no cached layer reads such an answer instead of asking Overpass
(OSM_Utils.OSM_queries_to_OSM_layer), through the same reader and cache
writer as a download, so the cache file is as from Overpass.

The answer follows Overpass's rules for "<query>(bbox);(._;>>;);out;":
- a node is in the tile when it lies inside it (edges included);
- a way when one of its segments touches the tile (a long segment crossing
  a corner counts, as in Overpass, even without a node inside);
- a relation when one of its member nodes or ways is in the tile;
- then everything is completed downwards: all nodes of the ways, all member
  ways and nodes of the relations, also far outside the tile. A sub-relation
  member is listed but not output (the reader only uses ways).
Objects are written sorted by id per type, as Overpass does, with its XML
escaping. Node tags are written only for layers that query nodes
(airports): the reader drops node tags for the others.

Nothing is cut silently: a tile whose answer would lack a node or a member
way (outside the given files) fails with the reason, and no answer is
written for it; the tool also refuses a tile that reaches into a Geofabrik
region whose file is not given (coverage_gaps; open sea outside all regions
needs none).

pyosmium is imported only by the extraction (the build only reads answers).
"""
import bz2
import html
import os
import re

import O4_File_Names as FNAMES

GENERATOR = "Ortho4XP extract"
SCALE = 10_000_000  # osmium's fixed-point coordinates: 1e-7 degree
_STMT = re.compile(r'^(node|way|rel)\["([^"]+)"(?:="([^"]*)")?\]$')
_HEADER = re.compile(rb'<o4xp_extract statements="([^"]*)" source="([^"]*)"/>')


# --- statements ---------------------------------------------------------------
def parse_statement(statement):
    """'way["highway"="motorway"]' -> ("w", "highway", "motorway");
    'node["aeroway"]' -> ("n", "aeroway", None). Only these simple forms
    are used by Ortho4XP's layers; anything else raises ValueError."""
    m = _STMT.match(statement)
    if not m:
        raise ValueError(f"unsupported Overpass statement: {statement}")
    return ({"node": "n", "way": "w", "rel": "r"}[m.group(1)],
            m.group(2), m.group(3))


def flat_statements(queries):
    """The statements of a layer's queries (a query is a str or a tuple of
    them), as OSM_queries_to_OSM_layer sends them."""
    return tuple(t for q in queries for t in ([q] if isinstance(q, str) else q))


def layer_statements(road_level):
    """{layer: statements} of the 5 cached layers at this road_level, from
    the build's own query constants (Vector_Map), so both never differ."""
    import O4_Vector_Map as VMAP
    layers = {
        "coastline": flat_statements(VMAP.COASTLINE_QUERIES),
        "airports": flat_statements(VMAP.AIRPORT_QUERIES),
        "water": flat_statements(VMAP.WATER_QUERIES),
    }
    if road_level >= 1:
        layers["big_roads"] = flat_statements(VMAP.BIG_ROAD_QUERIES)
    if road_level >= 2:
        layers["small_roads"] = flat_statements(
            VMAP.small_road_queries(road_level))
    return layers


# --- geometry -----------------------------------------------------------------
def tile_of(lat, lon):
    return FNAMES.short_latlon(lat, lon)


def _floor(v):
    return v // SCALE  # Python floors negative values too


def point_tiles(x, y, wanted):
    """Tiles (lat, lon) in wanted whose closed square holds (x, y)."""
    lons = {_floor(x)} | ({_floor(x) - 1} if x % SCALE == 0 else set())
    lats = {_floor(y)} | ({_floor(y) - 1} if y % SCALE == 0 else set())
    return {(la, lo) for la in lats for lo in lons if (la, lo) in wanted}


def _segment_touches(x1, y1, x2, y2, lat, lon):
    """Liang-Barsky: does the segment touch the closed tile square?"""
    (xmin, ymin) = (lon * SCALE, lat * SCALE)
    (xmax, ymax) = (xmin + SCALE, ymin + SCALE)
    (t0, t1) = (0.0, 1.0)
    (dx, dy) = (x2 - x1, y2 - y1)
    for (p, q) in ((-dx, x1 - xmin), (dx, xmax - x1),
                   (-dy, y1 - ymin), (dy, ymax - y1)):
        if p == 0:
            if q < 0:
                return False
        else:
            t = q / p
            if p < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
            if t0 > t1:
                return False
    return True


def way_tiles(xs, ys, wanted):
    """Tiles in wanted that a way (node coordinates xs, ys) touches."""
    if not xs:
        return set()
    (lo0, lo1) = (_floor(min(xs)) - 1, _floor(max(xs)))
    (la0, la1) = (_floor(min(ys)) - 1, _floor(max(ys)))
    candidates = [(la, lo) for (la, lo) in wanted
                  if la0 <= la <= la1 and lo0 <= lo <= lo1]
    found = set()
    for (la, lo) in candidates:
        if len(xs) == 1:
            if (la, lo) in point_tiles(xs[0], ys[0], {(la, lo)}):
                found.add((la, lo))
            continue
        for i in range(len(xs) - 1):
            if _segment_touches(xs[i], ys[i], xs[i + 1], ys[i + 1], la, lo):
                found.add((la, lo))
                break
    return found


def read_index(path):
    """Geofabrik's index-v1.json: [(id, pbf file name, area)]."""
    import json
    from shapely import geometry
    with open(path, encoding="utf-8") as f:
        index = json.load(f)
    regions = []
    for feature in index["features"]:
        props = feature.get("properties", {})
        pbf = props.get("urls", {}).get("pbf", "")
        if feature.get("geometry") and pbf:
            regions.append((props["id"], pbf.rsplit("/", 1)[-1],
                            geometry.shape(feature["geometry"])))
    return regions


MIN_GAP = 1e-6  # square degrees (~0.01 km2): slivers along shared borders


def coverage_gaps(tiles, given, regions):
    """{tile: [region ids that would fill it]} for tiles where some area
    of a Geofabrik region lies outside the given files' areas. Open sea
    outside every region holds no OSM data, so it needs no file: a coastal
    tile is covered when its land and coast are. given: areas of the files
    used; regions: read_index()."""
    from shapely import geometry, ops
    have = ops.unary_union(given)
    gaps = {}
    for (la, lo) in tiles:
        box = geometry.box(lo, la, lo + 1, la + 1)
        near = [(rid, area) for (rid, _, area) in regions
                if area.intersects(box)]
        missing = box.intersection(
            ops.unary_union([a for (_, a) in near])).difference(have)
        if missing.area > MIN_GAP:
            fill = [(area.area, rid) for (rid, area) in near
                    if area.intersection(missing).area > MIN_GAP]
            gaps[(la, lo)] = [rid for (_, rid) in sorted(fill)]
    return gaps


# Geofabrik's continents reach far out to sea (africa covers the Atlantic
# around the Canaries); a country file's boundary keeps a few km of sea.
# Russia is top-level too, but it is a country (land), so not listed.
CONTINENTS = {"africa", "antarctica", "asia", "australia-oceania",
              "central-america", "europe", "north-america", "south-america"}


def offshore_only(fill):
    """True when only continents fill a tile's gap: the gap is sea beyond
    every country file (only offshore objects such as platforms can be
    missing). The tool still refuses such a tile when the given files have
    nothing in it at all (its land would be in the gap, e.g. Diego Garcia,
    in no country file)."""
    return bool(fill) and set(fill) <= CONTINENTS


def has_objects(answers):
    """True if any answer of a tile holds a node."""
    return any(b"<node id=" in content for content in answers.values())


# --- XML as Overpass writes it ----------------------------------------------
def xml_escape(s):
    """Overpass's escaping: & " < > and control characters (&#x0a;)."""
    out = []
    for c in s:
        if c == "&":
            out.append("&amp;")
        elif c == '"':
            out.append("&quot;")
        elif c == "<":
            out.append("&lt;")
        elif c == ">":
            out.append("&gt;")
        elif ord(c) < 32:
            out.append(f"&#x{ord(c):02x};")
        else:
            out.append(c)
    return "".join(out)


def coord(v):
    """A fixed-point coordinate as Overpass prints it (7 decimals)."""
    sign = "-" if v < 0 else ""
    (whole, frac) = divmod(abs(v), SCALE)
    return f"{sign}{whole}.{frac:07d}"


_MEMBER_TYPE = {"n": "node", "w": "way", "r": "relation"}


def answer_xml(statements, source, osm_base, nodes, ways, rels):
    """The answer as bytes. nodes: {id: (x, y, tags or None)}; ways: {id:
    (refs, tags)}; rels: {id: (members [(type, ref, role)], tags)}; tags are
    lists of (k, v)."""
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           f'<osm version="0.6" generator="{GENERATOR}">',
           f'<meta osm_base="{xml_escape(osm_base)}"/>',
           '<o4xp_extract statements="'
           + xml_escape("\n".join(statements)) + '" source="'
           + xml_escape(source) + '"/>']

    def tag_lines(tags):
        return [f'    <tag k="{xml_escape(k)}" v="{xml_escape(v)}"/>'
                for (k, v) in tags]

    for nid in sorted(nodes):
        (x, y, tags) = nodes[nid]
        head = f'  <node id="{nid}" lat="{coord(y)}" lon="{coord(x)}"'
        if tags:
            out += [head + ">"] + tag_lines(tags) + ["  </node>"]
        else:
            out.append(head + "/>")
    for wid in sorted(ways):
        (refs, tags) = ways[wid]
        out.append(f'  <way id="{wid}">')
        out += [f'    <nd ref="{r}"/>' for r in refs]
        out += tag_lines(tags) + ["  </way>"]
    for rid in sorted(rels):
        (members, tags) = rels[rid]
        out.append(f'  <relation id="{rid}">')
        out += [f'    <member type="{_MEMBER_TYPE[t]}" ref="{r}" '
                f'role="{xml_escape(role)}"/>' for (t, r, role) in members]
        out += tag_lines(tags) + ["  </relation>"]
    out.append("</osm>")
    return ("\n".join(out) + "\n").encode("utf-8")


# --- answers on disk -----------------------------------------------------------
def answer_path(lat, lon, layer):
    return os.path.join(
        FNAMES.OSM_dir, FNAMES.long_latlon(lat, lon),
        FNAMES.short_latlon(lat, lon) + "_" + layer + ".extract.osm.bz2")


def write_answer(path, content):
    """bz2, under a temp name, then os.replace: never a half answer."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = FNAMES.temp_path_for(path)
    try:
        with bz2.open(tmp, "wb") as f:
            f.write(content)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def read_answer(path, statements):
    """(content, source) of a stored answer for these statements, or
    (None, reason). reason "" means there is none."""
    if not os.path.isfile(path):
        return (None, "")
    try:
        with bz2.open(path, "rb") as f:
            content = f.read()
    except (OSError, EOFError, ValueError) as e:
        return (None, f"unreadable ({type(e).__name__}: {e})")
    m = _HEADER.search(content[:4000])
    if not m or not content.rstrip().endswith(b"</osm>"):
        return (None, "not a complete extract answer")
    stored = html.unescape(m.group(1).decode("utf-8")).split("\n")
    if sorted(stored) != sorted(statements):
        return (None, "made for other queries (road_level changed?)")
    return (content, html.unescape(m.group(2).decode("utf-8")))


# --- extraction -------------------------------------------------------------------
class ExtractError(Exception):
    pass


def _osm_base(files):
    """Data date of the files: the oldest replication timestamp (Geofabrik
    sets it), else the oldest file time."""
    import datetime
    import osmium
    dates = []
    for f in files:
        ts = osmium.io.Reader(f, osmium.osm.osm_entity_bits.NOTHING).header() \
            .get("osmosis_replication_timestamp")
        if not ts:
            ts = datetime.datetime.fromtimestamp(
                os.path.getmtime(f), datetime.timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
        dates.append(ts)
    return min(dates)


def _run(files, *handlers, locations=False):
    """Apply the handlers (filters first) to each file in turn.

    One file at a time: pyosmium's MergeInputReader keeps every object of
    every file in memory (42 GB for norway + sweden + finland). An object
    in two neighbouring extracts is simply seen twice; the collections are
    keyed by id. Geofabrik ships every node of the ways in a file, so each
    file's own location index is enough. sparse_mem_array: 16 bytes per
    node of the file (flex_mem may switch to a dense array sized by the
    highest node id, ~100 GB today).
    """
    import osmium
    for f in files:
        chain = list(handlers)
        if locations:
            lh = osmium.NodeLocationsForWays(
                osmium.index.create_map("sparse_mem_array"))
            lh.ignore_errors()  # a missing node: an invalid location
            chain.insert(0, lh)
        reader = osmium.io.Reader(f)
        try:
            osmium.apply(reader, *chain)
        finally:
            reader.close()


def extract_answers(files, wanted, log=print):
    """Answers for wanted = {(lat, lon): {layer: statements}} from the .pbf
    (or .osm) files, read as one. Returns ({(lat, lon): {layer: bytes}},
    {(lat, lon): reason}) - a tile is either complete or in the second.
    """
    import osmium

    tiles = set(wanted)
    osm_base = _osm_base(files)
    source = ", ".join(os.path.basename(f) for f in files)
    # Statement index: type -> key -> value (None: any) -> {(tile, layer)}
    index = {"n": {}, "w": {}, "r": {}}
    for (tile, layers) in wanted.items():
        for (layer, statements) in layers.items():
            for st in statements:
                (t, k, v) = parse_statement(st)
                index[t].setdefault(k, {}).setdefault(v, set()).add(
                    (tile, layer))

    def matches(otype, tags):
        hit = set()
        keyed = index[otype]
        for (k, v) in tags:
            if k in keyed:
                hit |= keyed[k].get(None, set()) | keyed[k].get(v, set())
        return hit

    keys = sorted({k for t in index.values() for k in t})
    # Layers that query nodes: only their answers carry node tags.
    node_layers = {tl for by_value in index["n"].values()
                   for tls in by_value.values() for tl in tls}
    take = {}  # (tile, layer) -> {"n": set, "w": set, "r": set}

    def add(tile_layers, tiles_hit, otype, oid):
        for (tile, layer) in tile_layers:
            if tile in tiles_hit:
                take.setdefault((tile, layer), {"n": set(), "w": set(),
                                                "r": set()})[otype].add(oid)

    # Each pass puts a C++ filter in front of Python: of the hundreds of
    # millions of objects in a country file only the matching ones reach a
    # callback; the location index (idx) is filled in C++ for every node.
    def geometry(w):
        (refs, xs, ys, ok) = ([], [], [], True)
        for n in w.nodes:
            refs.append(n.ref)
            if n.location.valid():
                xs.append(n.x)
                ys.append(n.y)
            else:
                ok = False
        return (refs, xs, ys, ok)

    # Pass 1: relations matching a statement.
    rels = {}  # id -> (members, tags, (tile, layer)s)

    class Rels(osmium.SimpleHandler):
        def relation(self, r):
            tags = [(t.k, t.v) for t in r.tags]
            hit = matches("r", tags)
            if hit:
                rels[r.id] = ([(m.type, m.ref, m.role) for m in r.members],
                              tags, hit)

    log("    pass 1: relations")
    _run(files, osmium.filter.KeyFilter(*keys), Rels())
    member_ways = {ref for (mem, _, _) in rels.values()
                   for (t, ref, _) in mem if t == "w"}
    member_nodes = {ref for (mem, _, _) in rels.values()
                    for (t, ref, _) in mem if t == "n"}

    node_xy = {}  # id -> (x, y) of nodes output by themselves
    member_tiles = {}  # ("w"|"n", id) -> tiles it touches
    way_data = {}  # id -> (refs, xs, ys, tags)
    broken = {}  # way id -> tiles it touches (some node without location)

    def keep_way(w, hit, is_member):
        (refs, xs, ys, ok) = geometry(w)
        hit_tiles = way_tiles(xs, ys, tiles)
        if is_member:
            member_tiles[("w", w.id)] = hit_tiles
        if not hit_tiles:
            return
        if not ok:
            broken[w.id] = hit_tiles
        if w.id not in way_data:
            way_data[w.id] = (refs, xs, ys, [(t.k, t.v) for t in w.tags])
        add(hit, hit_tiles, "w", w.id)

    # Pass 2: ways matching a statement.
    class Ways(osmium.SimpleHandler):
        def way(self, w):
            hit = matches("w", [(t.k, t.v) for t in w.tags])
            if hit:
                keep_way(w, hit, w.id in member_ways)

    log("    pass 2: ways")
    _run(files, osmium.filter.KeyFilter(*keys), Ways(), locations=True)

    # Pass 3: member ways of the relations (mostly untagged).
    class MemberWays(osmium.SimpleHandler):
        def way(self, w):
            if ("w", w.id) not in member_tiles:
                keep_way(w, set(), True)

    if member_ways:
        log(f"    pass 3: {len(member_ways)} relation member ways")
        _run(files, osmium.filter.IdFilter(member_ways), MemberWays(),
             locations=True)

    # Pass 4: nodes matching a statement, and relation member nodes.
    class Nodes(osmium.SimpleHandler):
        def node(self, n):
            hit = matches("n", [(t.k, t.v) for t in n.tags])
            if hit:
                hit_tiles = point_tiles(n.location.x, n.location.y, tiles)
                if hit_tiles:
                    node_xy[n.id] = (n.location.x, n.location.y)
                    add(hit, hit_tiles, "n", n.id)

    class MemberNodes(osmium.SimpleHandler):
        def node(self, n):
            node_xy[n.id] = (n.location.x, n.location.y)
            member_tiles[("n", n.id)] = point_tiles(
                n.location.x, n.location.y, tiles)

    node_keys = sorted(index["n"])
    if node_keys:
        log("    pass 4: nodes")
        _run(files, osmium.filter.KeyFilter(*node_keys), Nodes())
    if member_nodes:
        _run(files, osmium.filter.IdFilter(member_nodes),
             MemberNodes())

    # Relations in a tile: one of their members is.
    for (rid, (members, tags, hit)) in rels.items():
        hit_tiles = set()
        for (t, ref, _) in members:
            hit_tiles |= member_tiles.get((t, ref), set())
        if hit_tiles:
            add(hit, hit_tiles, "r", rid)
    needed_rels = {rid for sets in take.values() for rid in sets["r"]}
    fetch = {ref for rid in needed_rels for (t, ref, _) in rels[rid][0]
             if t == "w" and ref not in way_data}

    # Pass 5: their member ways outside the tiles (complete relations).
    class MoreWays(osmium.SimpleHandler):
        def way(self, w):
            (refs, xs, ys, ok) = geometry(w)
            if not ok:
                broken[w.id] = set()
            way_data[w.id] = (refs, xs, ys, [(t.k, t.v) for t in w.tags])

    if fetch:
        log(f"    pass 5: {len(fetch)} member ways outside the tiles")
        _run(files, osmium.filter.IdFilter(fetch), MoreWays(),
             locations=True)
    rel_missing = {}  # rel id -> member ways absent from the files
    for rid in needed_rels:
        absent = [ref for (t, ref, _) in rels[rid][0]
                  if t == "w" and ref not in way_data]
        if absent:
            rel_missing[rid] = absent

    # Pass 6: tags of every node in a layer that queries nodes (airports).
    tag_ids = set()
    for ((tile, layer), sets) in take.items():
        if (tile, layer) in node_layers:
            tag_ids |= sets["n"]
            for wid in _layer_ways(sets, rels):
                tag_ids.update(way_data[wid][0] if wid in way_data else ())
    node_tags = {}

    class NodeTags(osmium.SimpleHandler):
        def node(self, n):
            if n.tags:
                node_tags[n.id] = [(t.k, t.v) for t in n.tags]

    if tag_ids:
        log(f"    pass 6: tags of {len(tag_ids)} airport nodes")
        _run(files, osmium.filter.IdFilter(tag_ids), NodeTags())

    # Assemble each tile's answers; a tile with any gap gets none.
    answers, failed = {}, {}
    for (tile, layers) in wanted.items():
        reasons, out = [], {}
        for (layer, statements) in layers.items():
            sets = take.get((tile, layer), {"n": set(), "w": set(), "r": set()})
            try:
                out[layer] = _layer_answer(
                    statements, source, osm_base, sets, rels, way_data,
                    node_xy, node_tags if (tile, layer) in node_layers else {},
                    broken, rel_missing)
            except ExtractError as e:
                reasons.append(f"{layer}: {e}")
        if reasons:
            failed[tile] = "; ".join(reasons)
        else:
            answers[tile] = out
    return (answers, failed)


def _layer_ways(sets, rels):
    ways = set(sets["w"])
    for rid in sets["r"]:
        ways.update(ref for (t, ref, _) in rels[rid][0] if t == "w")
    return ways


def _layer_answer(statements, source, osm_base, sets, rels, way_data,
                  node_xy, node_tags, broken, rel_missing):
    ways = _layer_ways(sets, rels)
    gaps = sorted(w for w in ways if w in broken)
    if gaps:
        raise ExtractError(
            f"way {', '.join(map(str, gaps[:3]))} has nodes outside the "
            "extract files (add the neighbouring extract)")
    missing = sorted(r for r in sets["r"] if r in rel_missing)
    if missing:
        raise ExtractError(
            f"relation {missing[0]} lacks member way "
            f"{rel_missing[missing[0]][0]} (outside the extract files; add "
            "the neighbouring extract)")
    nodes = {}
    for wid in ways:
        (refs, xs, ys, _) = way_data[wid]
        for (ref, x, y) in zip(refs, xs, ys):
            nodes[ref] = (x, y, node_tags.get(ref))
    for nid in sets["n"]:
        (x, y) = node_xy[nid]
        nodes[nid] = (x, y, node_tags.get(nid))
    for rid in sets["r"]:
        for (t, ref, _) in rels[rid][0]:
            if t == "n" and ref in node_xy:
                nodes[ref] = (*node_xy[ref], node_tags.get(ref))
    return answer_xml(
        statements, source, osm_base, nodes,
        {w: (way_data[w][0], way_data[w][3]) for w in ways},
        {r: (rels[r][0], rels[r][1]) for r in sets["r"]})
