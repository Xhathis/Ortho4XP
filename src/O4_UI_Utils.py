import os
import sys
import time
import traceback

import O4_File_Names as FNAMES

verbosity = 1
red_flag = False
# red_flag stops the current step, both on errors and on the Stop button;
# stop_requested is set only by the Stop button, so a batch build can tell
# "skip this tile" from "stop everything".
stop_requested = False
is_working = False
cleaning_level = 1
gui = None
log = True


################################################################################
def subprocess_env():
    """Return a subprocess environment with OBJC_DISABLE_INITIALIZE_FORK_SAFETY
    set on macOS to suppress CoreFoundation fork-safety warnings."""
    env = os.environ.copy()
    if "dar" in sys.platform:
        env["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
    return env


################################################################################
def safe_console_streams():
    """Make printing to stdout/stderr never raise UnicodeEncodeError.

    When the output is redirected (a parallel batch worker's tmp log, a CLI
    run piped to a file), Python encodes it with the Windows ANSI code page
    (cp1252), which has no letter like the Polish "ł": printing an OSM name
    with one (an airport in step 1) crashed the step. Such characters are
    now written as \\uXXXX escapes instead. The GUI replaces sys.stdout with
    its own window and is not affected.
    """
    for stream in (sys.stdout, sys.stderr):
        # None under pythonw; a replaced stream may lack reconfigure().
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")


################################################################################
def progress_bar(nbr, percentage, message=None):
    if gui:
        gui.pgrbv[nbr].set(percentage)


################################################################################
def vprint(min_verbosity, *args):
    if verbosity >= min_verbosity:
        print(*args)


################################################################################
def logprint(*args):
    try:
        # Same (locale) encoding as before, so the log stays one encoding;
        # a character it lacks is escaped instead of losing the whole line.
        with open(
            FNAMES.resource_path("Ortho4XP.log"), "a",
            errors="backslashreplace",
        ) as f:
            f.write(
                time.strftime("%c")
                + " | "
                + " ".join([str(x) for x in args])
                + "\n"
            )
    except (OSError, UnicodeError):  # logging must never crash
        pass


################################################################################
def lvprint(min_verbosity, *args):
    if verbosity >= min_verbosity:
        print(*args)
    if log:
        logprint(*args)


################################################################################
def bug_report(*args):
    logprint(
        "An internal error occured. Please file a bug with lat/lon and cfg"
    )
    if args:
        logprint(*args)


################################################################################
def exit_message_and_bottom_line(*args):
    global is_working
    if not args:
        args = ("Process interrupted",)
    if args[0]:
        logprint(*args)
        print(*args)
    print(
        "_____________________________________________________________"
        + "____________________________________"
    )
    is_working = False


################################################################################
def timings_and_bottom_line(tinit):
    global is_working
    print("\nCompleted in " + nicer_timer(time.time() - tinit) + ".")
    print(
        "_____________________________________________________________"
        + "____________________________________"
    )
    is_working = False


################################################################################
def run_guarded(func, *args):
    """Thread target for the GUI's work buttons (#52).

    A step that raised used to end its thread with is_working still set:
    every later button was ignored without a word until Ortho4XP was
    restarted, and the error went only to the console.
    """
    global is_working
    try:
        return func(*args)
    except Exception as e:
        lvprint(
            0, "ERROR:", getattr(func, "__name__", "step"),
            f"stopped on an unexpected error: {type(e).__name__}: {e}",
        )
        details = traceback.format_exc()
        vprint(1, details)
        if log:
            logprint(details)
        print(
            "_____________________________________________________________"
            + "____________________________________"
        )
        is_working = False
        return 0


################################################################################
def human_print(num, suffix=""):
    for unit in ["", "K", "M", "G", "T", "P", "E", "Z"]:
        if abs(num) < 1024.0:
            return "{:.1f}{}{}".format(num, unit, suffix)
        num /= 1024.0
    return "{:.1f}{}{}".format(num, "Y", suffix)


################################################################################
def nicer_timer(elapsed):
    out_string = ""
    hours = elapsed // 3600
    if hours:
        elapsed -= 3600 * hours
        out_string += str(int(hours)) + "h"
    minutes = elapsed // 60
    if hours or minutes:
        elapsed -= 60 * minutes
        out_string += str(int(minutes)) + "m"
    elapsed = "{:.2f}".format(elapsed) if not out_string else int(elapsed)
    out_string += str(elapsed) + "sec"
    return out_string
