import os
import sys
import time
import io
import bz2
import random
import requests
import numpy
from shapely import geometry, ops
from shapely.errors import ShapelyError
import O4_UI_Utils as UI
import O4_File_Names as FNAMES
from O4_Version import version as O4XP_VERSION

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

# Default overpass_server_choice if not in config
overpass_server_choice = "random"
max_osm_tentatives = 8
# Overpass gives a query 180 s by default before it answers, and sends
# nothing until then, so a 60 s read timeout cut off slow but valid
# answers (large residential layers) on every tentative.
overpass_timeout = (10, 190)  # (connect, read) in seconds
# A layer with several queries (roads, water) goes out as one union request:
# fewer slow round trips, and a way matched by two queries comes back once
# instead of being stored twice. It gets more server time, and falls back to
# one request per query when it keeps failing.
layer_request_server_timeout = 300  # seconds, sent as [timeout:...]
layer_request_tentatives = max_osm_tentatives // 2
# After an HTTP 429 the server wants us to slow down; retrying within a few
# seconds (2, 4, 8 s) got the connection reset by overpass-api.de.
overpass_rate_limit_wait = 60  # seconds, at least
# Set when a layer stopped the build because Overpass gave no answer after
# all tentatives (and reset by the batch before each step 1): a batch puts
# such a tile aside and tries it again later, since Overpass outages are
# usually temporary (2026-11-06: 21 tiles lost in ~3.5 h).
overpass_gave_up = False


def _no_ipv6_route():
    """True when this machine cannot reach the IPv6 internet at all.

    Connecting a UDP socket sends nothing; it only asks the OS for a route.
    """
    import socket
    s = None
    try:
        s = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        s.connect(("2001:4860:4860::8888", 53))
        return False
    except OSError:
        return True
    finally:
        if s is not None:
            s.close()


def _prefer_ipv4_without_ipv6_route():
    """Use only IPv4 addresses when there is no IPv6 route.

    requests tries every address of a host and reports the last failure.
    overpass-api.de lists its IPv4 addresses first, then IPv6; without an
    IPv6 route the IPv6 ones fail at once with "unreachable network"
    (WinError 10051), which then hid the real cause (the IPv4 servers
    timing out) in every error line.
    """
    if getattr(_prefer_ipv4_without_ipv6_route, "done", False):
        return
    _prefer_ipv4_without_ipv6_route.done = True
    try:
        import urllib3.util.connection as urllib3_connection
    except ImportError:  # requests always ships urllib3; be safe anyway
        return
    if urllib3_connection.HAS_IPV6 and _no_ipv6_route():
        urllib3_connection.HAS_IPV6 = False
        UI.vprint(2, "      No IPv6 route: connecting over IPv4 only.")


def _lock_file(f):
    if sys.platform == "win32":
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(f):
    if sys.platform == "win32":
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(f, fcntl.LOCK_UN)


def _acquire_overpass_slot():
    """Wait until no other Ortho4XP process has an Overpass request running.

    Parallel batch workers each download their own tile's OSM data; three
    at once got HTTP 429 and then connection resets from overpass-api.de,
    which allows about two running queries per IP. One request at a time is
    what the sequential batch always did. The OS releases the lock when a
    process ends, also when it is killed (Stop button). Returns the open
    lock file, or None if the build was stopped while waiting.
    """
    os.makedirs(FNAMES.OSM_dir, exist_ok=True)
    f = open(os.path.join(FNAMES.OSM_dir, ".overpass.lock"), "a+")
    waiting = False
    while True:
        try:
            _lock_file(f)
            return f
        except OSError:
            if UI.red_flag:
                f.close()
                return None
            if not waiting:
                UI.vprint(
                    1,
                    "      Waiting for another Ortho4XP process to finish "
                    "its OSM request...",
                )
                waiting = True
            time.sleep(1)


def _release_overpass_slot(f):
    try:
        _unlock_file(f)
    finally:
        f.close()


def _load_overpass_servers() -> dict:
    """Create dictionary from overpass_servers.txt."""
    servers = {}
    try:
        with open(FNAMES.resource_path("overpass_servers.txt"), "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, url = line.partition("=")
                    key, url = key.strip(), url.strip()
                    if key and url:
                        servers[key] = url
    except Exception as e:
        UI.lvprint(1, e)
    return servers


overpass_servers = _load_overpass_servers()


class OSM_layer:
    def __init__(self):
        self.dicosmn = {}  # keys are ints (ids) and values are tuple of (lat,lon)
        self.dicosmn_reverse = {}  # reverese of the previous one
        self.dicosmw = {}
        self.next_node_id = -1
        self.next_way_id = -1
        self.next_rel_id = -1
        # rels already sorted out and containing nodeids rather than wayids
        self.dicosmr = {}
        # original rels containing wayids only, not sorted and/or reversed
        self.dicosmrorig = {}
        # ids of objects directly queried, not of child or
        # parent objects pulled indirectly by queries. Since
        # osm ids are only unique per object type we need one for each:
        self.dicosmfirst = {"n": set(), "w": set(), "r": set()}
        self.dicosmtags = {"n": {}, "w": {}, "r": {}}
        self.dicosm = [
            self.dicosmn,
            self.dicosmw,
            self.dicosmr,
            self.dicosmrorig,
            self.dicosmfirst,
            self.dicosmtags,
        ]

    def update_dicosm(self, osm_input, input_tags=None, target_tags=None):
        # input_tags (dict or None) are the input query tags (per osm type)
        # target_tags (dict or None) are the the tags which should be kept
        # (per osm type) It is expected that if not None the target_tags
        # contains the input_tags
        initnodes = len(self.dicosmn)
        initways = len(self.dicosmfirst["w"])
        initrels = len(self.dicosmfirst["r"])
        dicosmn_id_map = {}
        dicosmw_id_map = {}
        # osm_input may either refer to an osm filename (e.g. cached data) or
        # to a xml bytestring (direct download)
        if isinstance(osm_input, str):
            osm_file_name = osm_input
            try:
                if osm_file_name[-4:] == ".bz2":
                    pfile = bz2.open(osm_file_name, "rt", encoding="utf-8")
                else:
                    pfile = open(osm_file_name, "r", encoding="utf-8")
            except OSError:
                UI.vprint(
                    1,
                    "    Could not open",
                    osm_file_name,
                    "for reading (corrupted ?).",
                )
                return 0
        elif isinstance(osm_input, bytes):
            pfile = io.StringIO(osm_input.decode(encoding="utf-8"))
        first_line = pfile.readline()
        if "<osm " not in first_line:
            first_line = pfile.readline()
        separator = "'" if "'" in first_line else '"'
        normal_exit = False
        for line in pfile:
            items = line.split(separator)
            if "<node id=" in items[0]:
                osmtype = "n"
                osmid = items[1]
                for j in range(0, len(items)):
                    if items[j] == " lat=":
                        latp = float(items[j + 1])
                    elif items[j] == " lon=":
                        lonp = float(items[j + 1])
                if (lonp, latp) in self.dicosmn_reverse:
                    true_osmid = self.dicosmn_reverse[(lonp, latp)]
                    dicosmn_id_map[osmid] = true_osmid
                    osmid = true_osmid
                else:
                    true_osmid = self.next_node_id
                    dicosmn_id_map[osmid] = true_osmid
                    osmid = true_osmid
                    self.dicosmn_reverse[(lonp, latp)] = osmid
                    self.dicosmn[osmid] = (lonp, latp)
                    self.next_node_id -= 1
            elif "<way id=" in items[0]:
                osmtype = "w"
                osmid = items[1]
                true_osmid = self.next_way_id
                self.next_way_id -= 1
                dicosmw_id_map[osmid] = true_osmid
                osmid = true_osmid
                self.dicosmw[osmid] = []
                if not input_tags:
                    self.dicosmfirst["w"].add(osmid)
            elif "<nd ref=" in items[0]:
                self.dicosmw[osmid].append(dicosmn_id_map[items[1]])
            elif "<relation id=" in items[0]:
                osmtype = "r"
                osmid = items[1]
                true_osmid = self.next_rel_id
                self.next_rel_id -= 1
                osmid = true_osmid
                self.dicosmr[osmid] = {"outer": [], "inner": []}
                self.dicosmrorig[osmid] = {"outer": [], "inner": []}
                dico_rel_check = {"inner": {}, "outer": {}}
                if not input_tags:
                    self.dicosmfirst["r"].add(osmid)
            elif "<member type=" in items[0]:
                role = items[5]
                if items[1] != "way" or role not in ("outer", "inner"):
                    if items[1] == "node":
                        continue  # not necessary to report these
                    UI.lvprint(
                        2,
                        "Relation id=",
                        osmid,
                        "contains a member of type",
                        "'" + items[1] + "'",
                        "and role",
                        "'" + role + "'",
                        "which was not treated (only deal with 'ways' of role ",
                        "'inner' or 'outer').",
                    )
                    continue
                try:
                    wayid = dicosmw_id_map[items[3]]
                except KeyError:
                    continue
                self.dicosmrorig[osmid][role].append(wayid)
                endpt1 = self.dicosmw[wayid][0]
                endpt2 = self.dicosmw[wayid][-1]
                if endpt1 == endpt2:
                    self.dicosmr[osmid][role].append(self.dicosmw[wayid])
                else:
                    if endpt1 in dico_rel_check[role]:
                        dico_rel_check[role][endpt1].append(wayid)
                    else:
                        dico_rel_check[role][endpt1] = [wayid]
                    if endpt2 in dico_rel_check[role]:
                        dico_rel_check[role][endpt2].append(wayid)
                    else:
                        dico_rel_check[role][endpt2] = [wayid]
            elif "<tag k=" in items[0]:
                # Do we need to catch that tag ?
                if (
                    (not input_tags)
                    or (("all", "") in target_tags[osmtype])
                    or ((items[1], "") in target_tags[osmtype])
                    or ((items[1], items[3]) in target_tags[osmtype])
                ):
                    if osmid not in self.dicosmtags[osmtype]:
                        self.dicosmtags[osmtype][osmid] = {items[1]: items[3]}
                    else:
                        self.dicosmtags[osmtype][osmid][items[1]] = items[3]
                    # If so, do we need to declare this osmid as a first catch,
                    # not one only brought with as a child
                    if input_tags and (
                        ((items[1], "") in input_tags[osmtype])
                        or ((items[1], items[3]) in input_tags[osmtype])
                    ):
                        self.dicosmfirst[osmtype].add(osmid)
            elif "</way" in items[0]:
                if not self.dicosmw[osmid]:
                    del self.dicosmw[osmid]
                    self.next_way_id += 1
                    if osmid in self.dicosmfirst["w"]:
                        self.dicosmfirst["w"].remove(osmid)
                    if osmid in self.dicosmtags["w"]:
                        del self.dicosmtags[osmtype][osmid]
            elif "</relation>" in items[0]:
                bad_rel = False
                for role, endpt in (
                    (r, e) for r in ["outer", "inner"] for e in dico_rel_check[r]
                ):
                    if len(dico_rel_check[role][endpt]) != 2:
                        bad_rel = True
                        break
                if bad_rel == True:
                    UI.lvprint(
                        2,
                        "Relation id=",
                        osmid,
                        "is ill formed and was not treated.",
                    )
                    del self.dicosmr[osmid]
                    del self.dicosmrorig[osmid]
                    del dico_rel_check
                    self.next_rel_id += 1
                    if osmid in self.dicosmfirst["r"]:
                        self.dicosmfirst["r"].remove(osmid)
                    if osmid in self.dicosmtags["r"]:
                        del self.dicosmtags["r"][osmid]
                    continue
                for role in ["outer", "inner"]:
                    while dico_rel_check[role]:
                        nodeids = []
                        endpt = next(iter(dico_rel_check[role]))
                        wayid = dico_rel_check[role][endpt][0]
                        endptinit = self.dicosmw[wayid][0]
                        endpt1 = endptinit
                        endpt2 = self.dicosmw[wayid][-1]
                        for nodeid in self.dicosmw[wayid][:-1]:
                            nodeids.append(nodeid)
                        while endpt2 != endptinit:
                            if dico_rel_check[role][endpt2][0] == wayid:
                                wayid = dico_rel_check[role][endpt2][1]
                            else:
                                wayid = dico_rel_check[role][endpt2][0]
                            endpt1 = endpt2
                            if self.dicosmw[wayid][0] == endpt1:
                                endpt2 = self.dicosmw[wayid][-1]
                                for nodeid in self.dicosmw[wayid][:-1]:
                                    nodeids.append(nodeid)
                            else:
                                endpt2 = self.dicosmw[wayid][0]
                                for nodeid in self.dicosmw[wayid][-1:0:-1]:
                                    nodeids.append(nodeid)
                            del dico_rel_check[role][endpt1]
                        nodeids.append(endptinit)
                        self.dicosmr[osmid][role].append(nodeids)
                        del dico_rel_check[role][endptinit]
                if target_tags == None:
                    for wayid in (
                        self.dicosmrorig[osmid]["outer"]
                        + self.dicosmrorig[osmid]["inner"]
                    ):
                        # A way shared by two relations was already taken out
                        # by the first one. dicosmfirst["w"] is a set, so
                        # discard(): narrowing the old bare except to
                        # ValueError (set.remove raises KeyError) made such
                        # files crash (#63).
                        self.dicosmfirst["w"].discard(wayid)
                if not self.dicosmr[osmid]["outer"]:
                    del self.dicosmr[osmid]
                    del self.dicosmrorig[osmid]
                    self.next_rel_id += 1
                    if osmid in self.dicosmfirst["r"]:
                        self.dicosmfirst["r"].remove(osmid)
                    if osmid in self.dicosmtags["r"]:
                        del self.dicosmtags["r"][osmid]
                del dico_rel_check
            elif "</osm>" in items[0]:
                normal_exit = True
        pfile.close()
        if not normal_exit:
            UI.lvprint(
                0,
                "ERROR: OSM overpass server answer was corrupted ",
                "(no ending </OSM> tag)",
            )
            return 0
        UI.vprint(
            2,
            "      A total of "
            + str(len(self.dicosmn) - initnodes)
            + " new node(s), "
            + str(len(self.dicosmfirst["w"]) - initways)
            + " new ways and "
            + str(len(self.dicosmfirst["r"]) - initrels)
            + " new relation(s).",
        )
        return 1

    def write_to_file(self, filename):
        try:
            if filename[-4:] == ".bz2":
                fout = bz2.open(filename, "wt", encoding="utf-8")
            else:
                fout = open(filename, "w", encoding="utf-8")
        except OSError:
            UI.lvprint(1, "    WARNING: could not open", filename, "for writing.")
            return 0
        fout.write(
            '<?xml version="1.0" encoding="UTF-8"?>\n<osm version="0.6" '
            + 'generator="Ortho4XP">\n'
        )
        if not len(self.dicosmfirst["n"]):
            for nodeid, (lonp, latp) in self.dicosmn.items():
                fout.write(
                    '  <node id="'
                    + str(nodeid)
                    + '" lat="'
                    + "{:.7f}".format(latp)
                    + '" lon="'
                    + "{:.7f}".format(lonp)
                    + '" version="1"/>\n'
                )
        else:
            for nodeid, (lonp, latp) in self.dicosmn.items():
                if nodeid not in self.dicosmtags["n"]:
                    fout.write(
                        '  <node id="'
                        + str(nodeid)
                        + '" lat="'
                        + "{:.7f}".format(latp)
                        + '" lon="'
                        + "{:.7f}".format(lonp)
                        + '" version="1"/>\n'
                    )
                else:
                    fout.write(
                        '  <node id="'
                        + str(nodeid)
                        + '" lat="'
                        + "{:.7f}".format(latp)
                        + '" lon="'
                        + "{:.7f}".format(lonp)
                        + '" version="1">\n'
                    )
                    for tag in self.dicosmtags["n"][nodeid]:
                        fout.write(
                            '    <tag k="'
                            + tag
                            + '" v="'
                            + self.dicosmtags["n"][nodeid][tag]
                            + '"/>\n'
                        )
                    fout.write("  </node>\n")
        # Write ways and relations in the order they were read (dict
        # insertion order). Reading the file back then gives every element
        # the same id as with the original download; iterating sets here
        # reshuffled them, so geometry built from the cache differed from
        # geometry built from a fresh download (mesh, masks and DSF).
        for wayid in self.dicosmw:
            fout.write('  <way id="' + str(wayid) + '" version="1">\n')
            for nodeid in self.dicosmw[wayid]:
                fout.write('    <nd ref="' + str(nodeid) + '"/>\n')
            for tag in (
                self.dicosmtags["w"][wayid] if wayid in self.dicosmtags["w"] else []
            ):
                fout.write(
                    '    <tag k="'
                    + tag
                    + '" v="'
                    + self.dicosmtags["w"][wayid][tag]
                    + '"/>\n'
                )
            fout.write("  </way>\n")
        for relid in self.dicosmrorig:
            fout.write('  <relation id="' + str(relid) + '" version="1">\n')
            for wayid in self.dicosmrorig[relid]["outer"]:
                fout.write(
                    '    <member type="way" ref="' + str(wayid) + '" role="outer"/>\n'
                )
            for wayid in self.dicosmrorig[relid]["inner"]:
                fout.write(
                    '    <member type="way" ref="' + str(wayid) + '" role="inner"/>\n'
                )
            for tag in (
                self.dicosmtags["r"][relid] if relid in self.dicosmtags["r"] else []
            ):
                fout.write(
                    '    <tag k="'
                    + tag
                    + '" v="'
                    + self.dicosmtags["r"][relid][tag]
                    + '"/>\n'
                )
            fout.write("  </relation>\n")
        fout.write("</osm>")
        fout.close()
        return 1


def OSM_queries_to_OSM_layer(
    queries,
    osm_layer,
    lat,
    lon,
    tags_of_interest=[],
    cached_suffix="",
):
    # this one is a bit complicated by a few checks of existing cached data
    # which had different filenames is versions prior to 1.30
    target_tags = {"n": [], "w": [], "r": []}
    input_tags = {"n": [], "w": [], "r": []}
    for query in queries:
        for tag in [query] if isinstance(query, str) else query:
            items = tag.split('"')
            osm_type = items[0][0]
            try:
                target_tags[osm_type].append((items[1], items[3]))
                input_tags[osm_type].append((items[1], items[3]))
            except IndexError:
                target_tags[osm_type].append((items[1], ""))
                input_tags[osm_type].append((items[1], ""))
            for tag in tags_of_interest:
                if isinstance(tag, str):
                    if (tag, "") not in target_tags[osm_type]:
                        target_tags[osm_type].append((tag, ""))
                else:
                    if tag not in target_tags[osm_type]:
                        target_tags[osm_type].append(tag)
    cached_data_filename = FNAMES.osm_cached(lat, lon, cached_suffix)
    if cached_suffix and os.path.isfile(cached_data_filename):
        UI.vprint(1, "    * Recycling OSM data from", cached_data_filename)
        return osm_layer.update_dicosm(cached_data_filename, input_tags, target_tags)
    old_scheme = any(
        isinstance(query, str)
        and os.path.isfile(FNAMES.osm_old_cached(lat, lon, query))
        for query in queries
    )
    if len(queries) > 1 and not old_scheme:
        statements = tuple(
            tag for query in queries
            for tag in ([query] if isinstance(query, str) else query)
        )
        UI.vprint(
            1,
            "    * Downloading OSM data for",
            cached_suffix or "the layer",
            f"({len(statements)} queries in one request)",
        )
        response = get_overpass_data(
            statements,
            (lat, lon, lat + 1, lon + 1),
            tentatives=layer_request_tentatives,
            server_timeout=layer_request_server_timeout,
        )
        if UI.red_flag:
            return 0
        if response:
            osm_layer.update_dicosm(response, input_tags, target_tags)
            if cached_suffix:
                osm_layer.write_to_file(cached_data_filename)
            return 1
        UI.vprint(
            1,
            "      No answer for the combined request (last:",
            (get_overpass_data.last_error or "unknown") + "),",
            "falling back to one request per query.",
        )
    for query in queries:
        # look first for cached data (old scheme)
        if isinstance(query, str):
            old_cached_data_filename = FNAMES.osm_old_cached(lat, lon, query)
            if os.path.isfile(old_cached_data_filename):
                UI.vprint(1, "    * Recycling OSM data for", query)
                osm_layer.update_dicosm(
                    old_cached_data_filename, input_tags, target_tags
                )
                continue
        UI.vprint(1, "    * Downloading OSM data for", query)
        response = get_overpass_data(query, (lat, lon, lat + 1, lon + 1))
        if UI.red_flag:
            return 0
        if not response:
            # A missing query leaves the whole layer incomplete (e.g. a tile
            # without any inland water), and nothing of it gets cached.
            # Raise the red flag so the build stops here instead of producing
            # a tile that looks fine but lacks data.
            UI.lvprint(
                0,
                "   ERROR: No valid answer for",
                query,
                "after",
                max_osm_tentatives,
                "tentatives (last:",
                (get_overpass_data.last_error or "unknown") + "). The",
                cached_suffix or "OSM",
                "layer would be incomplete, stopping.",
            )
            global overpass_gave_up
            overpass_gave_up = True
            UI.red_flag = True
            return 0
        osm_layer.update_dicosm(response, input_tags, target_tags)
    if cached_suffix:
        osm_layer.write_to_file(cached_data_filename)
    return 1


def OSM_query_to_OSM_layer(
    query,
    bbox,
    osm_layer,
    tags_of_interest=[],
    cached_file_name="",
):
    # this one is simpler and does not depend on the notion of tile
    target_tags = {"n": [], "w": [], "r": []}
    input_tags = {"n": [], "w": [], "r": []}
    for tag in [query] if isinstance(query, str) else query:
        items = tag.split('"')
        osm_type = items[0][0]
        try:
            target_tags[osm_type].append((items[1], items[3]))
            input_tags[osm_type].append((items[1], items[3]))
        except IndexError:
            target_tags[osm_type].append((items[1], ""))
            input_tags[osm_type].append((items[1], ""))
        for tag in tags_of_interest:
            if isinstance(tag, str):
                target_tags[osm_type].append((tag, ""))
            else:
                target_tags[osm_type].append(tag)
    if cached_file_name and os.path.isfile(cached_file_name):
        UI.vprint(1, "    * Recycling OSM data from", cached_file_name)
        osm_layer.update_dicosm(cached_file_name, input_tags, target_tags)
    else:
        response = get_overpass_data(query, bbox)
        if UI.red_flag:
            return 0
        if not response:
            UI.lvprint(
                1,
                "      No valid answer for",
                query,
                "after",
                max_osm_tentatives,
                "tentatives (last:",
                (get_overpass_data.last_error or "unknown") + "), skipping it.",
            )
            return 0
        osm_layer.update_dicosm(response, input_tags, target_tags)
        if cached_file_name:
            osm_layer.write_to_file(cached_file_name)
    return 1


def _pick_overpass_server(tentative: int, server_keys: list) -> str:
    """Return the server key to use for this tentative (1-based)."""
    if overpass_server_choice == "random":
        if len(server_keys) == 1:
            return server_keys[0]
        last_used = getattr(get_overpass_data, "last_key", None)
        other_keys = [k for k in server_keys if k != last_used]
        return random.choice(other_keys if other_keys else server_keys)
    if overpass_server_choice not in server_keys:
        UI.lvprint(
            1,
            "Selected overpass server not found in overpass_servers.txt, using:",
            server_keys[0],
        )
        return server_keys[0]
    # A fixed choice used to send all tentatives to the same server, so one
    # overloaded server failed the whole tile. Keep the chosen server for the
    # first half, then alternate with the others (odd tentatives).
    others = [k for k in server_keys if k != overpass_server_choice]
    if others and tentative > max_osm_tentatives // 2 and tentative % 2:
        fallback = others[(tentative // 2) % len(others)]
        UI.vprint(1, f"      Falling back to OSM server {fallback}")
        return fallback
    return overpass_server_choice


def overpass_answers() -> bool:
    """True if some configured Overpass server answers a tiny query now.

    Used by a batch to wait out an outage before it tries the tiles that
    lost step 1 to it again (#46): the query asks for the nodes of an
    empty box, so it costs the server nothing.
    """
    _prefer_ipv4_without_ipv6_route()
    s = requests.Session()
    s.headers.update(
        {"User-Agent": f"Ortho4XP/{O4XP_VERSION} (https://github.com/shred86/Ortho4XP)"}
    )
    for (key, url) in overpass_servers.items():
        slot = _acquire_overpass_slot()
        if slot is None:
            return False
        try:
            try:
                r = s.get(url + "?data=node(0,0,0,0);out;",
                          timeout=(overpass_timeout[0], 60))
            finally:
                _release_overpass_slot(slot)
        except requests.RequestException as e:
            UI.vprint(2, f"      Overpass check: {key}: {type(e).__name__}")
            continue
        if r.status_code == 200 and b"</osm>" in r.content[-20:]:
            UI.vprint(2, f"      Overpass check: {key} answers.")
            return True
        UI.vprint(2, f"      Overpass check: {key}: HTTP {r.status_code}")
    return False


def get_overpass_data(
    query: str, bbox: tuple, tentatives: int = 0, server_timeout: int = 0
) -> bytes:
    """Fetch data from OSM overpass servers.

    tentatives defaults to max_osm_tentatives; server_timeout, when given,
    is sent as [timeout:...] and the read timeout is raised to match.
    On failure returns 0 and leaves the reason of the last tentative in
    get_overpass_data.last_error, for the caller's error message.
    """
    get_overpass_data.last_error = ""
    if not overpass_servers:
        UI.lvprint(1, "No overpass servers configured. Check overpass_servers.txt.")
        return 0
    _prefer_ipv4_without_ipv6_route()
    s = requests.Session()
    s.headers.update(
        {"User-Agent": f"Ortho4XP/{O4XP_VERSION} (https://github.com/shred86/Ortho4XP)"}
    )
    server_keys = list(overpass_servers.keys())

    if isinstance(query, str):
        overpass_query = query + str(bbox) + ";"
    else:
        overpass_query = "".join(x + str(bbox) + ";" for x in query)
    settings, timeout = "", overpass_timeout
    if server_timeout:
        settings = f"[timeout:{server_timeout}];"
        timeout = (overpass_timeout[0], server_timeout + 10)

    for tentative in range(1, (tentatives or max_osm_tentatives) + 1):
        current_key = _pick_overpass_server(tentative, server_keys)
        get_overpass_data.last_key = current_key

        UI.vprint(2, f"      Using OSM server {current_key}")
        url = (
            overpass_servers[current_key]
            + "?data="
            + settings
            + "("
            + overpass_query
            + ");(._;>>;);out meta;"
        )
        UI.vprint(3, url)
        wait = 2**tentative
        slot = _acquire_overpass_slot()
        if slot is None:
            return 0
        try:
            try:
                r = s.get(url, timeout=timeout)
            finally:
                _release_overpass_slot(slot)
            if r.status_code == 200:
                if (
                    b"</osm>" not in r.content[-10:]
                    and b"</OSM>" not in r.content[-10:]
                ):
                    get_overpass_data.last_error = (
                        f"{current_key}: corrupted answer (no closing </osm> tag)"
                    )
                    UI.vprint(
                        1,
                        f"      OSM server {current_key} sent a corrupted answer ",
                        f"(no closing </osm> tag in answer), "
                        f"new tentative in {wait} sec...",
                    )
                elif len(r.content) <= 1000 and b"error" in r.content:
                    get_overpass_data.last_error = f"{current_key}: error answer"
                    UI.vprint(
                        1,
                        f"      OSM server {current_key} sent us an error code "
                        f"(data too big ?), new tentative in {wait} sec...",
                    )
                else:
                    return r.content
            else:
                if r.status_code == 429:  # 429 is overpass software rate limiting us
                    wait = max(int(r.headers.get("Retry-After", 0)), wait,
                               overpass_rate_limit_wait)
                get_overpass_data.last_error = f"{current_key}: HTTP {r.status_code}"
                UI.vprint(
                    1,
                    f"      OSM server {current_key} rejected our query "
                    f"(HTTP {r.status_code}), new tentative in {wait} sec...",
                )
        except Exception as e:
            # Name the actual error: a timeout, a refused connection and a
            # TLS problem need different remedies, "too busy" hid all three.
            get_overpass_data.last_error = f"{current_key}: {type(e).__name__}"
            UI.vprint(
                1,
                f"      OSM server {current_key} did not answer "
                f"({type(e).__name__}: {e}), new tentative in {wait} sec...",
            )
        if UI.red_flag:
            return 0
        time.sleep(wait)
    return 0


def OSM_to_MultiLineString(osm_layer, lat, lon, tags_for_exclusion=set(), filter=None):
    multiline = []
    multiline_reject = []
    todo = len(osm_layer.dicosmfirst["w"])
    step = int(todo / 100) + 1
    done = 0
    filtered_segs = 0
    for wayid in osm_layer.dicosmfirst["w"]:
        if done % step == 0:
            UI.progress_bar(1, int(100 * done / todo))
        if (
            tags_for_exclusion
            and wayid in osm_layer.dicosmtags["w"]
            and not set(osm_layer.dicosmtags["w"][wayid].keys()).isdisjoint(
                tags_for_exclusion
            )
        ):
            done += 1
            continue
        way = numpy.round(
            numpy.array(
                [osm_layer.dicosmn[nodeid] for nodeid in osm_layer.dicosmw[wayid]],
                dtype=numpy.float64,
            )
            - numpy.array([[lon, lat]], dtype=numpy.float64),
            7,
        )
        if filter and not filter(way, filtered_segs):
            try:
                multiline_reject.append(geometry.LineString(way))
            except (ShapelyError, ValueError):
                pass
            done += 1
            continue
        try:
            multiline.append(geometry.LineString(way))
            filtered_segs += len(way)
        except (ShapelyError, ValueError):
            pass
        done += 1
    UI.progress_bar(1, 100)
    if not filter:
        return geometry.MultiLineString(multiline)
    else:
        UI.vprint(2, "      Number of filtered segs :", filtered_segs)
        return (
            geometry.MultiLineString(multiline),
            geometry.MultiLineString(multiline_reject),
        )


def OSM_to_MultiPolygon(osm_layer, lat, lon, filter=None):
    multilist = []
    excludelist = []
    todo = len(osm_layer.dicosmfirst["w"]) + len(osm_layer.dicosmfirst["r"])
    step = int(todo / 100) + 1
    done = 0
    for wayid in osm_layer.dicosmfirst["w"]:
        if done % step == 0:
            UI.progress_bar(1, int(100 * done / todo))
        if osm_layer.dicosmw[wayid][0] != osm_layer.dicosmw[wayid][-1]:
            UI.logprint(
                "Non closed way starting at",
                osm_layer.dicosmn[osm_layer.dicosmw[wayid][0]],
                ", skipped.",
            )
            done += 1
            continue
        way = numpy.round(
            numpy.array(
                [osm_layer.dicosmn[nodeid] for nodeid in osm_layer.dicosmw[wayid]],
                dtype=numpy.float64,
            )
            - numpy.array([[lon, lat]], dtype=numpy.float64),
            7,
        )
        try:
            pol = geometry.Polygon(way)
            if not pol.area:
                continue
            if not pol.is_valid:
                UI.logprint(
                    "Invalid OSM way starting at",
                    osm_layer.dicosmn[osm_layer.dicosmw[wayid][0]],
                    ", skipped.",
                )
                done += 1
                continue
        except Exception as e:
            UI.vprint(2, e)
            done += 1
            continue
        if filter and filter(pol, wayid, osm_layer.dicosmtags["w"]):
            excludelist.append(pol)
        else:
            multilist.append(pol)
        done += 1
    for relid in osm_layer.dicosmfirst["r"]:
        if done % step == 0:
            UI.progress_bar(1, int(100 * done / todo))
        try:
            multiout = [
                geometry.Polygon(
                    numpy.round(
                        numpy.array(
                            [osm_layer.dicosmn[nodeid] for nodeid in nodelist],
                            dtype=numpy.float64,
                        )
                        - numpy.array([lon, lat], dtype=numpy.float64),
                        7,
                    )
                )
                for nodelist in osm_layer.dicosmr[relid]["outer"]
            ]
            multiout = ops.unary_union([geom for geom in multiout if geom.is_valid])
            multiin = [
                geometry.Polygon(
                    numpy.round(
                        numpy.array(
                            [osm_layer.dicosmn[nodeid] for nodeid in nodelist],
                            dtype=numpy.float64,
                        )
                        - numpy.array([lon, lat], dtype=numpy.float64),
                        7,
                    )
                )
                for nodelist in osm_layer.dicosmr[relid]["inner"]
            ]
            multiin = ops.unary_union([geom for geom in multiin if geom.is_valid])
        except Exception as e:
            UI.logprint(e)
            done += 1
            continue
        multipol = multiout.difference(multiin)
        if filter and filter(multipol, relid, osm_layer.dicosmtags["r"]):
            targetlist = excludelist
        else:
            targetlist = multilist
        for pol in (
            multipol.geoms
            if ("Multi" in multipol.geom_type or "Collection" in multipol.geom_type)
            else [multipol]
        ):
            if not pol.area:
                done += 1
                continue
            if not pol.is_valid:
                UI.logprint(
                    "Relation",
                    relid,
                    "contains an invalid polygon which was discarded",
                )
                done += 1
                continue
            targetlist.append(pol)
        done += 1
    if filter:
        ret_val = (
            geometry.MultiPolygon(multilist),
            geometry.MultiPolygon(excludelist),
        )
        UI.vprint(
            2,
            "    Total number of geometries:",
            len(ret_val[0].geoms),
            len(ret_val[1].geoms),
        )
    else:
        ret_val = geometry.MultiPolygon(multilist)
        UI.vprint(2, "    Total number of geometries:", len(ret_val.geoms))
    UI.progress_bar(1, 100)
    return ret_val
