"""fill_nodata_values_with_nearest_neighbor: filling and its messages (#39)."""
import numpy
import pytest

import O4_DEM_Utils as DEM

NODATA = -32768.0
M = DEM.COMBINED_MARGIN


@pytest.fixture
def messages(monkeypatch):
    out = []
    monkeypatch.setattr(
        DEM.UI, "vprint",
        lambda level, *a: out.append(("console", " ".join(map(str, a)))),
    )
    monkeypatch.setattr(
        DEM.UI, "lvprint",
        lambda level, *a: out.append(("logged", " ".join(map(str, a)))),
    )
    return out


def raster(size=3673, value=100.0):
    return numpy.full((size, size), value, dtype=numpy.float32)


def notes(messages):
    return [m for m in messages if "INFO:" in m[1] or "WARNING:" in m[1]
            if "trying to fill" not in m[1]]


def test_small_hole_is_filled_silently(messages):
    a = raster(200)
    a[50:55, 50:55] = NODATA
    assert DEM.fill_nodata_values_with_nearest_neighbor(a, NODATA, "tile X")
    assert not (a == NODATA).any()
    assert (a == 100).all()
    assert notes(messages) == []


def test_too_many_voids_is_refused(messages):
    a = raster(200)
    a[:100, :100] = NODATA  # 10,000 samples
    assert DEM.fill_nodata_values_with_nearest_neighbor(a, NODATA) == 0
    assert (a == NODATA).sum() == 10000  # untouched; caller zeroes it


def test_void_margin_corner_is_info_with_tile_name(messages):
    # +61-050 on 2026-11-05: neighbour N62W051 void in the NW corner.
    a = raster()
    a[:M, :M] = NODATA
    assert DEM.fill_nodata_values_with_nearest_neighbor(
        a, NODATA, "tile +61-050", M
    )
    assert not (a == NODATA).any()
    assert (a[M:, M:] == 100).all()  # the tile itself untouched
    (kind, text), = notes(messages)
    assert kind == "console"
    assert "INFO: tile +61-050:" in text and "margin" in text
    assert "WARNING" not in text


def test_hole_inside_tile_is_logged_warning(messages):
    a = raster()
    a[1000:1050, 1000:1050] = NODATA  # needs 25 rounds
    a[:M, :M] = NODATA
    DEM.fill_nodata_values_with_nearest_neighbor(a, NODATA, "tile +61-050", M)
    assert not (a == NODATA).any()
    (kind, text), = notes(messages)
    assert kind == "logged"
    assert "WARNING: tile +61-050:" in text
    assert "and " in text and "in the margin" in text


def test_without_margin_every_hole_counts(messages):
    # A 3" file read on its own (margin 0): a corner hole is in the file.
    a = raster(1201)
    a[:M, :M] = NODATA
    DEM.fill_nodata_values_with_nearest_neighbor(a, NODATA, "N62W051.hgt")
    (kind, text), = notes(messages)
    assert kind == "logged"
    assert "WARNING: N62W051.hgt:" in text
    assert "margin" not in text


def test_filled_values_are_unchanged_by_the_new_messages(messages):
    # Same filling as before #39: max of the 4 neighbours, then zero.
    a = raster()
    rng = numpy.random.default_rng(1)
    a[M:-M, M:-M] = rng.integers(0, 500, (3601, 3601))
    a[:M, :M] = NODATA
    a[2000:2060, 2000:2003] = NODATA
    b = a.copy()
    DEM.fill_nodata_values_with_nearest_neighbor(a, NODATA, "t", M)
    # reference: the pre-#39 algorithm
    for _ in range(21):
        if not (b == NODATA).any():
            break
        s = [numpy.roll(b, 1, 0), numpy.roll(b, -1, 0),
             numpy.roll(b, 1, 1), numpy.roll(b, -1, 1)]
        s[0][0], s[1][-1], s[2][:, 0], s[3][:, -1] = b[0], b[-1], b[:, 0], b[:, -1]
        t = numpy.maximum.reduce(s)
        b[b == NODATA] = t[b == NODATA]
    b[b == NODATA] = 0
    assert numpy.array_equal(a, b)
