"""sort_mesh reports moulinette's failure instead of "applied"."""
import sys
import types

import pytest

import O4_File_Names as FNAMES
import O4_Mesh_Utils as MESH
import O4_UI_Utils as UI


@pytest.fixture
def tile(tmp_path, monkeypatch):
    t = types.SimpleNamespace(lat=55, lon=12, build_dir=str(tmp_path),
                              default_zl=17)
    open(FNAMES.mesh_file(t.build_dir, 55, 12), "w").close()
    monkeypatch.setattr(UI, "is_working", 0)
    msgs = []
    monkeypatch.setattr(UI, "exit_message_and_bottom_line",
                        lambda *a: msgs.append(" ".join(map(str, a))))
    monkeypatch.setattr(UI, "timings_and_bottom_line", lambda *a: None)
    monkeypatch.setattr(UI, "logprint", lambda *a: msgs.append("applied"))
    monkeypatch.setattr(UI, "vprint", lambda *a: None)
    return t, msgs


def _fake_tool(monkeypatch, code):
    # A Python one-liner stands in for moulinette: prints, exits with code.
    script = f"print('sorting'); raise SystemExit({code})"
    monkeypatch.setattr(MESH, "sort_mesh_cmd", sys.executable)
    real_popen = MESH.subprocess.Popen

    def popen(cmd, **kw):
        return real_popen([cmd[0], "-c", script], **kw)

    monkeypatch.setattr(MESH.subprocess, "Popen", popen)


def test_success(tile, monkeypatch):
    t, msgs = tile
    _fake_tool(monkeypatch, 0)
    assert MESH.sort_mesh(t) == 1
    assert msgs == ["applied"]


def test_failure_is_reported(tile, monkeypatch):
    t, msgs = tile
    _fake_tool(monkeypatch, 3)
    assert MESH.sort_mesh(t) == 0
    assert len(msgs) == 1 and "moulinette failed" in msgs[0]
    assert "0x3" in msgs[0]


def test_missing_tool(tile, monkeypatch):
    t, msgs = tile
    monkeypatch.setattr(MESH, "sort_mesh_cmd", str(t.build_dir) + "/nope.exe")
    assert MESH.sort_mesh(t) == 0
    assert "Could not start moulinette" in msgs[0]
