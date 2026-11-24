"""#126: the Earth preview message names what went wrong."""
import tkinter as tk

import O4_GUI_Utils as GUI

PATH = r"G:\Ortho4XP\Utils\Earth\Earth2_ZL6_4_2.jpg"


def test_missing_file_asks_for_a_fresh_copy():
    msg = GUI.earth_preview_error(PATH, FileNotFoundError(2, "No such file"))
    assert msg.startswith("Could not find Earth preview file " + PATH)


def test_tcl_error_of_a_redraw_is_quiet():
    assert GUI.earth_preview_error(
        PATH, tk.TclError('image "pyimage12" doesn\'t exist')) is None


def test_other_error_is_named_not_blamed_on_the_file():
    msg = GUI.earth_preview_error(
        PATH, RuntimeError("main thread is not in main loop"))
    assert "Could not find" not in msg
    assert msg.startswith("ERROR:")
    assert PATH in msg
    assert "RuntimeError: main thread is not in main loop" in msg


def test_broken_image_is_named():
    msg = GUI.earth_preview_error(PATH, OSError("cannot identify image file"))
    assert "Could not find" not in msg
    assert "OSError: cannot identify image file" in msg
