"""Holes in the imagery provider's coverage (#116).

Batch B+D (2026-11-19): GO2 has nothing finer than ZL9 in parts of Kane
Basin (+79-070) and ZL12 at 82 N (+82-039's ZL18 airport cover). The 404
fallback to lower zoom levels stopped 5 levels down, so those textures
stayed white; each tile was then requeued 3 times as if GO2 were down, and
the imagery pause's probe, asking the middle of +79-070, got 404 every
time, so the batch waited the full 6 h, twice.
"""
from PIL import Image

import O4_Imagery_Utils as IMG
import O4_Tile_Utils as TILE

from test_imagery_gate import probes

PROVIDER = {"code": "T", "request_type": "tms", "grid_type": "webmercator",
            "url_template": "http://t/{zoom}/{x}/{y}", "tile_size": 256,
            # read by the {xcenter} placeholders, unused here
            "resolutions": [1.0] * 25, "top_left_corner": [[0, 0]] * 25}


def fake_server(monkeypatch, finest_zl, answer=None):
    """http_request_to_image: an image at zoom levels <= finest_zl (each
    pixel coloured by its column), 404 above; answer overrides all."""
    asked = []

    def request(width, height, url, headers, session):
        zl = int(url.split("/")[3])
        asked.append(zl)
        if answer is not None:
            return answer
        if zl > finest_zl:
            return (0, "<Response [404]>")
        im = Image.new("RGB", (width, height))
        im.putdata([(x, zl, 0) for y in range(height) for x in range(width)])
        return (1, im)

    monkeypatch.setattr(IMG, "http_request_to_image", request)
    return asked


# --- the fallback ---------------------------------------------------------------
def test_six_levels_down(monkeypatch):
    # +79-070: ZL15 asked, ZL9 the finest there (white before #116)
    asked = fake_server(monkeypatch, 9)
    report = IMG.ImageryReport()
    (ok, im) = IMG.get_wmts_image(15, 10057, 3934, PROVIDER, None, report)
    assert ok and im.size == (256, 256)
    assert asked == [15, 14, 13, 12, 11, 10, 9]
    assert (report.coarsest_zl, report.down_sample) == (9, 6)
    assert (report.no_data, report.failed) == (0, 0)
    assert im.getpixel((0, 0))[1] == 9  # cut from the ZL9 image


def test_eight_levels_down_is_one_pixel(monkeypatch):
    fake_server(monkeypatch, 10)
    report = IMG.ImageryReport()
    (ok, im) = IMG.get_wmts_image(18, 103392, 19296, PROVIDER, None, report)
    assert ok and report.down_sample == 8
    # 103392 % 256 = 224: column 224 of the ZL10 image, stretched
    assert {im.getpixel((x, 0))[0] for x in (0, 128, 255)} == {224}


def test_beyond_the_limit_is_no_data(monkeypatch):
    asked = fake_server(monkeypatch, 6)
    report = IMG.ImageryReport()
    (ok, im) = IMG.get_wmts_image(15, 10057, 3934, PROVIDER, None, report)
    assert not ok and im.getpixel((5, 5)) == (255, 255, 255)
    assert asked == list(range(15, 15 - IMG.MAX_DOWN_SAMPLE - 1, -1))
    assert (report.no_data, report.failed) == (1, 0)
    assert report.only_no_data()


def test_stops_at_zoom_level_zero(monkeypatch):
    asked = fake_server(monkeypatch, -1)
    report = IMG.ImageryReport()
    (ok, _) = IMG.get_wmts_image(2, 1, 1, PROVIDER, None, report)
    assert not ok and asked == [2, 1, 0] and report.only_no_data()


def test_other_failures_are_not_no_data(monkeypatch):
    fake_server(monkeypatch, 20, answer=(0, "Connection failure"))
    report = IMG.ImageryReport()
    (ok, _) = IMG.get_wmts_image(15, 1, 1, PROVIDER, None, report)
    assert not ok and (report.no_data, report.failed) == (0, 1)
    assert not report.only_no_data()
    report.missed(no_data=True)  # one hole and one failure: an outage
    assert not report.only_no_data()


def test_no_report_needed(monkeypatch):
    fake_server(monkeypatch, 9)
    assert IMG.get_wmts_image(15, 10057, 3934, PROVIDER, None)[0] == 1


# --- the probe ------------------------------------------------------------------
def test_probe_counts_no_data_as_an_answer(monkeypatch):
    monkeypatch.setattr(IMG, "providers_dict", {"T": PROVIDER})
    monkeypatch.setattr(IMG, "combined_providers_dict", {})
    fake_server(monkeypatch, -1)  # 404 everywhere: up, but no imagery
    assert IMG.provider_answers(79, -70, 15, "T") is True
    fake_server(monkeypatch, 20, answer=(0, "<Response [503]>"))
    assert IMG.provider_answers(79, -70, 15, "T") is False


def test_gate_probes_the_last_good_tile(lines, monkeypatch):
    asked = probes(monkeypatch, [True])
    gate = TILE._ImageryGate("GO2", 15)
    gate.failed(79, -70)
    gate.answered(64, -52)
    gate.failed(79, -71)
    gate.failed(82, -39)
    gate.poll([(79, -71), (82, -39)])
    gate.poll([(79, -71), (82, -39)])
    assert asked == [(64, -52, 15, "GO2")]
    assert gate.paused is None


def test_gate_probes_a_held_tile_without_a_good_one(lines, monkeypatch):
    asked = probes(monkeypatch, [False])
    gate = TILE._ImageryGate("GO2", 15)
    gate.failed(79, -70)
    gate.failed(79, -71)
    gate.poll([(79, -71)])
    assert asked == [(79, -71, 15, "GO2")]


# --- the texture and the tile ---------------------------------------------------
def texture(monkeypatch, tmp_path, fill):
    """download_jpeg_ortho of +79-070 with a builder that calls fill(report)
    and returns its success."""
    monkeypatch.setattr(IMG, "providers_dict", {"T": PROVIDER})
    for name in ("incomplete_imgs", "no_data_imgs", "coarse_imgs"):
        monkeypatch.setattr(IMG, name, {})

    def build(tilbox, zl, provider, progress=None, report=None):
        return (fill(report), Image.new("RGB", (4096, 4096), "white"))

    monkeypatch.setattr(IMG, "build_texture_from_tilbox", build)
    file_dir = tmp_path / "+79-070" / "T_15"
    assert IMG.download_jpeg_ortho(str(file_dir), "a.jpg", 0, 0, 15, "T")
    assert (file_dir / "a.jpg").is_file()
    return (IMG.incomplete_imgs, IMG.no_data_imgs, IMG.coarse_imgs)


def test_texture_with_a_hole(monkeypatch, tmp_path, lines):
    def fill(report):
        report.missed(no_data=True)
        return 0
    (white, no_data, coarse) = texture(monkeypatch, tmp_path, fill)
    assert white == {"+79-070": ["a.jpg"]}
    assert no_data == {"+79-070": ["a.jpg"]}
    assert coarse == {}


def test_texture_with_a_failure(monkeypatch, tmp_path, lines):
    def fill(report):
        report.missed(no_data=True)
        report.missed(no_data=False)
        return 0
    (white, no_data, _) = texture(monkeypatch, tmp_path, fill)
    assert white == {"+79-070": ["a.jpg"]} and no_data == {}


def test_texture_cut_from_far_below(monkeypatch, tmp_path, lines):
    def fill(report):
        report.got(9, 6)
        report.got(12, 3)
        return 1
    (white, _, coarse) = texture(monkeypatch, tmp_path, fill)
    assert white == {} and coarse == {"+79-070": {"a.jpg": 9}}


def test_texture_cut_from_a_little_below_is_quiet(monkeypatch, tmp_path,
                                                  lines):
    def fill(report):
        report.got(10, 5)  # the old limit reached that: no NOTE
        return 1
    assert texture(monkeypatch, tmp_path, fill)[2] == {}


def test_white_only_no_data():
    assert TILE.white_only_no_data(["a", "b"], ["b", "a", "c"])
    assert not TILE.white_only_no_data(["a", "b"], ["a"])
    assert not TILE.white_only_no_data([], [])
    assert not TILE.white_only_no_data([], ["a"])


def test_no_retry_for_a_hole(monkeypatch):
    calls = []

    def build_tile(tile, white_retry_follows=False):
        calls.append(white_retry_follows)
        IMG.incomplete_imgs["+79-070"] = ["a.jpg"]
        if hole:
            IMG.no_data_imgs["+79-070"] = ["a.jpg"]
        return 0

    class Tile:
        (lat, lon) = (79, -70)

    monkeypatch.setattr(TILE, "build_tile", build_tile)
    monkeypatch.setattr(IMG, "incomplete_imgs", {})
    monkeypatch.setattr(IMG, "no_data_imgs", {})
    hole = True
    assert TILE.build_tile_retrying_white(Tile()) == 0
    assert calls == [True]  # a second run would get the same 404s
    (hole, calls[:]) = (False, [])
    IMG.no_data_imgs.clear()
    assert TILE.build_tile_retrying_white(Tile()) == 0
    assert calls == [True, False]


def test_coarse_note(lines):
    class Tile:
        (lat, lon, default_website) = (82, -39, "GO2")

    TILE._note_coarse_imagery(Tile(), {})
    assert not lines
    TILE._note_coarse_imagery(Tile(), {"b.jpg": 12, "a.jpg": 11})
    assert any("NOTE: 2 texture(s) of tile +82-039" in l and "ZL11" in l
               and "GO2" in l and "a.jpg" in l for l in lines)
