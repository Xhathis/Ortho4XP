"""#52: a GUI step that raises frees the GUI again and says why."""
import pytest

import O4_UI_Utils as UI


@pytest.fixture
def logged(monkeypatch):
    lines = []
    monkeypatch.setattr(UI, "lvprint", lambda level, *a: lines.append(
        " ".join(str(x) for x in a)))
    monkeypatch.setattr(UI, "is_working", False)
    return lines


def test_result_is_passed_through(logged):
    assert UI.run_guarded(lambda a, b: a + b, 2, 3) == 5
    assert logged == []


def test_exception_frees_the_gui_and_is_logged(logged):
    def build_masks(tile, for_imagery):
        UI.is_working = 1
        raise TypeError("cannot unpack non-iterable int object")

    assert UI.run_guarded(build_masks, None, False) == 0
    assert UI.is_working is False
    assert len(logged) == 1
    assert "build_masks" in logged[0] and "TypeError" in logged[0]


def test_system_exit_is_not_swallowed(logged):
    def leave():
        raise SystemExit(3)

    with pytest.raises(SystemExit):
        UI.run_guarded(leave)
