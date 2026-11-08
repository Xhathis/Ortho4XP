"""#65: a texture download that fails once is retried, never lost.

download_textures used to put a failed texture back on the download queue
after its "pending" count had dropped, so the main loop could find the
queue empty first and send "quit". The retried texture was then neither
downloaded nor listed in `failed`, and build_tile activated the DSF.
"""
import queue
import threading
import time

import pytest

import O4_Imagery_Utils as IMG
import O4_Tile_Utils as TILE
import O4_UI_Utils as UI


class _SlowRequeue(queue.Queue):
    """A worker's put() of a texture comes late: this opens the old race
    window every time instead of once in a while."""

    def put(self, item, *a, **kw):
        if (isinstance(item, tuple)
                and threading.current_thread() is not threading.main_thread()):
            time.sleep(0.5)
        super().put(item, *a, **kw)


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(UI, "red_flag", False)
    monkeypatch.setattr(UI, "progress_bar", lambda *a, **k: None)
    logged = []
    monkeypatch.setattr(UI, "lvprint", lambda level, *a: logged.append(a))
    monkeypatch.setattr(UI, "vprint", lambda level, *a: None)
    return logged


def _run(monkeypatch, outcomes, attrs_list):
    """outcomes: per texture, the build_jpeg_ortho results in call order."""
    calls = {a: 0 for a in attrs_list}
    lock = threading.Lock()

    def fake_build(tile, *attrs):
        with lock:
            n = calls[attrs]
            calls[attrs] += 1
        return outcomes[attrs][min(n, len(outcomes[attrs]) - 1)]

    monkeypatch.setattr(IMG, "build_jpeg_ortho", fake_build)
    dq, cq = _SlowRequeue(), queue.Queue()
    for a in attrs_list:
        dq.put(a)
    failed = []
    result = TILE.download_textures(
        object(), dq, cq, workers=2, failed=failed
    )
    converted = []
    while not cq.empty():
        converted.append(cq.get()[1:])
    return result, converted, failed, calls


A = (1024, 2048, 17, "Arc")
B = (1040, 2048, 17, "Arc")


def test_texture_failing_once_is_converted(monkeypatch):
    result, converted, failed, calls = _run(
        monkeypatch, {A: [0, 1]}, [A]
    )
    assert result == 1
    assert converted == [A]
    assert failed == []
    assert calls[A] == 2


def test_texture_failing_always_is_listed_as_failed(monkeypatch, _quiet):
    result, converted, failed, calls = _run(
        monkeypatch, {A: [0], B: [1]}, [A, B]
    )
    assert converted == [B]
    assert failed == [A]
    assert calls[A] == 3
    assert any("Could not get texture" in str(x) for x in _quiet)


def test_exception_counts_as_a_failed_attempt(monkeypatch):
    def boom_then_ok():
        state = {"n": 0}

        def build(tile, *attrs):
            state["n"] += 1
            if state["n"] == 1:
                raise OSError("cut response")
            return 1
        return build

    monkeypatch.setattr(IMG, "build_jpeg_ortho", boom_then_ok())
    dq, cq = queue.Queue(), queue.Queue()
    dq.put(A)
    failed = []
    assert TILE.download_textures(object(), dq, cq, workers=1,
                                  failed=failed) == 1
    assert cq.get_nowait()[1:] == A
    assert failed == []
