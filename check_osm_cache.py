#!/usr/bin/env python3
"""Report which tiles' cached OSM layers are out of date.

Usage (from the Ortho4XP folder, with Ortho4XP's Python):
    python check_osm_cache.py                 every tile in OSM_data
    python check_osm_cache.py +55+012 +56+010 only these tiles
Options:
    --margin H   count edits up to H hours before the download (default 1)
    --csv FILE   also write one line per layer to FILE

Read only: nothing in OSM_data, Tiles or the config is changed. One
Overpass request per cached layer (about as long as downloading that layer
again, ~1 min), through the same lock as Ortho4XP, so it can run beside a
build without overloading the servers. Ctrl+C stops and prints the summary
so far.

To refresh a changed tile, delete (or move away) the layer files named in
the summary and rebuild the tile from step 1; its imagery stays cached.
See src/O4_OSM_Freshness.py for how a change is detected.
"""

import csv
import os
import sys
import time

Ortho4XP_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(Ortho4XP_dir, "src"))

import requests  # noqa: E402

import O4_File_Names as FNAMES  # noqa: E402
import O4_OSM_Utils as OSM  # noqa: E402
import O4_OSM_Freshness as FRESH  # noqa: E402
import O4_UI_Utils as UI  # noqa: E402

TENTATIVES = 4
SERVER_TIMEOUT = 300
RETRY_WAIT = 30


def ask_overpass(session, query, cache_file):
    """Answer bytes of a count query, or raise RuntimeError with the reason.

    The configured server first, then the others in turn (as a build's
    later tentatives do). Each request holds the cross-process Overpass
    slot, so a running batch and this check never query at once. A server
    whose data is older than cache_file cannot answer and counts as failed.
    """
    keys = list(OSM.overpass_servers)
    if not keys:
        raise RuntimeError("no Overpass server in overpass_servers.txt")
    choice = OSM.overpass_server_choice
    if choice in keys:
        keys.remove(choice)
        keys.insert(0, choice)
    last = ""
    for tentative in range(TENTATIVES):
        key = keys[tentative % len(keys)]
        slot = OSM._acquire_overpass_slot()
        if slot is None:
            raise RuntimeError("could not get the Overpass slot")
        try:
            try:
                r = session.get(
                    OSM.overpass_servers[key],
                    params={"data": query},
                    timeout=(OSM.overpass_timeout[0], SERVER_TIMEOUT + 10),
                )
            finally:
                OSM._release_overpass_slot(slot)
            if r.status_code == 200:
                # Both raise ValueError if the answer is unusable.
                (osm_base, _, _) = FRESH.parse_count_answer(r.content)
                FRESH.check_server_date(osm_base, cache_file)
                return r.content
            last = f"{key}: HTTP {r.status_code}"
            wait = RETRY_WAIT
            if r.status_code == 429:
                wait = max(int(r.headers.get("Retry-After", 0) or 0),
                           OSM.overpass_rate_limit_wait)
        except requests.RequestException as e:
            last, wait = f"{key}: {type(e).__name__}", RETRY_WAIT
        except ValueError as e:
            last, wait = f"{key}: {e}", RETRY_WAIT
        if tentative + 1 < TENTATIVES:
            print(f"      ({last}, new try in {wait} s)", flush=True)
            time.sleep(wait)
    raise RuntimeError(last)


def check_tile(session, lat, lon, margin, rows):
    """Check the tile's cached layers; returns (changed layers, failed)."""
    name = FNAMES.short_latlon(lat, lon)
    road_level = FRESH.tile_road_level(lat, lon)
    bbox = (lat, lon, lat + 1, lon + 1)
    changed, failed = [], []
    for (layer, path) in FRESH.cached_layers(lat, lon):
        statements = FRESH.layer_statements(layer, road_level)
        cached, highways = FRESH.cache_counts(path, statements)
        since = FRESH.since_date(path, margin)
        timer = time.time()
        try:
            answer = ask_overpass(
                session,
                FRESH.count_query(statements, bbox, since, SERVER_TIMEOUT),
                path,
            )
        except RuntimeError as e:
            print(f"  {name} {layer:<11} FAILED ({e})", flush=True)
            failed.append(layer)
            rows.append([name, layer, since, "", "failed", str(e)])
            continue
        osm_base, now, newer = FRESH.parse_count_answer(answer)
        is_changed, text = FRESH.layer_verdict(cached, now, newer)
        if layer == "small_roads":
            gaps = FRESH.road_level_gaps(road_level, highways)
            if gaps:
                # A rebuild would reuse this cache without these road types.
                is_changed = True
                text += (f"; cache has no {', '.join(gaps)} ways although "
                         f"road_level is {road_level}")
        if is_changed:
            changed.append(layer)
        print(f"  {name} {layer:<11} since {since[:16]} UTC: {text}"
              f"  ({time.time() - timer:.0f} s)", flush=True)
        rows.append([name, layer, since, osm_base,
                     "changed" if is_changed else "unchanged", text])
    return changed, failed


def main(argv):
    margin, csv_file, tiles = FRESH.DEFAULT_MARGIN, "", []
    args = list(argv)
    while args:
        arg = args.pop(0)
        if arg in ("-h", "--help"):
            print(__doc__)
            return 0
        if arg == "--margin" and args:
            try:
                margin = float(args.pop(0)) * 3600
            except ValueError:
                print("--margin needs a number of hours")
                return 2
        elif arg == "--csv" and args:
            csv_file = args.pop(0)
        else:
            tile = FRESH.parse_tile(arg)
            if not tile:
                print("Not a tile:", arg, "(expected e.g. +55+012)")
                return 2
            tiles.append(tile)
    UI.log = False  # this check is not a build: keep Ortho4XP.log clean
    choice = FRESH.read_config_value("Ortho4XP.cfg", "overpass_server_choice")
    if choice:
        OSM.overpass_server_choice = choice
    if not tiles:
        tiles = FRESH.cached_tiles()
    else:
        for (lat, lon) in tiles:
            if not FRESH.cached_layers(lat, lon):
                print("No cached OSM layer for", FNAMES.short_latlon(lat, lon))
        tiles = [t for t in tiles if FRESH.cached_layers(*t)]
    if not tiles:
        print("Nothing to check.")
        return 0
    layers = sum(len(FRESH.cached_layers(*t)) for t in tiles)
    print(f"Checking {layers} cached layers of {len(tiles)} tiles "
          f"(~1 min each, one request at a time).", flush=True)
    OSM._prefer_ipv4_without_ipv6_route()
    session = requests.Session()
    session.headers.update({
        "User-Agent":
            f"Ortho4XP/{OSM.O4XP_VERSION} (https://github.com/shred86/Ortho4XP)"
    })
    rows, changed_tiles, failed_tiles = [], [], []
    timer = time.time()
    try:
        for (lat, lon) in tiles:
            changed, failed = check_tile(session, lat, lon, margin, rows)
            name = FNAMES.short_latlon(lat, lon)
            if changed:
                changed_tiles.append((name, changed))
            if failed:
                failed_tiles.append((name, failed))
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        session.close()
    if csv_file:
        with open(csv_file, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["tile", "layer", "since", "osm_base", "result", "details"])
            w.writerows(rows)
    print(f"\nChecked {len(rows)} layers in {(time.time() - timer) / 60:.0f} min.")
    if changed_tiles:
        print(f"Changed since download ({len(changed_tiles)} tiles):")
        for (name, changed) in changed_tiles:
            print(f"  {name}: {', '.join(changed)}")
    else:
        print("No changed layer found.")
    if failed_tiles:
        print("Not checked (no answer):")
        for (name, failed) in failed_tiles:
            print(f"  {name}: {', '.join(failed)}")
    return 1 if failed_tiles else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
