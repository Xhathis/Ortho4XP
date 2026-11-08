import time
import os
import shutil
import sys
import subprocess
import O4_File_Names as FNAMES
import O4_UI_Utils as UI

# the following is meant to be modified directly by users who need it (in the 
# config window, not here!)
ovl_exclude_pol = [0]
ovl_exclude_net = []

# the following is meant to be modified by the CFG module at run time
custom_overlay_src = ""
custom_overlay_src_alternate = ""

if "dar" in sys.platform:
    unzip_cmd = os.path.join(FNAMES.Utils_dir, "mac", "7zz")
    # As of version 1.40.08, the 7zz executable was added to Utils/mac
    # For user upgrading from previous versions (only updated the Ortho4XP executable),
    # we continue to use 7z installed on the system.
    if not os.path.exists(unzip_cmd):
        unzip_cmd = "7z"
    dsftool_cmd = os.path.join(FNAMES.Utils_dir, "mac", "DSFTool ")
elif "win" in sys.platform:
    unzip_cmd = os.path.join(FNAMES.Utils_dir, "win", "7z.exe")
    dsftool_cmd = os.path.join(FNAMES.Utils_dir, "win", "DSFTool.exe ")
else:
    unzip_cmd = "7z"
    dsftool_cmd = os.path.join(FNAMES.Utils_dir, "lin", "DSFTool ")

################################################################################
def build_overlay(lat, lon):
    if UI.is_working:
        return 0
    UI.is_working = 1
    timer = time.time()
    UI.logprint("Step 4 for tile lat=", lat, ", lon=", lon, ": starting.")
    UI.vprint(
        0,
        "\nStep 4 : Extracting overlay for tile "
        + FNAMES.short_latlon(lat, lon)
        + " : \n--------\n",
    )
    try:
        error = _extract_overlay(lat, lon)
    except OSError as e:
        # Disk full, a locked or vanished tmp file: report it instead of
        # ending the thread with an exception and UI.is_working still set.
        error = f"{e.strerror or e} ({e.filename})"
    _remove_tmp_files(lat, lon)
    if error:
        UI.exit_message_and_bottom_line(
            "   ERROR: overlay for tile "
            + FNAMES.short_latlon(lat, lon)
            + " not extracted: "
            + error
        )
        return 0
    UI.logprint("Step 4 for tile lat=", lat, ", lon=", lon, ": normal exit.")
    UI.timings_and_bottom_line(timer)
    return 1


def _tmp_file(lat, lon, suffix):
    return os.path.join(FNAMES.Tmp_dir, FNAMES.short_latlon(lat, lon) + suffix)


def _remove_tmp_files(lat, lon):
    """Remove what build_overlay leaves in tmp, after success or failure."""
    names = [
        _tmp_file(lat, lon, suffix)
        for suffix in (".dsf", ".dsf.7z", "_tmp_dsf.txt",
                       "_tmp_dsf_without_mesh.txt", "_tmp_dsf_without_mesh.dsf")
    ]
    # DSFTool writes one .raw per raster layer; XP12 DSFs have about a dozen
    # (elevation, sea_level, seasons, soundscape), not just the first two.
    raw_prefix = FNAMES.short_latlon(lat, lon) + "_tmp_dsf.txt."
    try:
        names += [
            os.path.join(FNAMES.Tmp_dir, file_name)
            for file_name in os.listdir(FNAMES.Tmp_dir)
            if file_name.startswith(raw_prefix) and file_name.endswith(".raw")
        ]
    except OSError:
        pass
    for name in names:
        try:
            os.remove(name)
        except FileNotFoundError:
            pass
        except OSError as e:
            UI.vprint(1, "   WARNING: could not remove", name, f"({e.strerror})")


def _run_dsftool(option, src, dst):
    """Run DSFTool and show its output; return an error message or None."""
    process = subprocess.Popen(
        [dsftool_cmd.strip(), option, src, dst],
        stdout=subprocess.PIPE, bufsize=0, env=UI.subprocess_env(),
    )
    for line in process.stdout:
        UI.vprint(1, "     " + line.decode("utf-8", "replace").rstrip())
    # returncode is None until the process is waited for: reading stdout to
    # its end only means the pipe closed, so the old check never fired.
    returncode = process.wait()
    if returncode:
        code = returncode & 0xFFFFFFFF
        shown = f"{code:#X}" if code >= 0xC0000000 else str(returncode)
        return f"DSFTool {option} failed (exit code {shown})."
    if not os.path.isfile(dst):
        return f"DSFTool {option} wrote no output file."
    return None


def _extract_overlay(lat, lon):
    """Steps of build_overlay; return an error message or None."""
    # An empty setting is skipped: joined with "" the path would be
    # relative to the cwd, and the error would name the wrong file.
    candidates = [
        os.path.join(src, "Earth nav data", FNAMES.long_latlon(lat, lon) + ".dsf")
        for src in (custom_overlay_src, custom_overlay_src_alternate) if src
    ]
    if not candidates:
        return (
            "custom_overlay_src is not set. The overlay source directory "
            "needs to be set in the config window first."
        )
    existing = [name for name in candidates if os.path.isfile(name)]
    if not existing:
        return "file " + " or ".join(candidates) + " absent."
    file_to_sniff = existing[0]
    # Leftovers of an interrupted run must not pass for this run's output.
    _remove_tmp_files(lat, lon)
    file_to_sniff_loc = _tmp_file(lat, lon, ".dsf")
    UI.vprint(1, "-> Making a copy of the original overlay DSF in tmp dir")
    try:
        shutil.copy(file_to_sniff, file_to_sniff_loc)
    except OSError as e:
        return f"could not copy it to the tmp dir ({e.strerror or e})."
    with open(file_to_sniff_loc, "rb") as f:
        dsfid = f.read(2)
    if dsfid == b"7z":
        UI.vprint(1, "-> The original DSF is a 7z archive, uncompressing...")
        # Same guard as in O4_DSF_Utils: a locked tmp file or a failing 7z
        # used to crash the overlay step a few lines later.
        try:
            os.replace(file_to_sniff_loc, file_to_sniff_loc + ".7z")
            result = subprocess.run(
                [unzip_cmd, "e", "-y", f"-o{FNAMES.Tmp_dir}",
                 f"{file_to_sniff_loc}.7z"],
                env=UI.subprocess_env(),
            )
            if result.returncode or not os.path.isfile(file_to_sniff_loc):
                raise OSError(f"7z exited with code {result.returncode}")
        except OSError as e:
            return f"could not uncompress the overlay DSF ({e.strerror or e})."
    UI.vprint(1, "-> Converting the copy to text format")
    error = _run_dsftool(
        "-dsf2text", file_to_sniff_loc, _tmp_file(lat, lon, "_tmp_dsf.txt")
    )
    if error:
        return error
    UI.vprint(1, "-> Selecting overlays for copy/paste")
    # with: an error while writing (full disk) must not leave the files
    # open, Windows would then refuse to delete or rewrite them in tmp.
    with open(_tmp_file(lat, lon, "_tmp_dsf.txt"), "r") as f, open(
        _tmp_file(lat, lon, "_tmp_dsf_without_mesh.txt"), "w"
    ) as g:
        line = f.readline()
        g.write("PROPERTY sim/overlay 1\n")
        pol_type = 0
        pol_dict = {}
        exclude_set_updated = False
        full_ovl_exclude_pol = set(ovl_exclude_pol)
        while line:
            if "PROPERTY" in line:
                g.write(line)
            elif "POLYGON_DEF" in line:
                level = 2 if "facade" not in line else 3
                pol_dict[pol_type] = line.split()[1]
                UI.vprint(level, pol_type, ":", pol_dict[pol_type])
                pol_type += 1
                g.write(line)
            elif "NETWORK_DEF" in line:
                g.write(line)
            elif "BEGIN_POLYGON" in line:
                if not exclude_set_updated:
                    tmp = set()
                    for item in full_ovl_exclude_pol:
                        if isinstance(item, int):
                            tmp.add(item)
                        elif isinstance(item, str):
                            if item and item[0] == "!":
                                item = item[1:]
                                tmp = tmp.union(
                                    [k for k in pol_dict if item not in pol_dict[k]]
                                )
                            else:
                                tmp = tmp.union(
                                    [k for k in pol_dict if item in pol_dict[k]]
                                )
                    full_ovl_exclude_pol = tmp
                    exclude_set_updated = True
                pol_type = int(line.split()[1])
                if pol_type not in full_ovl_exclude_pol:
                    while line and ("END_POLYGON" not in line):
                        g.write(line)
                        line = f.readline()
                    g.write(line)
                else:
                    while line and ("END_POLYGON" not in line):
                        line = f.readline()
            elif "BEGIN_SEGMENT" in line:
                road_type = int(line.split()[2])
                if (
                    road_type not in ovl_exclude_net
                    and "" not in ovl_exclude_net
                    and "*" not in ovl_exclude_net
                ):
                    while line and ("END_SEGMENT" not in line):
                        g.write(line)
                        line = f.readline()
                    g.write(line)
                else:
                    while line and ("END_SEGMENT" not in line):
                        line = f.readline()
            line = f.readline()
    UI.vprint(1, "-> Converting back the text DSF to binary format")
    ovl_dsf = _tmp_file(lat, lon, "_tmp_dsf_without_mesh.dsf")
    error = _run_dsftool(
        "-text2dsf", _tmp_file(lat, lon, "_tmp_dsf_without_mesh.txt"), ovl_dsf
    )
    if error:
        return error
    dest_dir = os.path.join(
        FNAMES.Overlay_dir, "Earth nav data", FNAMES.round_latlon(lat, lon)
    )
    UI.vprint(1, "-> Copying the final overlay DSF in " + dest_dir)
    try:
        os.makedirs(dest_dir, exist_ok=True)
    except OSError as e:
        return f"could not create {dest_dir} ({e.strerror or e})."
    # Copy under a temp name first, so a failed copy never leaves a
    # truncated DSF where X-Plane would load it.
    dest_file = os.path.join(dest_dir, FNAMES.short_latlon(lat, lon) + ".dsf")
    try:
        shutil.copy(ovl_dsf, dest_file + ".tmp")
        os.replace(dest_file + ".tmp", dest_file)
    except OSError as e:
        try:
            os.remove(dest_file + ".tmp")
        except OSError:
            pass
        return f"could not write {dest_file} ({e.strerror or e})."
    return None