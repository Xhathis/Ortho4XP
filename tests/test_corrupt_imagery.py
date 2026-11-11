"""#48: a corrupt image from the server is retried, not handed on."""
import io

import pytest
from PIL import Image

import O4_Imagery_Utils as IMG
import O4_UI_Utils as UI


def _jpeg_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (256, 256), (10, 120, 30)).save(buf, "JPEG")
    return buf.getvalue()


class _Response:
    def __init__(self, content):
        self.content = content
        self.headers = {"Content-Type": "image/jpeg"}
        self.status_code = 200

    def __str__(self):
        return "<Response [200]>"


class _Session:
    def __init__(self, contents):
        self.contents = list(contents)
        self.calls = 0

    def get(self, url, timeout=None, headers=None):
        self.calls += 1
        return _Response(self.contents.pop(0))


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    monkeypatch.setattr(UI, "red_flag", False)


def test_good_image_is_decoded():
    session = _Session([_jpeg_bytes()])
    ok, image = IMG.http_request_to_image(256, 256, "http://x/1", None, session)
    assert ok == 1 and image.size == (256, 256)
    assert image.getpixel((5, 5))[1] > 100


def test_truncated_image_is_retried_then_used():
    good = _jpeg_bytes()
    session = _Session([good[: len(good) // 2], good])
    ok, image = IMG.http_request_to_image(256, 256, "http://x/1", None, session)
    assert ok == 1 and session.calls == 2
    image.convert("RGB")  # already decoded: no error any more


def test_always_truncated_image_fails(monkeypatch):
    good = _jpeg_bytes()
    monkeypatch.setattr(IMG, "max_baddata_retries", 3)
    session = _Session([good[: len(good) // 2]] * 3)
    ok, data = IMG.http_request_to_image(256, 256, "http://x/1", None, session)
    assert ok == 0 and session.calls == 3
