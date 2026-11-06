"""Printing names the console encoding lacks must not crash a step.

A parallel batch worker writes to a UTF-8 tmp log but encoded its output
in cp1252, so a Polish airport name ("ł") in +54+015 raised
UnicodeEncodeError in step 1.
"""
import io
import os
import subprocess
import sys

import O4_File_Names as FNAMES
import O4_Tile_Utils as TILE
import O4_UI_Utils as UI

NAME = "Kołobrzeg Świdwin"  # neither ł nor Ś is in cp1252


def _cp1252_stream():
    return io.TextIOWrapper(io.BytesIO(), encoding="cp1252")


def test_safe_console_streams_escapes(monkeypatch):
    out, err = _cp1252_stream(), _cp1252_stream()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    UI.safe_console_streams()
    print("EPKG", NAME)
    print(NAME, file=sys.stderr)
    out.flush()
    err.flush()
    assert out.buffer.getvalue() == b"EPKG Ko\\u0142obrzeg \\u015awidwin\r\n" \
        or out.buffer.getvalue() == b"EPKG Ko\\u0142obrzeg \\u015awidwin\n"
    assert b"\\u0142" in err.buffer.getvalue()


def test_safe_console_streams_keeps_encodable_text(monkeypatch):
    out = _cp1252_stream()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", None)  # pythonw
    UI.safe_console_streams()
    print("Keflavík Þórshöfn Ærø")
    out.flush()
    assert "Keflavík Þórshöfn Ærø".encode("cp1252") in out.buffer.getvalue()


def test_safe_console_streams_ignores_replaced_stream(monkeypatch):
    class Widget:  # like the GUI's stdout replacement
        def write(self, s):
            pass

    monkeypatch.setattr(sys, "stdout", Widget())
    UI.safe_console_streams()  # must not raise


def test_vprint_without_fix_raises(monkeypatch):
    # The failure as it happened, so the test above means something.
    monkeypatch.setattr(sys, "stdout", _cp1252_stream())
    try:
        UI.vprint(0, NAME)
    except UnicodeEncodeError:
        return
    raise AssertionError("cp1252 stream accepted ł")


def test_logprint_keeps_line(monkeypatch, tmp_path):
    log = tmp_path / "Ortho4XP.log"
    monkeypatch.setattr(FNAMES, "resource_path", lambda name: str(log))
    UI.logprint("Airport", NAME, "end")
    UI.logprint("next line")
    raw = log.read_bytes()
    assert raw.count(b"\n") == 2
    assert b"Airport" in raw and b"end" in raw and b"next line" in raw


def test_worker_env_child_output(tmp_path):
    # A real child process, output redirected to a file opened as UTF-8
    # (as _run_batch_phase does): the name arrives intact, exit 0.
    log_path = tmp_path / "batch_+54+015.log"
    env = TILE._worker_env()
    env.pop("PYTHONUTF8", None)
    with open(log_path, "w", encoding="utf-8") as log_file:
        code = subprocess.run(
            [sys.executable, "-c", f"print({NAME!r})"],
            stdout=log_file, stderr=subprocess.STDOUT, env=env,
        ).returncode
    assert code == 0
    assert log_path.read_text(encoding="utf-8").strip() == NAME


def test_child_without_worker_env_fails(tmp_path):
    # Without PYTHONIOENCODING the same child crashes on Windows (cp1252);
    # elsewhere the locale is usually UTF-8 and it passes.
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
    with open(tmp_path / "out.log", "w", encoding="utf-8") as log_file:
        code = subprocess.run(
            [sys.executable, "-c", f"print({NAME!r})"],
            stdout=log_file, stderr=subprocess.STDOUT, env=env,
        ).returncode
    if sys.platform == "win32":
        assert code != 0
