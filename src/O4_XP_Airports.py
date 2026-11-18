"""Airports that X-Plane flattens, read from X-Plane's own apt.dat.

An airport with "1302 flatten 1" in apt.dat is drawn by X-Plane on ground it
forces flat at the airport elevation, inside the airport boundary (row 130).
Where the elevation data under it differs (data older than a new runway,
blasting and fill, uneven ground in a large boundary), the edge of that
area shows as vertical walls in the sim (Nuuk BGGH: 18-107 m data under a
flat 86 m). Step 1 builds the same areas flat at the same height, as a
hand-made patch would, so the mesh meets X-Plane's ground with slopes.

apt.dat (~400 MB) is read once into a small index next to the tile data
(tmp/xp_flatten_airports.json) and read again only when apt.dat changes.
"""
import json
import math
import os

from shapely import affinity, geometry, ops

import O4_File_Names as FNAMES
import O4_UI_Utils as UI

# App setting (Ortho4XP.cfg): match X-Plane's airport flattening in step 1.
xp_flatten_airports = True

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


def flatten_areas_for_tile(tile, overlay_srcs):
    """tile_flatten_areas from X-Plane's apt.dat, [] when the setting is off
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
    airports = load_airports(apt_dat)
    if not airports:
        return []
    return tile_flatten_areas(airports, tile.lat, tile.lon)


def degrees_area_to_km2(area, lat):
    return area * 111.32 ** 2 * math.cos(math.radians(lat))
