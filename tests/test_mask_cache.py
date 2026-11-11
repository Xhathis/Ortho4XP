"""#88: needs_mask decodes each mask once (bounded cache), same answers."""
import os
import types

import numpy
import pytest
from PIL import Image

import O4_File_Names as FNAMES
import O4_Mask_Utils as MASK


@pytest.fixture
def masks(tmp_path, monkeypatch):
    monkeypatch.setattr(FNAMES, "mask_dir", lambda lat, lon: str(tmp_path))
    MASK.clear_mask_cache()
    yield tmp_path
    MASK.clear_mask_cache()


def _mask(path, value_at):
    a = numpy.zeros((4096, 4096), dtype=numpy.uint8)
    for (x0, y0, v) in value_at:
        a[y0:y0 + 512, x0:x0 + 512] = v
    Image.fromarray(a).save(path)


TILE = types.SimpleNamespace(lat=55, lon=12, mask_zl=14)


def _old_needs_mask(path, rx, ry, factor):
    big = Image.open(path)
    x0, y0 = int(rx * 4096 / factor), int(ry * 4096 / factor)
    small = big.crop((x0, y0, x0 + 4096 // factor, y0 + 4096 // factor))
    return small if numpy.array(small).max() > 30 else False


def test_same_answers_as_without_cache_and_one_decode(masks, monkeypatch):
    # ZL17 textures on a mask_zl 14 mask: factor 8, 64 textures per mask.
    path = os.path.join(masks, FNAMES.legacy_mask(5088, 8736))
    _mask(path, [(512, 0, 255), (1024, 1536, 20), (3584, 3584, 31)])
    opened = []
    real_open = Image.open
    monkeypatch.setattr(MASK.Image, "open",
                        lambda p, *a: opened.append(p) or real_open(p, *a))
    for ry in range(8):
        for rx in range(8):
            got = MASK.needs_mask(TILE, 5088 * 8 + 16 * rx, 8736 * 8 + 16 * ry, 17)
            want = _old_needs_mask(path, rx, ry, 8)
            if want is False:
                assert got is False, (rx, ry)
            else:
                assert numpy.array_equal(numpy.array(got), numpy.array(want))
    assert opened.count(path) == 1 + 64  # cache once, _old_needs_mask 64 times


def test_rewritten_mask_is_read_again(masks):
    path = os.path.join(masks, FNAMES.legacy_mask(5088, 8736))
    _mask(path, [])
    assert MASK.needs_mask(TILE, 5088 * 8, 8736 * 8, 17) is False
    _mask(path, [(0, 0, 255)])
    os.utime(path, ns=(os.stat(path).st_atime_ns, os.stat(path).st_mtime_ns + 10**9))
    assert MASK.needs_mask(TILE, 5088 * 8, 8736 * 8, 17) is not False


def test_cache_is_bounded(masks):
    for i in range(MASK._MASK_CACHE_SIZE + 3):
        path = os.path.join(masks, FNAMES.legacy_mask(5088 + 16 * i, 8736))
        _mask(path, [])
        MASK.needs_mask(TILE, (5088 + 16 * i) * 8, 8736 * 8, 17)
    assert len(MASK._mask_cache) == MASK._MASK_CACHE_SIZE
    MASK.clear_mask_cache()
    assert len(MASK._mask_cache) == 0


def test_no_mask_file(masks):
    assert MASK.needs_mask(TILE, 5088 * 8, 8736 * 8, 17) is False
    assert MASK.needs_mask(TILE, 5088, 8736, 13) is False  # below mask_zl
