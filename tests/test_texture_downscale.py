"""#91: a mosaic much larger than the target (provider without a coarse
enough level) is built in full and resized once; the dead per-piece
"downscale" code (float sizes) is gone. Same results as before."""
import numpy
import pytest
from PIL import Image

import O4_Imagery_Utils as IMG
import O4_UI_Utils as UI

R = 0.5  # m per pixel, the provider's only level
X0, Y0 = 0.0, 100000.0


def _color(til_x, til_y):
    return (40 * (til_x % 6), 40 * (til_y % 6), 200)


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(UI, "red_flag", False)
    monkeypatch.setattr(UI, "vprint", lambda *a: None)

    def paste(tilematrix, til_x, til_y, provider, big_image, x0, y0,
              http_session, subt_size=None):
        size = subt_size or (provider["tile_size"],) * 2
        big_image.paste(Image.new("RGB", size, _color(til_x, til_y)),
                        (int(x0), int(y0)))
        return 1

    monkeypatch.setattr(IMG, "get_and_paste_wmts_part", paste)
    return {
        "code": "fake", "epsg_code": "3857", "request_type": "wmts",
        "tile_size": 256, "resolutions": numpy.array([R]),
        "top_left_corner": [[X0, Y0]], "max_threads": 2,
    }


def test_large_mosaic_is_downscaled(provider):
    # 1024 x 1024 source pixels asked as 128 x 128: 8 times too many.
    bbox = [X0, Y0, X0 + 1024 * R, Y0 - 1024 * R]
    ok, img = IMG.build_texture_from_bbox_and_size(bbox, "3857", (128, 128), provider)
    assert ok == 1 and img.size == (128, 128)
    assert img.getpixel((5, 5)) == _color(0, 0)
    assert img.getpixel((122, 122)) == _color(3, 3)


def test_large_mosaic_with_crop(provider):
    # Offset by half a piece: 5 x 5 pieces fetched, crop needed.
    bbox = [X0 + 128 * R, Y0 - 128 * R, X0 + 1152 * R, Y0 - 1152 * R]
    ok, img = IMG.build_texture_from_bbox_and_size(bbox, "3857", (128, 128), provider)
    assert ok == 1 and img.size == (128, 128)
    # the first 16 target pixels (128 source px) are the rest of piece 0
    assert img.getpixel((4, 4)) == _color(0, 0)
    assert img.getpixel((20, 20)) == _color(1, 1)
    assert img.getpixel((124, 124)) == _color(4, 4)


def test_normal_size_not_downscaled(provider):
    bbox = [X0, Y0, X0 + 512 * R, Y0 - 512 * R]
    ok, img = IMG.build_texture_from_bbox_and_size(bbox, "3857", (512, 512), provider)
    assert ok == 1 and img.size == (512, 512)
    assert img.getpixel((300, 10)) == _color(1, 0)
