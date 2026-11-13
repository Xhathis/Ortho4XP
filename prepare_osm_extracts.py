#!/usr/bin/env python3
"""Prepare tiles' OSM layers from local OSM extracts instead of Overpass.

Usage (from the Ortho4XP folder, with Ortho4XP's Python):
    python prepare_osm_extracts.py FILE.osm.pbf [FILE ...] TILES [options]
TILES:
    --tiles +55+012 +56+010     these tiles
    --tile-file FILE            one +LL+LLL per line (# comments), e.g.
                                .last_batch_tiles.txt
Options:
    --road-level N   instead of each tile's config (else the global one)
    --force          also for layers already cached or prepared
    --index FILE     Geofabrik's index-v1.json (default: next to the
                     first file; download it with the extracts)
    --no-coverage    skip the coverage check (gaps are still found, see
                     below)
    --dry-run        only show what would be done

The files (Geofabrik .osm.pbf, any number) are read as one. A tile that
reaches into a Geofabrik region whose file is not given is skipped, with
the regions that would fill it (from Geofabrik's index-v1.json; open sea
outside all regions needs no file). For every layer of a tile that is
not cached yet, the answer Overpass would give is written to
OSM_data/<10x10>/<tile>/<tile>_<layer>.extract.osm.bz2; the next build of
the tile reads it instead of asking Overpass and writes the normal cache.
A tile whose data reaches outside the files (a way's node, a lake's member
way) gets no answer at all: add the neighbouring extract and run again.

Needs pyosmium (pip install osmium). Reads the files 3-4 times; memory
grows with the tiles' data, not with the size of the files.
See src/O4_OSM_Extract.py for the rules the answers follow.
"""

import os
import re
import sys
import time

Ortho4XP_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(Ortho4XP_dir, "src"))

import O4_File_Names as FNAMES  # noqa: E402
import O4_OSM_Extract as EXTRACT  # noqa: E402

_TILE = re.compile(r"^([+-]\d\d)([+-]\d\d\d)$")


def parse_tile(text):
    m = _TILE.match(text.strip())
    if not m:
        raise ValueError(f"not a tile name: {text!r} (expected +LL+LLL)")
    return (int(m.group(1)), int(m.group(2)))


def read_tile_file(path):
    with open(path, encoding="utf-8") as f:
        return [parse_tile(line) for line in f
                if line.strip() and not line.lstrip().startswith("#")]


def road_level_of(lat, lon, default):
    """road_level of the tile config, else of Ortho4XP.cfg, else default."""
    tile = FNAMES.short_latlon(lat, lon)
    for cfg in (os.path.join(FNAMES.Tile_dir, "zOrtho4XP_" + tile,
                             "Ortho4XP_" + tile + ".cfg"),
                os.path.join(Ortho4XP_dir, "Ortho4XP.cfg")):
        try:
            with open(cfg, encoding="utf-8") as f:
                for line in f:
                    if line.startswith("road_level="):
                        return int(line.split("=", 1)[1])
        except (OSError, ValueError):
            continue
    return default


def cached_nodes(lat, lon):
    """True if an already cached layer of the tile holds a node."""
    import bz2
    for layer in ("coastline", "airports", "big_roads", "small_roads",
                  "water"):
        try:
            with bz2.open(FNAMES.osm_cached(lat, lon, layer), "rt",
                          encoding="utf-8") as f:
                if any("<node id=" in line for line in f):
                    return True
        except (OSError, EOFError):
            continue
    return False


def given_areas(files, regions):
    """Areas of the files (by Geofabrik file name), or the names unknown."""
    by_name = {name: area for (_, name, area) in regions}
    unknown = [f for f in files if os.path.basename(f) not in by_name]
    return ([by_name[os.path.basename(f)] for f in files
             if os.path.basename(f) in by_name], unknown)


def main(argv):
    args = list(argv)
    files, tiles, opts = [], [], {"road_level": None, "index": None}
    try:
        while args:
            a = args.pop(0)
            if a == "--tiles":
                while args and not args[0].startswith("--"):
                    tiles.append(parse_tile(args.pop(0)))
            elif a == "--tile-file":
                tiles += read_tile_file(args.pop(0))
            elif a == "--road-level":
                opts["road_level"] = int(args.pop(0))
            elif a == "--index":
                opts["index"] = args.pop(0)
            elif a in ("--force", "--no-coverage", "--dry-run"):
                opts[a[2:]] = True
            elif a.startswith("--"):
                raise ValueError(f"unknown option {a}")
            else:
                files.append(a)
    except (ValueError, IndexError, OSError) as e:
        print(f"ERROR: {e}\n\n{__doc__}")
        return 2
    if not files or not tiles:
        print(__doc__)
        return 2
    missing = [f for f in files if not os.path.isfile(f)]
    if missing:
        print("ERROR: no such file:", ", ".join(missing))
        return 2
    tiles = list(dict.fromkeys(tiles))
    offshore = set()  # tiles partly beyond the files, only at sea

    if not opts.get("no-coverage"):
        index = opts["index"] or os.path.join(
            os.path.dirname(os.path.abspath(files[0])), "index-v1.json")
        if not os.path.isfile(index):
            print(f"ERROR: no Geofabrik index {index}\n(download "
                  "https://download.geofabrik.de/index-v1.json next to the "
                  "extracts, or use --no-coverage)")
            return 2
        regions = EXTRACT.read_index(index)
        (given, unknown) = given_areas(files, regions)
        if unknown:
            print("ERROR: not Geofabrik file names (renamed?):",
                  ", ".join(unknown), "- or use --no-coverage")
            return 2
        gaps = EXTRACT.coverage_gaps(tiles, given, regions)
        for ((lat, lon), fill) in sorted(gaps.items()):
            if EXTRACT.offshore_only(fill):
                offshore.add((lat, lon))
                print(f"NOTE {FNAMES.short_latlon(lat, lon)}: part of it is "
                      "sea beyond the given files (only " + ", ".join(fill)
                      + "): offshore objects there are not included")
            else:
                print(f"SKIP {FNAMES.short_latlon(lat, lon)}: reaches "
                      "outside the given files; add one of: "
                      + ", ".join(fill[:4]))
        tiles = [t for t in tiles
                 if t not in gaps or t in offshore]

    wanted = {}
    for (lat, lon) in tiles:
        rl = opts["road_level"]
        if rl is None:
            rl = road_level_of(lat, lon, 4)
        layers = {}
        for (layer, statements) in EXTRACT.layer_statements(rl).items():
            done = (os.path.isfile(FNAMES.osm_cached(lat, lon, layer))
                    or os.path.isfile(EXTRACT.answer_path(lat, lon, layer)))
            if opts.get("force") or not done:
                layers[layer] = statements
        if layers:
            wanted[(lat, lon)] = layers
    print(f"{len(tiles)} tile(s) covered, {len(wanted)} with layers to "
          f"prepare ({sum(len(v) for v in wanted.values())} layers) from "
          f"{len(files)} file(s).")
    if opts.get("dry-run") or not wanted:
        for ((lat, lon), layers) in wanted.items():
            print(f"  {FNAMES.short_latlon(lat, lon)}: {', '.join(layers)}")
        return 0

    start = time.time()
    (answers, failed) = EXTRACT.extract_answers(files, wanted)
    for tile in [t for t in answers if t in offshore]:
        if not (EXTRACT.has_objects(answers[tile]) or cached_nodes(*tile)):
            # Nothing of the tile in the files although it reaches beyond
            # them: its land, if any, is in the gap.
            del answers[tile]
            failed[tile] = ("no data in the given files, and part of the "
                            "tile lies beyond them (its land may be there)")
    written = 0
    for ((lat, lon), layers) in sorted(answers.items()):
        for (layer, content) in layers.items():
            EXTRACT.write_answer(EXTRACT.answer_path(lat, lon, layer), content)
            written += 1
        print(f"OK   {FNAMES.short_latlon(lat, lon)}: "
              + ", ".join(f"{k} {len(v) / 1e6:.1f} MB"
                          for (k, v) in layers.items()))
    for ((lat, lon), reason) in sorted(failed.items()):
        print(f"FAIL {FNAMES.short_latlon(lat, lon)}: {reason}")
    print(f"{written} layer answer(s) written for {len(answers)} tile(s), "
          f"{len(failed)} tile(s) failed, {time.time() - start:.0f} s.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
