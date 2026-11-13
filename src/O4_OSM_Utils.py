import os
import sys
import time
import datetime
import json
import re
import io
import bz2
import random
import requests
import numpy
from shapely import geometry, ops
from shapely.errors import ShapelyError
import O4_UI_Utils as UI
import O4_File_Names as FNAMES
import O4_OSM_Extract as EXTRACT
from O4_Version import version as O4XP_VERSION

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

# Default overpass_server_choice if not in config
overpass_server_choice = "random"
# Overpass gives a query 180 s by default before it answers, and sends
# nothing until then, so a 60 s read timeout cut off slow but valid
# answers (large residential layers) on every tentative.
overpass_timeout = (10, 190)  # (connect, read) in seconds
# A layer with several queries (roads, water) goes out as one union request:
# fewer slow round trips, and a way matched by two queries comes back once
# instead of being stored twice. It gets more server time, and falls back to
# one request per query when it keeps failing.
layer_request_server_timeout = 300  # seconds, sent as [timeout:...]
# Server order and failures (#83). Before, a layer went 4 times to the
# configured server as one request, then each query 8 times (FR only on the
# 5th and 7th), with waits up to 256 s, also after the last try: up to ~55
# min and 12 requests before a layer failed, and every worker and layer
# found out on its own that DE was down. Now the configured server gets
# overpass_primary_tries tries, then each other server one; the
# per-query fallback only when a server connected but could not do the
# request (size or timeout), not when it is down; and a server failing
# overpass_skip_after times in a row (any process) is left out by all for
# overpass_skip_time. The batch pauses on the first tile that fails (#81).
overpass_primary_tries = 2
overpass_primary_retry_wait = 10  # seconds between them
overpass_skip_after = 3
overpass_skip_time = 900  # seconds
OVERPASS_HEALTH_FILE = ".overpass_health.json"  # in OSM_data, shared
# A downloaded layer whose data (osm_base) is older than this many days is
# logged with its server and date: FR was a month behind on 2026-11-11.
overpass_stale_days = 2
# After an HTTP 429 the server wants us to slow down; retrying within a few
# seconds (2, 4, 8 s) got the connection reset by overpass-api.de.
overpass_rate_limit_wait = 60  # seconds, at least
# Overpass requests running at once across all Ortho4XP processes (#80).
# overpass-api.de grants two per IP ("Rate limit: 2" on /api/status); with
# one, the good hours of the 346-tile batch of 2026-11-08 were already at
# the limit (60-87 layer downloads an hour at ~50 s each). Three at once
# got HTTP 429 (#30).
overpass_max_parallel = 2
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


def _overpass_lock_names():
    """Lock file names, one per allowed concurrent request.

    The first keeps the name of the single lock used before (#30), so an
    older Ortho4XP still running at the same time shares that slot.
    """
    return [".overpass.lock"] + [
        f".overpass.lock{i}" for i in range(1, max(1, overpass_max_parallel))
    ]


def _acquire_overpass_slot():
    """Wait for a free Overpass slot (shared by all Ortho4XP processes).

    Parallel batch workers each download their own tile's OSM data; three
    at once got HTTP 429 and then connection resets from overpass-api.de.
    At most overpass_max_parallel requests run at once, across processes:
    one lock file per slot. The OS releases a lock when its process ends,
    also when it is killed (Stop button). Returns the open lock file of the
    slot, or None if the build was stopped while waiting.
    """
    os.makedirs(FNAMES.OSM_dir, exist_ok=True)
    files = [open(os.path.join(FNAMES.OSM_dir, name), "a+")
             for name in _overpass_lock_names()]
    waiting = False
    while True:
        for f in files:
            try:
                _lock_file(f)
            except OSError:
                continue
            for other in files:
                if other is not f:
                    other.close()
            return f
        if UI.red_flag:
            for f in files:
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
                if target_tags is None:
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


################################################################################
def read_custom_osm_dir(osm_layer, src_dir, merged_file):
    """Read every OSM file of a custom coastline/water folder into osm_layer.

    The merged result is written to merged_file once, after all files were
    read (it was rewritten after each one), and only when every file could
    be read: the merged file is used instead of the folder from then on, so
    a cut or broken input file would have been cached for good. Returns
    True when all files were read.
    """
    for osm_file in os.listdir(src_dir):
        UI.vprint(2, "      ", osm_file)
        if not osm_layer.update_dicosm(
            os.path.join(src_dir, osm_file), input_tags=None, target_tags=None
        ):
            UI.lvprint(
                0, "   ERROR: Could not read the custom OSM file",
                os.path.join(src_dir, osm_file) + ", stopping.",
            )
            return False
    if not osm_layer.write_to_file(merged_file):
        # The layer itself is complete; only the shortcut for the next run
        # is missing.
        UI.lvprint(1, "WARNING: Could not write", merged_file)
    return True


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
    if cached_suffix and _layer_from_extract(
            queries, osm_layer, lat, lon, input_tags, target_tags,
            cached_suffix, cached_data_filename):
        return 1
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
            server_timeout=layer_request_server_timeout,
        )
        if UI.red_flag:
            return 0
        if response:
            _note_old_data(cached_suffix, lat, lon, [_last_source()])
            osm_layer.update_dicosm(response, input_tags, target_tags)
            if cached_suffix:
                osm_layer.write_to_file(cached_data_filename)
            return 1
        if not getattr(get_overpass_data, "size_failure", False):
            # No server could be reached at all: one request per query
            # would only ask the same dead servers more often (#83).
            return _overpass_layer_failed(cached_suffix, "the combined request")
        UI.vprint(
            1,
            "      No answer for the combined request (last:",
            (get_overpass_data.last_error or "unknown") + "),",
            "falling back to one request per query.",
        )
    sources = []
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
            return _overpass_layer_failed(cached_suffix, query)
        sources.append(_last_source())
        osm_layer.update_dicosm(response, input_tags, target_tags)
    _note_old_data(cached_suffix, lat, lon, sources)
    if cached_suffix:
        osm_layer.write_to_file(cached_data_filename)
    return 1


def _layer_from_extract(queries, osm_layer, lat, lon, input_tags, target_tags,
                        cached_suffix, cached_data_filename):
    """Read the layer from a local extract answer (prepare_osm_extracts.py,
    #100) instead of Overpass: the same reader and cache writer as a
    download. False when there is none, or it does not fit these queries
    (then Overpass, as before)."""
    path = EXTRACT.answer_path(lat, lon, cached_suffix)
    (content, source) = EXTRACT.read_answer(
        path, EXTRACT.flat_statements(queries))
    if content is None:
        if source:
            UI.lvprint(1, "   WARNING: local OSM extract answer", path,
                       "not used:", source + "; asking Overpass.")
        return False
    UI.vprint(1, "    * Reading OSM data for", cached_suffix,
              "from the local extract", f"({source})")
    if not osm_layer.update_dicosm(content, input_tags, target_tags):
        return False
    _note_old_data(cached_suffix, lat, lon,
                   [("local extract", osm_base_of(content))])
    osm_layer.write_to_file(cached_data_filename)
    return True


def _last_source():
    """(server, osm_base) of the last answer (tests may stub the request)."""
    return getattr(get_overpass_data, "last_source", ("", ""))


def _overpass_layer_failed(cached_suffix, what):
    """Stop the build: a layer without an answer from any server.

    A missing query leaves the whole layer incomplete (e.g. a tile without
    any inland water), and nothing of it gets cached. Raise the red flag so
    the build stops here instead of producing a tile that looks fine but
    lacks data; a batch puts the tile aside (overpass_gave_up, #44, #81).
    """
    UI.lvprint(
        0,
        "   ERROR: No valid answer for",
        what,
        "from any Overpass server (last:",
        (get_overpass_data.last_error or "unknown") + "). The",
        cached_suffix or "OSM",
        "layer would be incomplete, stopping.",
    )
    global overpass_gave_up
    overpass_gave_up = True
    UI.red_flag = True
    return 0


def _note_old_data(cached_suffix, lat, lon, sources):
    """Log a downloaded layer whose data is old (a lagging server, #83).

    sources: (server, osm_base) of each answer that made up the layer. The
    cache file does not record where its data came from; this log line is
    the only trace, so a tile can be checked (check_osm_cache.py) or
    rebuilt once the server has caught up.
    """
    old = [(key, base, age) for (key, base) in sources
           for age in [data_age_days(base)]
           if age is not None and age > overpass_stale_days]
    if not old:
        return
    (key, base, age) = max(old, key=lambda o: o[2])
    UI.lvprint(
        0, "   NOTE: OSM", cached_suffix or "", "layer of",
        FNAMES.short_latlon(lat, lon), f"has data of {base[:10]} from server",
        f"{key} ({age:.0f} days old).",
    )


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
                "from any Overpass server (last:",
                (get_overpass_data.last_error or "unknown") + "), skipping it.",
            )
            return 0
        osm_layer.update_dicosm(response, input_tags, target_tags)
        if cached_file_name:
            osm_layer.write_to_file(cached_file_name)
    return 1


def _server_order(server_keys, shuffle=True) -> list:
    """The servers in the order a request asks them (#83).

    The configured overpass_server_choice first ("random": a random order,
    or the file order with shuffle=False), then the others in
    overpass_servers.txt order.
    """
    keys = list(server_keys)
    if overpass_server_choice == "random":
        if not shuffle:
            return keys
        random.shuffle(keys)
        return keys
    if overpass_server_choice in keys:
        keys.remove(overpass_server_choice)
        keys.insert(0, overpass_server_choice)
    elif keys:
        UI.vprint(
            1, "Selected overpass server not found in overpass_servers.txt, "
            "using:", keys[0],
        )
    return keys


# Kinds of failed requests (#83). DOWN: no connection, HTTP 401/403/429/5xx - the
# server is unavailable, a smaller request would fail the same way. TIMEOUT:
# connected but no answer in time - overloaded, or the request was too big.
# SIZE: the server answered that it could not do the request (a <remark>,
# an error answer, a cut answer) - one request per query may work. DOWN and
# TIMEOUT count towards skipping the server; TIMEOUT and SIZE allow the
# one-request-per-query fallback of a layer. BROKEN: a complete answer that
# contradicts itself (a way naming a node the answer lacks, #99) - the
# server's database is mid-update; neither skips the server (its other
# answers may be fine) nor falls back per query (same database).
DOWN, TIMEOUT, SIZE, BROKEN = "down", "timeout", "size", "broken"

_NODE_ID = re.compile(rb'<node id=["\'](-?\d+)')
_ND_REF = re.compile(rb'<nd ref=["\'](-?\d+)')


def dangling_node_refs(content, limit=3):
    """Node ids that ways of an OSM answer refer to but the answer lacks.

    Overpass's (._;>>;) sends every node of every way, so a missing one
    means the server's database is inconsistent (FR, 2026-11-11, catching
    up: nodes deleted on 10-20/21 gone, the ways still naming them), and
    update_dicosm would crash with KeyError. Returns up to limit ids
    (bytes), empty when the answer is consistent. Streams the refs: one
    set of node ids only (largest cached layer: ~6 s, ~160 MB).
    """
    nodes = set(m.group(1) for m in _NODE_ID.finditer(content))
    missing = []
    for m in _ND_REF.finditer(content):
        if m.group(1) not in nodes and m.group(1) not in missing:
            missing.append(m.group(1))
            if len(missing) >= limit:
                break
    return missing


def _health_path():
    return os.path.join(FNAMES.OSM_dir, OVERPASS_HEALTH_FILE)


def _with_health(change):
    """Run change(health) on the shared server health record, under a lock.

    health maps a server URL to {"fails": n, "skip_until": time,
    "probation": bool}; change returns (result, changed) and the file is
    only written when changed (a cached build never writes it). Shared by
    all Ortho4XP processes of a parallel batch, so one dead server is found
    out once, not by every worker and layer on its own. Any OSError: the
    record is treated as empty and not written (requests still go out).
    """
    path = _health_path()
    try:
        os.makedirs(FNAMES.OSM_dir, exist_ok=True)
        lock = open(path + ".lock", "a+")
    except OSError:
        return change({})[0]
    locked = False
    try:
        for _ in range(200):
            try:
                _lock_file(lock)
                locked = True
                break
            except OSError:
                time.sleep(0.05)
        else:
            return change({})[0]  # never blocks a download for long
        try:
            with open(path, "r", encoding="utf-8") as f:
                health = json.load(f)
            if not isinstance(health, dict):
                health = {}
        except (OSError, ValueError):
            health = {}
        (result, changed) = change(health)
        if changed:
            tmp = path + ".tmp"
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(health, f)
                os.replace(tmp, path)
            except OSError as e:
                UI.vprint(1, f"      Could not write {path}: {e}")
        return result
    finally:
        if locked:
            _release_overpass_slot(lock)
        else:
            lock.close()


def _skipped_servers():
    """{url: skip_until} of the servers to leave out for now."""
    now = time.time()

    def change(health):
        return ({url: entry.get("skip_until", 0)
                 for (url, entry) in health.items()
                 if isinstance(entry, dict)
                 and entry.get("skip_until", 0) > now}, False)

    return _with_health(change)


def _record_server(url, failed):
    """Record a request's result; True when the server starts being skipped.

    overpass_skip_after DOWN/TIMEOUT failures in a row (from any process)
    skip it for overpass_skip_time; afterwards it is on probation: the next
    failure skips it again at once, a success clears it.
    """
    now = time.time()

    def change(health):
        entry = health.get(url)
        if not isinstance(entry, dict):
            entry = {}
        if not failed:
            if not entry:
                return (False, False)
            del health[url]
            return (False, True)
        if entry.get("skip_until", 0) > now:
            return (False, False)  # another process skipped it meanwhile
        fails = entry.get("fails", 0) + 1
        if entry.get("probation") or fails >= overpass_skip_after:
            health[url] = {"fails": 0, "skip_until": now + overpass_skip_time,
                           "probation": True}
            return (True, True)
        health[url] = {"fails": fails, "skip_until": 0,
                       "probation": False}
        return (False, True)

    return _with_health(change)


_OSM_BASE = re.compile(rb'osm_base="([^"]+)"')


def osm_base_of(content) -> str:
    """The data date (osm_base) of an Overpass answer, or ""."""
    m = _OSM_BASE.search(content[:2000]) if content else None
    return m.group(1).decode("ascii", "replace") if m else ""


def data_age_days(osm_base, now=None):
    """Age in days of an osm_base date, or None if it cannot be read."""
    try:
        when = datetime.datetime.fromisoformat(osm_base.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=datetime.timezone.utc)
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return (now - when).total_seconds() / 86400


def overpass_answers(bbox=None) -> bool:
    """True if some configured Overpass server answers a small query now.

    Used by a batch to wait out an outage before it starts the tiles held
    back by it (#46, #81). Without bbox the query asks for the nodes of an
    empty box, which costs the server nothing. With bbox (lat0, lon0,
    lat1, lon1) it counts the aeroway elements there, a real database
    query: on 2026-11-10 an overloaded DE answered the empty one while real
    requests kept failing, and the batch spent 20 h retrying (#78). Asks
    every server, skipped ones too: a server that answers is no longer
    skipped (#83).
    """
    _prefer_ipv4_without_ipv6_route()
    s = requests.Session()
    s.headers.update(
        {"User-Agent": f"Ortho4XP/{O4XP_VERSION} (https://github.com/shred86/Ortho4XP)"}
    )
    if bbox:
        query = f'[out:xml][timeout:60];nwr["aeroway"]{tuple(bbox)};out count;'
        read_timeout = 90
    else:
        query, read_timeout = "node(0,0,0,0);out;", 60
    try:
        for key in _server_order(overpass_servers, shuffle=False):
            url = overpass_servers[key]
            slot = _acquire_overpass_slot()
            if slot is None:
                return False
            try:
                try:
                    r = s.get(url + "?data=" + query,
                              timeout=(overpass_timeout[0], read_timeout))
                finally:
                    _release_overpass_slot(slot)
            except requests.RequestException as e:
                UI.vprint(2, f"      Overpass check: {key}: {type(e).__name__}")
                continue
            # Overpass reports a timeout or an overload with HTTP 200 and a
            # <remark>: that is no answer.
            if (
                r.status_code == 200
                and b"</osm>" in r.content[-20:]
                and b"<remark>" not in r.content
                and (not bbox or b"<count" in r.content)
            ):
                UI.vprint(2, f"      Overpass check: {key} answers.")
                _record_server(url, failed=False)
                return True
            UI.vprint(2, f"      Overpass check: {key}: HTTP {r.status_code}")
        return False
    finally:
        s.close()


def _overpass_request(session, key, url, timeout):
    """One request: (content, None, "") or (0, kind, reason, wait)."""
    slot = _acquire_overpass_slot()
    if slot is None:
        return (0, None, "stopped", 0)
    try:
        try:
            r = session.get(url, timeout=timeout)
        finally:
            _release_overpass_slot(slot)
    except requests.ReadTimeout as e:
        UI.vprint(1, f"      OSM server {key} did not answer in time ({e})")
        return (0, TIMEOUT, "ReadTimeout", 0)
    except Exception as e:
        # Name the actual error: a timeout, a refused connection and a TLS
        # problem need different remedies, "too busy" hid all three.
        UI.vprint(
            1, f"      OSM server {key} did not answer ({type(e).__name__}: {e})"
        )
        return (0, DOWN, type(e).__name__, 0)
    if r.status_code != 200:
        UI.vprint(
            1, f"      OSM server {key} rejected our query (HTTP {r.status_code})"
        )
        if r.status_code == 429:  # Overpass rate limiting us
            try:
                retry_after = int(r.headers.get("Retry-After", 0))
            except ValueError:
                retry_after = 0
            return (0, DOWN, "HTTP 429",
                    max(retry_after, overpass_rate_limit_wait))
        # 401/403: the server refuses us (FR since 2026-11: "only available
        # to white-listed usages"); a smaller request is refused the same.
        refused = r.status_code >= 500 or r.status_code in (401, 403)
        kind = DOWN if refused else SIZE
        return (0, kind, f"HTTP {r.status_code}", 0)
    if b"</osm>" not in r.content[-10:] and b"</OSM>" not in r.content[-10:]:
        UI.vprint(1, f"      OSM server {key} sent a cut answer (no </osm>)")
        return (0, SIZE, "corrupted answer (no closing </osm> tag)", 0)
    # A <remark> is Overpass saying the query failed (timeout, out of
    # memory); the answer may still carry part of the data, which used to
    # pass as complete when it was over 1000 bytes.
    if b"<remark>" in r.content or (
            len(r.content) <= 1000 and b"error" in r.content):
        UI.vprint(1, f"      OSM server {key} could not run the query "
                  "(remark or error in its answer)")
        return (0, SIZE, "error answer", 0)
    missing = dangling_node_refs(r.content)
    if missing:
        ids = ", ".join(i.decode() for i in missing)
        UI.vprint(1, f"      OSM server {key} sent ways with nodes missing "
                  f"from its answer (e.g. node {ids}): its data is "
                  "inconsistent")
        return (0, BROKEN, f"inconsistent answer (missing node {ids})", 0)
    return (r.content, None, "", 0)


def get_overpass_data(query, bbox: tuple, server_timeout: int = 0) -> bytes:
    """Fetch data from the Overpass servers (#83).

    The first server (overpass_server_choice) gets overpass_primary_tries
    tries, overpass_primary_retry_wait seconds apart (after HTTP 429 at
    least overpass_rate_limit_wait), then each other server one. Servers
    skipped after repeated failures (_record_server, shared by all
    processes) are left out. No wait after the last try: the caller or
    the batch decides what comes next. server_timeout, when given, is sent
    as [timeout:...] and the read timeout is raised to match.

    Returns the answer, or 0. Sets get_overpass_data.last_error (reason of
    the last try), .size_failure (some server connected but could not do
    the request, so smaller requests may work) and .last_source ((server,
    osm_base) of the answer).
    """
    get_overpass_data.last_error = ""
    get_overpass_data.size_failure = False
    get_overpass_data.last_source = ("", "")
    if not overpass_servers:
        UI.lvprint(1, "No overpass servers configured. Check overpass_servers.txt.")
        get_overpass_data.last_error = "no server configured"
        return 0
    if isinstance(query, str):
        overpass_query = query + str(bbox) + ";"
    else:
        overpass_query = "".join(x + str(bbox) + ";" for x in query)
    settings, timeout = "", overpass_timeout
    if server_timeout:
        settings = f"[timeout:{server_timeout}];"
        timeout = (overpass_timeout[0], server_timeout + 10)
    skipped = _skipped_servers()
    plan = []
    for key in _server_order(overpass_servers):
        if overpass_servers[key] in skipped:
            UI.vprint(1, f"      Skipping OSM server {key} (failed repeatedly, "
                      "until " + time.strftime(
                          "%H:%M", time.localtime(skipped[overpass_servers[key]]))
                      + ")")
            continue
        plan += [key] * (overpass_primary_tries if not plan else 1)
    if not plan:
        get_overpass_data.last_error = "all servers skipped after repeated failures"
        return 0
    _prefer_ipv4_without_ipv6_route()
    s = requests.Session()
    s.headers.update(
        {"User-Agent": f"Ortho4XP/{O4XP_VERSION} (https://github.com/shred86/Ortho4XP)"}
    )
    try:
        wait = 0
        dropped = set()  # servers skipped since this request started
        for (n, key) in enumerate(plan):
            url = overpass_servers[key]
            if key in dropped:
                continue
            if n:
                if key == plan[n - 1]:
                    if url in _skipped_servers():  # by another process
                        continue
                    wait = max(wait, overpass_primary_retry_wait)
                    UI.vprint(1, f"      New try on {key} in {wait} sec...")
                    time.sleep(wait)
                else:
                    UI.vprint(1, f"      Trying OSM server {key}")
                if UI.red_flag:
                    return 0
            UI.vprint(2, f"      Using OSM server {key}")
            full_url = (url + "?data=" + settings + "(" + overpass_query
                        + ");(._;>>;);out meta;")
            UI.vprint(3, full_url)
            (content, kind, reason, wait) = _overpass_request(
                s, key, full_url, timeout)
            if content:
                _record_server(url, failed=False)
                get_overpass_data.last_source = (key, osm_base_of(content))
                return content
            if kind is None:  # stopped while waiting for the slot
                return 0
            get_overpass_data.last_error = f"{key}: {reason}"
            if kind in (TIMEOUT, SIZE):
                get_overpass_data.size_failure = True
            if kind in (DOWN, TIMEOUT) and _record_server(url, failed=True):
                dropped.add(key)
                UI.lvprint(
                    0, f"Overpass server {key} failed repeatedly: all "
                    "Ortho4XP processes leave it out for "
                    f"{UI.nicer_timer(overpass_skip_time)}.",
                )
            if UI.red_flag:
                return 0
        return 0
    finally:
        s.close()


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
