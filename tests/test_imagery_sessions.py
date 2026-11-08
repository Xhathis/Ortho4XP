"""#70: sessions made after a connection failure are closed, the shared one
is not."""
import pytest
import requests

import O4_Imagery_Utils as IMG
import O4_UI_Utils as UI


class _FailingSession:
    made = []

    def __init__(self):
        self.closed = False
        _FailingSession.made.append(self)

    def get(self, url, timeout=None, headers=None):
        raise requests.exceptions.ConnectionError("refused")

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    monkeypatch.setattr(UI, "red_flag", False)
    monkeypatch.setattr(UI, "vprint", lambda *a: None)
    monkeypatch.setattr(IMG.time, "sleep", lambda s: None)
    monkeypatch.setattr(IMG, "check_tms_response", True)
    monkeypatch.setattr(IMG, "max_connect_retries", 4)
    _FailingSession.made = []
    monkeypatch.setattr(IMG.requests, "Session", _FailingSession)


def test_retry_sessions_are_closed_shared_one_is_not():
    shared = _FailingSession()
    ok, status = IMG.http_request_to_image(256, 256, "http://x/1", None, shared)
    assert ok == 0 and status == "Connection failure"
    own = _FailingSession.made[1:]
    assert len(own) == 4
    assert all(s.closed for s in own)
    assert not shared.closed


def test_no_retry_no_new_session(monkeypatch):
    monkeypatch.setattr(IMG, "check_tms_response", False)
    shared = _FailingSession()
    ok, _ = IMG.http_request_to_image(256, 256, "http://x/1", None, shared)
    assert ok == 0
    assert _FailingSession.made == [shared]
    assert not shared.closed
