"""At most overpass_max_parallel Overpass requests at once (#80, #30)."""
import os
import subprocess
import sys
import textwrap

import O4_File_Names as FNAMES
import O4_OSM_Utils as OSM
import O4_UI_Utils as UI


def test_lock_names(monkeypatch):
    monkeypatch.setattr(OSM, "overpass_max_parallel", 2)
    assert OSM._overpass_lock_names() == [".overpass.lock", ".overpass.lock1"]
    monkeypatch.setattr(OSM, "overpass_max_parallel", 0)
    assert OSM._overpass_lock_names() == [".overpass.lock"]


def test_two_slots_then_wait(monkeypatch):
    monkeypatch.setattr(OSM, "overpass_max_parallel", 2)
    monkeypatch.setattr(UI, "vprint", lambda *a: None)
    a = OSM._acquire_overpass_slot()
    b = OSM._acquire_overpass_slot()
    assert a and b and a.name != b.name
    # A third request waits; with the red flag (Stop) it gives up.
    monkeypatch.setattr(UI, "red_flag", True)
    assert OSM._acquire_overpass_slot() is None
    monkeypatch.setattr(UI, "red_flag", False)
    OSM._release_overpass_slot(a)
    c = OSM._acquire_overpass_slot()
    assert c.name == a.name
    OSM._release_overpass_slot(b)
    OSM._release_overpass_slot(c)


def test_slot_shared_with_another_process(monkeypatch):
    # A process holding both lock files (as two requests elsewhere would)
    # leaves none for this one.
    monkeypatch.setattr(OSM, "overpass_max_parallel", 2)
    monkeypatch.setattr(UI, "vprint", lambda *a: None)
    os.makedirs(FNAMES.OSM_dir, exist_ok=True)
    holder = textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {os.path.dirname(OSM.__file__)!r})
        import O4_OSM_Utils as OSM
        OSM.overpass_max_parallel = 2
        a = OSM._acquire_overpass_slot(); b = OSM._acquire_overpass_slot()
        print("held", flush=True)
        sys.stdin.readline()
    """)
    p = subprocess.Popen([sys.executable, "-c", holder], cwd=os.getcwd(),
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         text=True)
    try:
        # The import may print a notice first (no overpass_servers.txt in
        # the test's empty cwd).
        for line in p.stdout:
            if line.strip() == "held":
                break
        else:
            raise AssertionError("holder process did not take the slots")
        monkeypatch.setattr(UI, "red_flag", True)
        assert OSM._acquire_overpass_slot() is None
        monkeypatch.setattr(UI, "red_flag", False)
    finally:
        p.stdin.write("\n")
        p.stdin.flush()
        p.wait(timeout=30)
    # The OS released its locks with the process.
    s = OSM._acquire_overpass_slot()
    assert s is not None
    OSM._release_overpass_slot(s)
