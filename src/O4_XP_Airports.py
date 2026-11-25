"""Airports that X-Plane flattens, read from X-Plane's own apt.dat.

An airport with "1302 flatten 1" in apt.dat is drawn by X-Plane on ground it
forces flat at the airport elevation. Step 1 builds the airport boundary
(row 130) flat at that height, as a hand-made patch would, and ramps the
elevation data around it back to the data over FLATTEN_RAMP_M (#115, #119),
so the airport needs no flattening by X-Plane.

X-Plane's own flatten covers far more than the boundary: at Nuuk BGGH it
raised the sea to 86 m and cut the hills with straight walls over a DSF
that was flat inside the boundary and ramped around it (#123). The walls
went only without the flag, so an override pack holds those airports
without it once their tiles are built flat (update_override_pack), with
their 3D (buildings, hangars, ...) copied from Global Airports' DSFs: X-Plane
draws those only for an airport taken from Global Airports itself (#124).

apt.dat (~400 MB) is read once into a small index next to the tile data
(tmp/xp_flatten_airports.json) and read again only when apt.dat changes.
"""
import hashlib
import json
import math
import os
import struct

import numpy
import shapely
from shapely import affinity, geometry, ops

import O4_File_Names as FNAMES
import O4_Geo_Utils as GEO
import O4_UI_Utils as UI

# App setting (Ortho4XP.cfg): match X-Plane's airport flattening in step 1.
xp_flatten_airports = True

# Width of the ramp around a flattened airport from its elevation back to
# the elevation data (#119): Nuuk's 30-40 m steps become slopes of ~20 deg,
# about an embankment's.
FLATTEN_RAMP_M = 100.0

APT_DAT_REL = os.path.join("Global Airports", "Earth nav data", "apt.dat")
INDEX_VERSION = 1
FT_TO_M = 0.3048
# Clipped to the tile a little inside its edges: the tile frame edges are
# already in the vector map, a flatten edge on top of them is not wanted.
EDGE_INSET = 1e-6


def index_path():
    return os.path.join(FNAMES.Tmp_dir, "xp_flatten_airports.json")


def find_apt_dat(overlay_srcs):
    """X-Plane's apt.dat from the Global Scenery folders the overlay settings
    name (".../Global Scenery/X-Plane 12 Global Scenery"): its parent holds
    Global Airports. None when there is none."""
    for src in overlay_srcs:
        if not src:
            continue
        path = os.path.join(
            os.path.dirname(os.path.normpath(src)), APT_DAT_REL
        )
        if os.path.isfile(path):
            return path
    return None


def parse_apt_dat(lines):
    """Flatten airports with a boundary, from apt.dat lines (str or bytes).

    Returns a list of dicts: icao, elev_m, polygons; each polygon is a list
    of rings [[lon, lat], ...] (lists, as the JSON index gives them), the first the outline, the others holes (a
    130 boundary is one polygon; an airport may have several). Bezier
    control points are ignored (the nodes are kept). Airports without
    "flatten 1" or without a boundary are left out: X-Plane does not
    flatten an area for them that step 1 could match.
    """
    out = []
    apt = None
    polygon = None
    ring = None

    def finish():
        if apt and apt["flatten"] and apt["polygons"]:
            polys = [
                [r for r in p if len(r) >= 3] for p in apt["polygons"]
            ]
            polys = [p for p in polys if p]
            if polys:
                out.append(
                    {
                        "icao": apt["icao"],
                        "elev_m": round(apt["elev_ft"] * FT_TO_M, 2),
                        "polygons": polys,
                    }
                )

    for line in lines:
        if isinstance(line, bytes):
            line = line.decode("utf-8", "replace")
        p = line.split()
        if not p:
            continue
        code = p[0]
        if code in ("1", "16", "17"):
            finish()
            try:
                apt = {"icao": p[4], "elev_ft": float(p[1]),
                       "flatten": False, "polygons": []}
            except (IndexError, ValueError):
                apt = None
            polygon = ring = None
        elif apt is None:
            continue
        elif code == "1302":
            if len(p) >= 3 and p[1] == "flatten" and p[2] == "1":
                apt["flatten"] = True
        elif code == "130":
            polygon = []
            apt["polygons"].append(polygon)
            ring = []
            polygon.append(ring)
        elif code in ("111", "112", "113", "114", "115", "116"):
            if ring is None:
                continue
            try:
                ring.append([float(p[2]), float(p[1])])
            except (IndexError, ValueError):
                continue
            if code in ("113", "114"):
                # Ring closed: a following node starts a hole of the same
                # boundary, until the next row of another kind.
                ring = []
                polygon.append(ring)
        elif code == "99":
            finish()
            apt = None
        else:
            polygon = ring = None
    finish()
    return out


def _read_index(path, stamp):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if data.get("version") != INDEX_VERSION or data.get("source") != stamp:
        return None
    return data.get("airports")


def load_airports(apt_dat):
    """The flatten airports of apt_dat, through the index (rebuilt when
    apt.dat's path, size or time changed; parallel batch workers wait for
    the one building it). None when apt.dat cannot be read."""
    try:
        st = os.stat(apt_dat)
    except OSError:
        return None
    stamp = {"path": os.path.normcase(os.path.abspath(apt_dat)),
             "size": st.st_size, "mtime_ns": st.st_mtime_ns}
    path = index_path()
    airports = _read_index(path, stamp)
    if airports is not None:
        return airports
    import O4_Geofabrik as GEOFABRIK  # its cross-process file lock
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with GEOFABRIK._FileLock(path + ".lock"):
        airports = _read_index(path, stamp)  # built while we waited?
        if airports is not None:
            return airports
        UI.vprint(1, "   Reading X-Plane's apt.dat for airports it flattens",
                  "(once per apt.dat version).")
        try:
            with open(apt_dat, "rb") as f:
                airports = parse_apt_dat(f)
        except OSError as e:
            UI.lvprint(1, "   WARNING: could not read", apt_dat,
                       f"({e}); airports X-Plane flattens are not matched.")
            return None
        tmp = FNAMES.temp_path_for(path)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": INDEX_VERSION, "source": stamp,
                       "airports": airports}, f)
        FNAMES.finish_temp_file(tmp, path)
    return airports


def tile_flatten_areas(airports, lat, lon):
    """[(icao, elev_m, Polygon in tile coordinates)] of the airports whose
    boundary reaches into tile (lat, lon), clipped a little inside it."""
    box = geometry.box(lon, lat, lon + 1, lat + 1)
    inner = geometry.box(lon + EDGE_INSET, lat + EDGE_INSET,
                         lon + 1 - EDGE_INSET, lat + 1 - EDGE_INSET)
    out = []
    for apt in airports:
        polys = []
        for rings in apt["polygons"]:
            try:
                pol = geometry.Polygon(rings[0], rings[1:]).buffer(0)
            except (ValueError, TypeError):
                continue
            if pol.is_empty or not pol.intersects(box):
                continue
            pol = pol.intersection(inner)
            if not pol.is_empty and pol.area > 0:
                polys.append(pol)
        if not polys:
            continue
        area = ops.unary_union(polys)
        area = geometry.MultiPolygon(
            [g for g in getattr(area, "geoms", [area])
             if isinstance(g, geometry.Polygon) and g.area > 0]
        )
        if area.is_empty:
            continue
        out.append((apt["icao"], apt["elev_m"],
                    affinity.translate(area, -lon, -lat)))
    return out


def ramp_areas(airports, lat, lon, bounds, width_m=FLATTEN_RAMP_M):
    """[(icao, elev_m, area in tile coordinates)] of the airports whose
    boundary lies within width_m of the elevation data bounds (x0, y0, x1,
    y1 in tile coordinates, the tile and its margin): all polygons of each,
    unclipped. The ramp must not depend on which tile is built: an airport
    just across the edge, or the part of a boundary in the neighbour tile,
    ramps the edge samples there too, and both tiles then give their
    shared edge the same elevations (tile_flatten_areas clips to the tile
    and missed both)."""
    (x0, y0, x1, y1) = bounds
    far = min(max(abs(lat + y0), abs(lat + y1)), 89.0)
    (wx, wy) = (width_m / GEO.lon_to_m(far), width_m / GEO.lat_to_m)
    box = geometry.box(lon + x0 - wx, lat + y0 - wy,
                       lon + x1 + wx, lat + y1 + wy)
    out = []
    for apt in airports:
        polys = []
        for rings in apt["polygons"]:
            try:
                pol = geometry.Polygon(rings[0], rings[1:]).buffer(0)
            except (ValueError, TypeError):
                continue
            if not pol.is_empty and pol.area > 0:
                polys.append(pol)
        if not polys or not any(p.intersects(box) for p in polys):
            continue
        out.append((apt["icao"], apt["elev_m"],
                    affinity.translate(ops.unary_union(polys), -lon, -lat)))
    return out


def _tile_airports(overlay_srcs):
    """The flatten airports of X-Plane's apt.dat, [] when the setting is off
    or X-Plane's apt.dat is not found (console note only: a build without
    an X-Plane installation is unchanged)."""
    if not xp_flatten_airports:
        return []
    apt_dat = find_apt_dat(overlay_srcs)
    if not apt_dat:
        UI.vprint(1, "   X-Plane's Global Airports apt.dat not found next to",
                  "custom_overlay_src: airports X-Plane flattens are not",
                  "matched.")
        return []
    return load_airports(apt_dat) or []


def flatten_areas_for_tile(tile, overlay_srcs):
    """tile_flatten_areas from X-Plane's apt.dat, [] when the setting is off
    or X-Plane's apt.dat is not found."""
    airports = _tile_airports(overlay_srcs)
    if not airports:
        return []
    return tile_flatten_areas(airports, tile.lat, tile.lon)


def ramp_areas_for_tile(tile, overlay_srcs, bounds):
    """ramp_areas from X-Plane's apt.dat ([] as flatten_areas_for_tile)."""
    airports = _tile_airports(overlay_srcs)
    if not airports:
        return []
    return ramp_areas(airports, tile.lat, tile.lon, bounds)


def areas_without_user_patch(areas, patch_dir, usable=os.path.isfile):
    """The flatten areas whose airport has no user patch (<ICAO>.patch.osm in
    patch_dir): a user patch replaces X-Plane's area (include_patches).
    usable(path) tells whether a patch file counts: include_patches skips
    one it cannot read, and X-Plane's area is then built after all, so the
    ramp around it must be there too."""
    return [a for a in areas
            if not usable(os.path.join(patch_dir, a[0] + ".patch.osm"))]


def ramp_dem_around_areas(alt_dem, bounds, areas, lat, width_m=FLATTEN_RAMP_M):
    """Set the elevation samples inside each (icao, elev, area) to elev and
    blend them linearly back to the data within width_m around the area
    (distance in metres). alt_dem: rows from north to south, samples from
    x0 to x1 and y1 to y0 inclusive; bounds (x0, y0, x1, y1) and the areas
    in tile coordinates. Changed in place; returns the samples changed.
    Distances are measured at the area's own latitude, not the tile's, so
    two tiles ramping the same airport agree on their shared edge."""
    (x0, y0, x1, y1) = bounds
    (ny, nx) = alt_dem.shape
    xstep = (x1 - x0) / (nx - 1)
    ystep = (y1 - y0) / (ny - 1)
    my = GEO.lat_to_m
    wy = width_m / my
    changed = 0
    for (_icao, elev, area) in areas:
        mx = GEO.lon_to_m(lat + area.centroid.y)
        wx = width_m / mx
        (xmin, ymin, xmax, ymax) = area.bounds
        c0 = max(math.floor((xmin - wx - x0) / xstep), 0)
        c1 = min(math.ceil((xmax + wx - x0) / xstep), nx - 1)
        r0 = max(math.floor((y1 - ymax - wy) / ystep), 0)
        r1 = min(math.ceil((y1 - ymin + wy) / ystep), ny - 1)
        if c0 > c1 or r0 > r1:
            continue
        (X, Y) = numpy.meshgrid(x0 + numpy.arange(c0, c1 + 1) * xstep,
                                y1 - numpy.arange(r0, r1 + 1) * ystep)
        metric = affinity.scale(area, mx, my, origin=(0, 0))
        dist = shapely.distance(
            metric, shapely.points(X.ravel() * mx, Y.ravel() * my)
        ).reshape(X.shape)
        t = numpy.clip(dist / width_m, 0, 1)
        window = alt_dem[r0:r1 + 1, c0:c1 + 1]  # a view: written in place
        near = t < 1
        window[near] = (elev + (window - elev) * t)[near]
        changed += int(near.sum())
    return changed


def degrees_area_to_km2(area, lat):
    return area * 111.32 ** 2 * math.cos(math.radians(lat))


################################################################################
# Override pack (#123): X-Plane's own flatten covers far more than the
# boundary (Nuuk: the sea raised to 86 m with straight edges, hills cut, all
# over a DSF that was flat inside the boundary and ramped around it). The
# walls went only when the airport came from a pack above Global Airports
# without "1302 flatten 1". Such a pack is written for every airport the
# built tiles have flat: step 1 records the airports it built flat in the
# tile folder (MARKER), and an airport goes into the pack once every tile
# its boundary reaches has it recorded and a DSF built since.

MARKER = "xp_flattened_airports.json"
PACK_APT_DAT = os.path.join("Earth nav data", "apt.dat")
PACK_STAMP = "ortho4xp_pack.json"
# Bumped when the pack gains content, so packs written before are redone.
# 2: the airports' 3D from Global Airports (#124).
PACK_VERSION = 2

# The 3D of a gateway airport (buildings, hangars, cars, lights) lives in
# Global Airports' DSF of its tile, in a block behind "FILTER n", where n
# counts the DSF's "sim/filter/aptid <ICAO>" properties; the exclusions
# after such a property belong to that airport. X-Plane draws a block only
# while the airport comes from that same pack, so with the airport taken
# from the override pack its buildings were gone (Nuuk, 2026-11-21). The
# pack therefore carries, per tile, a DSF with only its airports' blocks
# (the others stay with Global Airports, so nothing is drawn twice).
APTID_PROPERTY = "sim/filter/aptid"


def ga_dsf_path(apt_dat, lat, lon):
    """Global Airports' DSF of a tile, next to its apt.dat."""
    return FNAMES.dsf_file(
        os.path.dirname(os.path.dirname(apt_dat)), lat, lon)


def _atoms(data, start, end):
    """(name, payload start, payload end) of the DSF atoms in data[start:end];
    ValueError when they do not fit."""
    out = []
    pos = start
    while pos < end:
        if pos + 8 > end:
            raise ValueError("DSF atom header cut off")
        (aid, length) = struct.unpack_from("<4sI", data, pos)
        if length < 8 or pos + length > end:
            raise ValueError("DSF atom length out of range")
        out.append((aid[::-1].decode("latin-1"), pos + 8, pos + length))
        pos += length
    return out


def _atom(name, payload):
    return struct.pack("<4sI", name[::-1].encode("latin-1"),
                       8 + len(payload)) + payload


def read_dsf(path):
    """(file header, top-level atoms {name: payload}, their order, the
    properties [(key, value)]) of an uncompressed DSF; ValueError when it is
    none or is broken."""
    with open(path, "rb") as f:
        data = f.read()
    if data.startswith(b"7z\xbc\xaf"):
        raise ValueError("compressed DSF")
    if not data.startswith(b"XPLNEDSF") or len(data) < 28:
        raise ValueError("not a DSF")
    if hashlib.md5(data[:-16]).digest() != data[-16:]:
        raise ValueError("DSF checksum wrong")
    atoms = {}
    order = []
    for (name, a, b) in _atoms(data, 12, len(data) - 16):
        atoms[name] = data[a:b]
        order.append(name)
    head = atoms.get("HEAD", b"")
    props = []
    for (name, a, b) in _atoms(head, 0, len(head)):
        if name == "PROP":
            strings = head[a:b].split(b"\x00")
            props = [(strings[i].decode("utf-8", "replace"),
                      strings[i + 1].decode("utf-8", "replace"))
                     for i in range(0, len(strings) - 1, 2)]
    return (data[:12], atoms, order, props)


def dsf_airport_ids(path):
    """The airports with a filter block in a DSF, in filter order."""
    return [v for (k, v) in read_dsf(path)[3] if k == APTID_PROPERTY]


def filter_properties(props, icaos):
    """The properties without the aptid filters of other airports and the
    exclusions that follow them (exclusions before any aptid too: Global
    Airports applies them anyway). Returns (properties, {old filter index:
    new one})."""
    want = set(icaos)
    out = []
    renumber = {}
    n_ids = 0
    kept = False
    for (k, v) in props:
        if k == APTID_PROPERTY:
            kept = v in want
            if kept:
                renumber[n_ids] = len(renumber)
                out.append((k, v))
            n_ids += 1
        elif k.startswith("sim/exclude_"):
            if kept:
                out.append((k, v))
        else:
            kept = False
            out.append((k, v))
    return (out, renumber)


# DSF commands (DSF specification). State commands change what later
# commands refer to (pool, definition, junction offset, road subtype): they
# are kept whatever filter they sit under, so a kept block still sees the
# state an earlier block set. A filter is a comment whose payload is
# uint16 1 and the int32 filter index. Global Airports has one other
# comment (payload uint16 2, int32 1; 1,299 of its 7,077 DSFs, before an
# object command; DSFTool does not show it): kept like a state command,
# as are any other comments.
_STATE_CMDS = {1: 2, 2: 4, 3: 1, 4: 2, 5: 4, 6: 1}  # id: argument bytes
_COMMENTS = {32: 1, 33: 2, 34: 4}  # id: bytes of the length field
_FILTER_COMMENT = 1


def _cmd_end(cmds, pos):
    """End of the command starting at pos."""
    c = cmds[pos]
    p = pos + 1
    if c in _STATE_CMDS:
        return p + _STATE_CMDS[c]
    if c == 7:                      # object
        return p + 2
    if c in (8, 10, 25, 28, 31):    # ranges: first, last
        return p + 4
    if c in (9, 23, 26, 29):        # count, uint16 indices
        return p + 1 + 2 * cmds[p]
    if c in (11, 24, 27, 30):       # count, uint32 / (pool, index) pairs
        return p + 1 + 4 * cmds[p]
    if c == 12:                     # polygon: param, count, uint16 indices
        return p + 3 + 2 * cmds[p + 2]
    if c == 15:                     # nested polygon range: param, count,
        return p + 3 + 2 * (cmds[p + 2] + 1)  # count + 1 winding bounds
    if c == 13:                     # polygon range: param, first, last
        return p + 6
    if c == 14:                     # nested polygon: param, windings, each
        n = cmds[p + 2]             # a count and uint16 indices
        p += 3
        for _ in range(n):
            p += 1 + 2 * cmds[p]
        return p
    if c == 16:                     # terrain patch
        return p
    if c == 17:                     # patch with flags
        return p + 1
    if c == 18:                     # patch with flags and LOD
        return p + 9
    if c in _COMMENTS:
        size = _COMMENTS[c]
        length = int.from_bytes(cmds[p:p + size], "little")
        return p + size + length
    raise ValueError(f"unknown DSF command {c} at byte {pos}")


def _filter_index(cmds, pos, end):
    """The filter index a comment command sets, None for another comment."""
    payload = cmds[pos + 1 + _COMMENTS[cmds[pos]]:end]
    if len(payload) == 6 and \
            struct.unpack_from("<H", payload)[0] == _FILTER_COMMENT:
        return struct.unpack_from("<i", payload, 2)[0]
    return None


def filter_commands(cmds, renumber):
    """The command stream with only the blocks of the filters in renumber
    (renumbered), the state commands everywhere; drawing commands outside
    any filter are left out (Global Airports shows them anyway)."""
    out = bytearray()
    current = None
    pos = 0
    n = len(cmds)
    while pos < n:
        end = _cmd_end(cmds, pos)
        if end > n:
            raise ValueError("DSF command cut off")
        c = cmds[pos]
        idx = _filter_index(cmds, pos, end) if c in _COMMENTS else None
        if idx is not None:
            current = renumber.get(idx)
            if current is not None:
                out += struct.pack("<BBHi", 32, 6, _FILTER_COMMENT, current)
        elif c in _STATE_CMDS or c in _COMMENTS or current is not None:
            out += cmds[pos:end]
        pos = end
    return bytes(out)


def filter_dsf(src, dst, icaos):
    """Write to dst Global Airports' DSF src with only the blocks of the
    airports in icaos; False (nothing written) when none of them is in it.
    Definitions and point pools are copied as they are."""
    (head, atoms, order, props) = read_dsf(src)
    (kept, renumber) = filter_properties(props, icaos)
    if not renumber:
        return False
    prop = b"".join(k.encode("utf-8") + b"\x00" + v.encode("utf-8") + b"\x00"
                    for (k, v) in kept)
    body = bytearray(head)
    for name in order:
        if name == "HEAD":
            body += _atom("HEAD", _atom("PROP", prop))
        elif name == "CMDS":
            body += _atom("CMDS", filter_commands(atoms["CMDS"], renumber))
        else:
            body += _atom(name, atoms[name])
    body += hashlib.md5(body).digest()
    tmp = FNAMES.temp_path_for(dst)
    try:
        with open(tmp, "wb") as f:
            f.write(body)
        os.replace(tmp, dst)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return True


def candidate_tiles(apt):
    """Tiles that may hold the airport's 3D: those its boundary's bounding
    box touches and their neighbours (objects can lie outside the
    boundary)."""
    lons = [p[0] for rings in apt["polygons"] for r in rings for p in r]
    lats = [p[1] for rings in apt["polygons"] for r in rings for p in r]
    return {(lat, lon)
            for lat in range(math.floor(min(lats)) - 1,
                             math.floor(max(lats)) + 2)
            for lon in range(math.floor(min(lons)) - 1,
                             math.floor(max(lons)) + 2)
            if -90 <= lat < 90 and -180 <= lon < 180}


def write_object_dsfs(apt_dat, airports, icaos, out_dir):
    """The pack's DSFs: per tile, Global Airports' blocks of the airports in
    icaos. Pack DSFs of other tiles are removed. Returns (tiles written,
    failures as text)."""
    want = set(icaos)
    tiles = set()
    for apt in airports:
        if apt["icao"] in want:
            tiles |= candidate_tiles(apt)
    written = set()
    kept = set()
    failures = []
    for (lat, lon) in sorted(tiles):
        src = ga_dsf_path(apt_dat, lat, lon)
        if not os.path.isfile(src):
            continue
        target = FNAMES.dsf_file(out_dir, lat, lon)
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            if filter_dsf(src, target, icaos):
                written.add(os.path.normcase(target))
        except (OSError, ValueError, struct.error, IndexError) as e:
            failures.append(f"{FNAMES.short_latlon(lat, lon)}: {e}")
            # Its DSF of the last time stays: still right for the airports
            # it had. (A file X-Plane holds open cannot be replaced; it was
            # then deleted below, and the airport's 3D with it.)
            kept.add(os.path.normcase(target))
    # DSFs of tiles no longer in the pack (an airport left it).
    for root, _dirs, files in os.walk(os.path.join(out_dir, "Earth nav data")):
        for f in files:
            path = os.path.normcase(os.path.join(root, f))
            if f.lower().endswith(".dsf") and path not in written | kept:
                try:
                    os.remove(path)
                except OSError as e:
                    failures.append(f"{f} not removed ({e})")
    return (len(written), failures)


def pack_dir():
    return FNAMES.Airport_pack_dir


def marker_path(build_dir):
    return os.path.join(build_dir, MARKER)


def write_marker(build_dir, icaos):
    """Record the airports step 1 built flat in this tile folder; no file
    when there are none (a mesh built without them must not count)."""
    path = marker_path(build_dir)
    if not icaos:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        return
    FNAMES.write_text_atomic(path, json.dumps(sorted(set(icaos))))


def read_marker(build_dir):
    try:
        with open(marker_path(build_dir), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return set()
    return {str(x) for x in data} if isinstance(data, list) else set()


def built_flat_tiles(tile_dir):
    """{(lat, lon): {icao, ...}} of the tile folders in tile_dir whose DSF
    was built from (or after) the mesh that has those airports flat: the DSF
    is not older than the marker."""
    out = {}
    try:
        names = os.listdir(tile_dir)
    except OSError:
        return out
    for name in names:
        if not name.startswith("zOrtho4XP_"):
            continue
        try:
            (lat, lon) = (int(name[10:13]), int(name[13:17]))
        except ValueError:
            continue
        build_dir = os.path.join(tile_dir, name)
        try:
            marked = os.path.getmtime(marker_path(build_dir))
            built = os.path.getmtime(FNAMES.dsf_file(build_dir, lat, lon))
        except OSError:
            continue
        if built >= marked:
            icaos = read_marker(build_dir)
            if icaos:
                out[(lat, lon)] = icaos
    return out


def airport_tiles(apt):
    """The tiles (lat, lon) the airport's boundary reaches into (with area,
    as tile_flatten_areas counts them)."""
    tiles = set()
    for rings in apt["polygons"]:
        lons = [p[0] for r in rings for p in r]
        lats = [p[1] for r in rings for p in r]
        for lat in range(math.floor(min(lats)), math.floor(max(lats)) + 1):
            for lon in range(math.floor(min(lons)),
                             math.floor(max(lons)) + 1):
                if tile_flatten_areas([apt], lat, lon):
                    tiles.add((lat, lon))
    return tiles


def override_airports(airports, flat_tiles):
    """ICAOs of the flatten airports built flat in every tile they reach."""
    out = []
    for apt in airports:
        tiles = airport_tiles(apt)
        if tiles and all(apt["icao"] in flat_tiles.get(t, ()) for t in tiles):
            out.append(apt["icao"])
    return sorted(set(out))


def extract_blocks(lines, icaos):
    """{icao: [lines]} of the airports in icaos, from apt.dat lines (str or
    bytes), as they are there but for "1302 flatten 1"; trailing blank
    lines dropped."""
    want = set(icaos)
    out = {}
    cur = None
    for line in lines:
        if isinstance(line, bytes):
            line = line.decode("utf-8", "replace")
        line = line.rstrip("\r\n")
        p = line.split()
        if p and p[0] in ("1", "16", "17", "99"):
            cur = None
            if p[0] != "99" and len(p) > 4 and p[4] in want \
                    and p[4] not in out:
                cur = out[p[4]] = []
        if cur is None:
            continue
        if p[:3] == ["1302", "flatten", "1"]:
            continue
        cur.append(line)
    for block in out.values():
        while block and not block[-1].strip():
            block.pop()
    return out


def pack_text(blocks):
    lines = ["I", "1200 Version - Ortho4XP: X-Plane's airports without "
             "'1302 flatten 1' where the Ortho4XP tiles are built flat "
             "(written by Ortho4XP, do not edit)", ""]
    for icao in sorted(blocks):
        lines += blocks[icao] + [""]
    lines.append("99")
    return "\n".join(lines) + "\n"


def _write_apt_dat(path, text):
    """UTF-8 (apt.dat's encoding; names outside the ANSI code page would
    not encode otherwise) with CRLF as X-Plane's own, written atomically."""
    tmp = FNAMES.temp_path_for(path)
    try:
        with open(tmp, "w", encoding="utf-8", newline="\r\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def update_override_pack(overlay_srcs, tile_dir=None, out_dir=None):
    """Write the override pack (apt.dat, and the airports' 3D as DSFs) when
    the airports in it, X-Plane's apt.dat or PACK_VERSION changed. Returns the number of airports in it, None when nothing was
    done (setting off, no apt.dat)."""
    if not xp_flatten_airports:
        return None
    apt_dat = find_apt_dat(overlay_srcs)
    if not apt_dat:
        return None
    airports = load_airports(apt_dat)
    if airports is None:
        return None
    icaos = override_airports(
        airports, built_flat_tiles(tile_dir or FNAMES.Tile_dir))
    out_dir = out_dir or pack_dir()
    st = os.stat(apt_dat)
    stamp = {"apt_dat": os.path.normcase(os.path.abspath(apt_dat)),
             "size": st.st_size, "mtime_ns": st.st_mtime_ns,
             "airports": icaos, "version": PACK_VERSION}
    stamp_file = os.path.join(out_dir, PACK_STAMP)
    target = os.path.join(out_dir, PACK_APT_DAT)
    try:
        with open(stamp_file, encoding="utf-8") as f:
            if json.load(f) == stamp and os.path.isfile(target):
                return len(icaos)
    except (OSError, ValueError):
        pass
    blocks = {}
    if icaos:
        with open(apt_dat, "rb") as f:
            blocks = extract_blocks(f, icaos)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    (n_dsf, failures) = write_object_dsfs(apt_dat, airports, icaos, out_dir)
    _write_apt_dat(target, pack_text(blocks))
    UI.lvprint(
        1, f"   X-Plane airport override: {len(blocks)} airport(s) without "
        f"X-Plane's flatten in {out_dir} ({', '.join(sorted(blocks)) or '-'}),"
        f" their 3D from Global Airports in {n_dsf} DSF(s)."
        " It must be in Custom Scenery above Global Airports.",
    )
    if failures:
        # No stamp: the next step 3 or batch tries again.
        UI.lvprint(
            1, "   WARNING: X-Plane airport override: the 3D of these tiles "
            "was not copied, their airports show without buildings: "
            + "; ".join(failures),
        )
    else:
        FNAMES.write_text_atomic(stamp_file, json.dumps(stamp))
    return len(blocks)
