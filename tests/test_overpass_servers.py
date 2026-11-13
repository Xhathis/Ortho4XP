"""Overpass server order, failure kinds and shared server health (#83)."""
import json
import os

import pytest

import O4_File_Names as FNAMES
import O4_OSM_Utils as OSM
import O4_UI_Utils as UI

DE, FR = "http://de", "http://fr"
OK = (b'<?xml version="1.0"?>\n<osm version="0.6">\n'
      b'<meta osm_base="2026-11-11T08:14:53Z"/>\n</osm>\n')
OLD = OK.replace(b"2026-11-11", b"2026-10-13")
REMARK = (b'<?xml version="1.0"?>\n<osm version="0.6">\n<node id="1"/>\n'
          + b"x" * 2000 + b'\n<remark> runtime error: Query run out of '
          b'memory </remark>\n</osm>\n')


class Resp:
    def __init__(self, status, content=b"", headers=None):
        self.status_code, self.content = status, content
        self.headers = headers or {}


@pytest.fixture
def net(monkeypatch):
    """Fake servers DE and FR: replies[url] is a list of Resp/exceptions
    (the last one repeats). Returns (asked urls, sleeps, log lines)."""
    monkeypatch.setattr(OSM, "overpass_servers", {"DE": DE, "FR": FR})
    monkeypatch.setattr(OSM, "overpass_server_choice", "DE")
    monkeypatch.setattr(OSM, "_prefer_ipv4_without_ipv6_route", lambda: None)
    monkeypatch.setattr(UI, "vprint", lambda *a: None)
    lines = []
    monkeypatch.setattr(UI, "lvprint",
                        lambda level, *a: lines.append(" ".join(map(str, a))))
    monkeypatch.setattr(UI, "red_flag", False)
    sleeps = []
    monkeypatch.setattr(OSM.time, "sleep", sleeps.append)
    asked = []
    replies = {}

    class Session:
        headers = {}

        def close(self):
            pass

        def get(self, url, timeout):
            base = url.split("?")[0]
            asked.append(base)
            todo = replies[base]
            reply = todo.pop(0) if len(todo) > 1 else todo[0]
            if isinstance(reply, Exception):
                raise reply
            return reply

    monkeypatch.setattr(OSM.requests, "Session", Session)
    yield replies, asked, sleeps, lines
    try:
        os.remove(OSM._health_path())
    except OSError:
        pass


def health():
    try:
        with open(OSM._health_path(), encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        return None


DOWN_ERR = OSM.requests.ConnectionError("refused")


def test_de_twice_then_fr(net):
    (replies, asked, sleeps, _) = net
    replies[DE] = [DOWN_ERR]
    replies[FR] = [Resp(200, OLD)]
    assert OSM.get_overpass_data("way", (1, 2, 3, 4)) == OLD
    assert asked == [DE, DE, FR]
    assert sleeps == [OSM.overpass_primary_retry_wait]
    assert OSM.get_overpass_data.last_source == ("FR", "2026-10-13T08:14:53Z")


def test_all_down_no_wait_after_last_try(net):
    (replies, asked, sleeps, _) = net
    replies[DE] = [DOWN_ERR]
    replies[FR] = [OSM.requests.ConnectTimeout("t")]
    assert OSM.get_overpass_data("way", (1, 2, 3, 4)) == 0
    assert asked == [DE, DE, FR]
    assert sleeps == [OSM.overpass_primary_retry_wait]  # none after FR
    assert OSM.get_overpass_data.last_error == "FR: ConnectTimeout"
    assert OSM.get_overpass_data.size_failure is False


def test_de_answers_first(net):
    (replies, asked, sleeps, _) = net
    replies[DE] = [Resp(200, OK)]
    assert OSM.get_overpass_data("way", (1, 2, 3, 4)) == OK
    assert asked == [DE] and sleeps == []
    assert health() is None  # nothing written when nothing failed


@pytest.mark.parametrize("reply, size", [
    (OSM.requests.ReadTimeout("r"), True),
    (Resp(200, REMARK), True),  # partial data with a remark: not complete
    (Resp(200, b'<osm version="0.6"><node id="1"/>'), True),  # cut
    (Resp(504, b"Gateway"), False),
    (Resp(503, b""), False),
    # FR since 2026-11: refuses everyone not white-listed (#101): no
    # per-query fallback, which would only be refused again.
    (Resp(403, b"This service is only available to white-listed usages"),
     False),
    (Resp(401, b""), False),
])
def test_failure_kinds(net, reply, size):
    (replies, asked, _, _) = net
    replies[DE] = [reply]
    replies[FR] = [reply]
    assert OSM.get_overpass_data("way", (1, 2, 3, 4)) == 0
    assert OSM.get_overpass_data.size_failure is size


def test_429_waits_before_second_try(net):
    (replies, asked, sleeps, _) = net
    replies[DE] = [Resp(429, b"", {"Retry-After": "120"}), Resp(200, OK)]
    assert OSM.get_overpass_data("way", (1, 2, 3, 4)) == OK
    assert sleeps == [120]


def test_dead_server_skipped_by_all(net, monkeypatch):
    (replies, asked, _, lines) = net
    clock = [1000.0]
    monkeypatch.setattr(OSM.time, "time", lambda: clock[0])
    replies[DE] = [DOWN_ERR]
    replies[FR] = [Resp(200, OLD)]
    OSM.get_overpass_data("way", (1, 2, 3, 4))  # DE fails 2 times
    assert health()[DE]["fails"] == 2
    asked.clear()
    OSM.get_overpass_data("way", (1, 2, 3, 4))  # 3rd failure: skipped
    assert asked == [DE, FR]
    assert any("leave it out" in l for l in lines)
    assert health()[DE]["skip_until"] == 1000.0 + OSM.overpass_skip_time
    asked.clear()
    OSM.get_overpass_data("way", (1, 2, 3, 4))
    assert asked == [FR]  # DE left out, no request at all
    # After the skip time: one try; a failure skips it again at once.
    clock[0] += OSM.overpass_skip_time + 1
    asked.clear()
    OSM.get_overpass_data("way", (1, 2, 3, 4))
    assert asked == [DE, FR]
    assert health()[DE]["skip_until"] > clock[0]
    # A success clears it.
    clock[0] += OSM.overpass_skip_time + 1
    replies[DE] = [Resp(200, OK)]
    OSM.get_overpass_data("way", (1, 2, 3, 4))
    assert DE not in health()


def test_size_failures_do_not_skip(net):
    (replies, asked, _, _) = net
    replies[DE] = [Resp(200, REMARK)]
    replies[FR] = [Resp(200, REMARK)]
    for _ in range(3):
        OSM.get_overpass_data("way", (1, 2, 3, 4))
    assert health() is None


def test_all_skipped(net, monkeypatch):
    (replies, asked, _, _) = net
    for url in (DE, FR):
        OSM._with_health(lambda h, u=url: (h.update(
            {u: {"fails": 0, "skip_until": OSM.time.time() + 100,
                 "probation": True}}), True)[1:] + (True,))
    assert OSM.get_overpass_data("way", (1, 2, 3, 4)) == 0
    assert asked == []
    assert "skipped" in OSM.get_overpass_data.last_error


def test_probe_clears_skip(net):
    (replies, asked, _, _) = net
    OSM._with_health(lambda h: (h.update(
        {DE: {"fails": 0, "skip_until": OSM.time.time() + 100,
              "probation": True}}), True)[1:] + (True,))
    count = (b'<?xml version="1.0"?>\n<osm version="0.6">\n'
             b'<count id="0"><tag k="total" v="3"/></count>\n</osm>\n')
    replies[DE] = [Resp(200, count)]
    assert OSM.overpass_answers((1, 2, 3, 4))
    assert asked == [DE]  # the probe asks skipped servers too
    assert DE not in health()


def test_broken_health_file(net):
    (replies, asked, _, _) = net
    os.makedirs(FNAMES.OSM_dir, exist_ok=True)
    with open(OSM._health_path(), "w") as f:
        f.write("{not json")
    replies[DE] = [Resp(200, OK)]
    assert OSM.get_overpass_data("way", (1, 2, 3, 4)) == OK


# --- layers -----------------------------------------------------------------
WATER = ['rel["natural"="water"]', 'way["natural"="water"]']


@pytest.fixture
def layer(net, monkeypatch):
    monkeypatch.setattr(OSM, "overpass_gave_up", False)
    monkeypatch.setattr(OSM.FNAMES, "osm_cached",
                        lambda lat, lon, s: os.path.join("nowhere", s))
    monkeypatch.setattr(OSM.FNAMES, "osm_old_cached",
                        lambda lat, lon, q: os.path.join("nowhere", "old"))
    yield net
    UI.red_flag = False


def test_layer_down_no_per_query_requests(layer):
    (replies, asked, _, lines) = layer
    replies[DE] = [DOWN_ERR]
    replies[FR] = [DOWN_ERR]
    assert OSM.OSM_queries_to_OSM_layer(
        WATER, OSM.OSM_layer(), 55, 12, cached_suffix="") == 0
    assert asked == [DE, DE, FR]  # the combined request only
    assert OSM.overpass_gave_up and UI.red_flag
    assert any("the combined request from any Overpass server (last: FR: "
               "ConnectionError)" in l for l in lines)


def test_layer_too_big_falls_back_per_query(layer):
    (replies, asked, _, lines) = layer
    replies[DE] = [OSM.requests.ReadTimeout("r"), OSM.requests.ReadTimeout("r"),
                   Resp(200, OK)]
    replies[FR] = [Resp(200, REMARK)]
    assert OSM.OSM_queries_to_OSM_layer(
        WATER, OSM.OSM_layer(), 55, 12, cached_suffix="") == 1
    assert asked == [DE, DE, FR, DE, DE]  # combined, then 2 queries on DE


def test_old_data_noted(layer):
    (replies, asked, _, lines) = layer
    replies[DE] = [DOWN_ERR]
    replies[FR] = [Resp(200, OLD)]
    assert OSM.OSM_queries_to_OSM_layer(
        WATER, OSM.OSM_layer(), 55, 12, cached_suffix="water") == 1
    note = [l for l in lines if "NOTE" in l]
    assert len(note) == 1 and "water layer of +55+012" in note[0]
    assert "2026-10-13 from server FR" in note[0]


def test_data_age_days():
    import datetime
    now = datetime.datetime(2026, 11, 11, 8, tzinfo=datetime.timezone.utc)
    assert OSM.data_age_days("2026-10-13T08:00:00Z", now) == pytest.approx(29)
    assert OSM.data_age_days("", now) is None
    assert OSM.data_age_days("garbage", now) is None
    assert OSM.osm_base_of(OK) == "2026-11-11T08:14:53Z"
    assert OSM.osm_base_of(b"<osm/>") == ""


# --- inconsistent answers (#99) ---------------------------------------------
# FR, 2026-11-11: ways naming nodes deleted from its database (KeyError in
# update_dicosm, 17 tiles failed for good instead of being retried).
def _answer(nodes, refs, q=b'"'):
    body = b"".join(b"<node id=%s%d%s lat=%s1%s lon=%s2%s/>\n"
                    % (q, n, q, q, q, q, q) for n in nodes)
    body += (b"<way id=%s7%s>\n" % (q, q)
             + b"".join(b"<nd ref=%s%d%s/>\n" % (q, r, q) for r in refs)
             + b"</way>\n")
    return OK.replace(b"</osm>", body + b"</osm>")


BROKEN = _answer([1, 2], [1, 29171402, 2, 1])
GOOD = _answer([1, 2, 3], [1, 2, 3, 1])


def test_dangling_node_refs():
    assert OSM.dangling_node_refs(GOOD) == []
    assert OSM.dangling_node_refs(OK) == []  # no ways at all
    assert OSM.dangling_node_refs(BROKEN) == [b"29171402"]
    assert OSM.dangling_node_refs(_answer([1], [1, 5, 5, 6], q=b"'")) == [
        b"5", b"6"]
    many = _answer([], range(10, 20))
    assert OSM.dangling_node_refs(many) == [b"10", b"11", b"12"]


def test_inconsistent_answer_tries_next_server(net):
    (replies, asked, _, _) = net
    replies[DE] = [Resp(200, BROKEN)]
    replies[FR] = [Resp(200, GOOD)]
    assert OSM.get_overpass_data("way", (1, 2, 3, 4)) == GOOD
    assert asked == [DE, DE, FR]
    assert health() is None  # not a reason to skip DE


def test_inconsistent_answers_fail_layer_for_a_retry(layer):
    (replies, asked, _, lines) = layer
    replies[DE] = [DOWN_ERR]
    replies[FR] = [Resp(200, BROKEN)]
    osm_layer = OSM.OSM_layer()
    assert OSM.OSM_queries_to_OSM_layer(
        WATER, osm_layer, 55, 12, cached_suffix="") == 0
    assert asked == [DE, DE, FR]  # same database: no per-query fallback
    assert OSM.get_overpass_data.size_failure is False
    assert OSM.overpass_gave_up and UI.red_flag  # the batch requeues it
    assert any("(last: FR: inconsistent answer (missing node 29171402))"
               in l for l in lines)
    assert not osm_layer.dicosmw  # nothing half-read


def test_consistent_answer_still_read(layer):
    (replies, asked, _, _) = layer
    replies[DE] = [Resp(200, GOOD)]
    osm_layer = OSM.OSM_layer()
    assert OSM.OSM_queries_to_OSM_layer(
        WATER, osm_layer, 55, 12, cached_suffix="") == 1
    assert [len(w) for w in osm_layer.dicosmw.values()] == [4]
