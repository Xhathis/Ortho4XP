"""#86: imagery answers 429/408/503 are retried after a wait; an answer
without Content-Type does not raise."""
import io

import pytest
from PIL import Image

import O4_Imagery_Utils as IMG
import O4_UI_Utils as UI


def _png():
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "green").save(buf, "PNG")
    return buf.getvalue()


class _Resp:
    def __init__(self, status, headers=None, content=b""):
        self.status_code = status
        self.headers = headers or {}
        self.content = content

    def __str__(self):
        return f"<Response [{self.status_code}]>"


class _Session:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = 0

    def get(self, url, timeout=None, headers=None):
        self.calls += 1
        return self.answers.pop(0)

    def close(self):
        pass


OK = _Resp(200, {"Content-Type": "image/png"}, _png())


@pytest.fixture
def slept(monkeypatch):
    waits = []
    monkeypatch.setattr(UI, "red_flag", False)
    monkeypatch.setattr(UI, "vprint", lambda *a: None)
    monkeypatch.setattr(IMG.time, "sleep", waits.append)
    monkeypatch.setattr(IMG, "check_tms_response", True)
    monkeypatch.setattr(IMG, "max_baddata_retries", 5)
    return waits


def _get(session):
    return IMG.http_request_to_image(4, 4, "http://x/1", None, session)


def test_429_with_retry_after_is_waited_and_retried(slept):
    s = _Session([_Resp(429, {"Retry-After": "7"}), OK])
    ok, img = _get(s)
    assert ok == 1 and img.size == (4, 4)
    assert sum(slept) == pytest.approx(7)


def test_429_without_retry_after_backs_off(slept):
    s = _Session([_Resp(429), _Resp(429), _Resp(429), OK])
    ok, _ = _get(s)
    assert ok == 1
    assert sum(slept) == pytest.approx(2 + 4 + 8)


def test_retry_after_is_capped(slept):
    s = _Session([_Resp(503, {"Retry-After": "3600"}), OK])
    assert _get(s)[0] == 1
    assert sum(slept) == pytest.approx(60)


def test_408_and_500_wait_2s(slept):
    s = _Session([_Resp(408), _Resp(500), OK])
    assert _get(s)[0] == 1
    assert sum(slept) == pytest.approx(4)


def test_gives_up_after_max_baddata_retries(slept):
    s = _Session([_Resp(429, {"Retry-After": "1"}) for _ in range(5)])
    ok, status = _get(s)
    assert ok == 0 and "[429]" in status
    assert s.calls == 5


def test_no_retry_without_check_tms_response(slept, monkeypatch):
    monkeypatch.setattr(IMG, "check_tms_response", False)
    s = _Session([_Resp(429), OK])
    assert _get(s)[0] == 0
    assert s.calls == 1 and slept == []


def test_stop_ends_the_wait(slept, monkeypatch):
    def sleep(t):
        slept.append(t)
        UI.red_flag = True
    monkeypatch.setattr(IMG.time, "sleep", sleep)
    s = _Session([_Resp(429, {"Retry-After": "30"}), OK])
    assert _get(s) == (0, "Stopped")
    assert len(slept) == 1 and s.calls == 1


def test_200_without_content_type(slept):
    s = _Session([_Resp(200, {}, b"<html>")])
    ok, status = _get(s)
    assert ok == 0 and "[200]" in status
