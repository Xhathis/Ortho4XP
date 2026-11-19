"""Fallback providers for pieces the texture's provider lacks (#117).

Where GO2 drops 2-3 zoom levels (a quarter of the Arctic ZL15 textures
sampled on 2026-11-19) its pieces are a few blocks each, while Arc has
sharp imagery at the asked level; at +82-039 Bing has ZL15 where GO2 has
ZL12. Such a piece is now asked from imagery_fallback (Arc, then Bing)
at the asked level before the provider's own lower levels.
"""
from PIL import Image
import pytest

import O4_Cfg_Vars as CFGV
import O4_Imagery_Utils as IMG
import O4_Tile_Utils as TILE


def provider(code, **extra):
    return {"code": code, "request_type": "tms", "grid_type": "webmercator",
            "url_template": "http://" + code + "/{zoom}/{x}/{y}",
            "tile_size": 256, "resolutions": [1.0] * 25,
            "top_left_corner": [[0, 0]] * 25, **extra}


@pytest.fixture
def servers(monkeypatch):
    """has[code] = finest zoom level with an image; asked = (code, zl)."""
    has = {"T": 15, "A": 99, "B": 99}
    asked = []
    colour = {"T": (10, 0, 0), "A": (0, 10, 0), "B": (0, 0, 10)}

    def request(width, height, url, headers, session):
        (code, zl) = (url.split("/")[2], int(url.split("/")[3]))
        asked.append((code, zl))
        if zl > has[code]:
            return (0, "<Response [404]>")
        return (1, Image.new("RGB", (width, height), colour[code]))

    monkeypatch.setattr(IMG, "http_request_to_image", request)
    monkeypatch.setattr(IMG, "providers_dict", {
        c: provider(c) for c in ("T", "A", "B")})
    monkeypatch.setattr(IMG, "imagery_fallback", ["A", "B"])
    return (has, asked, colour)


def piece(zl=15, code="T"):
    report = IMG.ImageryReport()
    (ok, im) = IMG.get_wmts_image(zl, 100, 100, IMG.providers_dict[code],
                                  None, report)
    return (ok, im.getpixel((0, 0)), report)


def test_provider_has_it(servers):
    (has, asked, colour) = servers
    (ok, px, report) = piece()
    assert ok and px == colour["T"] and asked == [("T", 15)]
    assert not report.fallbacks


def test_first_fallback_before_lower_levels(servers):
    (has, asked, colour) = servers
    has["T"] = 13
    (ok, px, report) = piece()
    assert ok and px == colour["A"]
    assert asked == [("T", 15), ("A", 15)]  # T's ZL14 never asked
    assert report.fallbacks == {"A"} and report.down_sample == 0


def test_second_fallback(servers):
    (has, asked, colour) = servers
    (has["T"], has["A"]) = (13, 14)
    (ok, px, report) = piece()
    assert ok and px == colour["B"] and report.fallbacks == {"B"}
    assert asked == [("T", 15), ("A", 15), ("B", 15)]  # A not asked lower


def test_no_fallback_has_it(servers):
    (has, asked, colour) = servers
    (has["T"], has["A"], has["B"]) = (13, 14, 14)
    (ok, px, report) = piece()
    assert ok and px == colour["T"]
    # the fallbacks only once, at the asked level
    assert asked == [("T", 15), ("A", 15), ("B", 15), ("T", 14), ("T", 13)]
    assert not report.fallbacks and report.down_sample == 2


def test_nobody_has_it(servers):
    (has, asked, colour) = servers
    (has["T"], has["A"], has["B"]) = (-1, -1, -1)
    (ok, px, report) = piece(zl=4)
    assert not ok and px == (255, 255, 255) and report.only_no_data()
    assert asked == [("T", 4), ("A", 4), ("B", 4),
                     ("T", 3), ("T", 2), ("T", 1), ("T", 0)]


def test_off(servers, monkeypatch):
    (has, asked, colour) = servers
    has["T"] = 13
    monkeypatch.setattr(IMG, "imagery_fallback", [])
    (ok, px, report) = piece()
    assert ok and px == colour["T"] and ("A", 15) not in asked


def test_unsuitable_fallbacks_skipped(servers, monkeypatch):
    (has, asked, colour) = servers
    has["T"] = 13
    IMG.providers_dict["W"] = {"code": "W", "request_type": "wms"}
    IMG.providers_dict["Z"] = provider("Z", max_zl=14)
    IMG.providers_dict["S"] = provider("S", tile_size=512)
    has.update(Z=99, S=99)
    monkeypatch.setattr(IMG, "imagery_fallback",
                        ["T", "nope", "W", "Z", "S", "B"])
    (ok, px, report) = piece()
    assert ok and report.fallbacks == {"B"}
    assert [c for (c, _) in asked] == ["T", "B"]


def test_connection_failure_is_no_fallback(servers, monkeypatch):
    (has, asked, colour) = servers
    monkeypatch.setattr(IMG, "http_request_to_image",
                        lambda *a: (0, "Connection failure"))
    (ok, _, report) = piece()
    assert not ok and report.failed == 1 and not report.fallbacks


def test_probe_asks_the_provider_only(servers, monkeypatch):
    (has, asked, colour) = servers
    monkeypatch.setattr(IMG, "combined_providers_dict", {})
    has["T"] = 13
    assert IMG.provider_answers(55, 12, 15, "T") is True
    assert {c for (c, _) in asked} == {"T"}


def test_texture_records_the_fallback(servers, monkeypatch, tmp_path, lines):
    for name in ("incomplete_imgs", "no_data_imgs", "coarse_imgs",
                 "fallback_imgs"):
        monkeypatch.setattr(IMG, name, {})

    def build(tilbox, zl, prov, progress=None, report=None):
        report.fell_back("A")
        report.fell_back("B")
        return (1, Image.new("RGB", (4096, 4096)))

    monkeypatch.setattr(IMG, "build_texture_from_tilbox", build)
    file_dir = tmp_path / "+82-039" / "T_15"
    assert IMG.download_jpeg_ortho(str(file_dir), "a.jpg", 0, 0, 15, "T")
    assert IMG.fallback_imgs == {"+82-039": {"a.jpg": ["A", "B"]}}
    assert IMG.incomplete_imgs == {}


def test_fallback_note(lines):
    class Tile:
        (lat, lon, default_website) = (82, -39, "GO2")

    TILE._note_fallback_imagery(Tile(), {})
    assert not lines
    TILE._note_fallback_imagery(Tile(), {"b.jpg": ["BI"],
                                         "a.jpg": ["Arc", "BI"]})
    assert any("NOTE: 2 texture(s) of tile +82-039 have pieces from Arc, BI"
               in l and "GO2" in l and "a.jpg" in l for l in lines)


def test_setting():
    var = CFGV.cfg_vars["imagery_fallback"]
    assert var["module"] == "IMG" and var["type"] is list
    assert var["default"] == ["Arc", "BI"] == IMG.imagery_fallback
    assert "imagery_fallback" in CFGV.list_app_vars
