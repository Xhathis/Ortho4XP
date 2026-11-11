import os
import sys
import time
import shutil
import json
import re
import subprocess
import queue
import threading
import traceback
import O4_UI_Utils as UI
import O4_File_Names as FNAMES
import O4_Imagery_Utils as IMG
import O4_Vector_Map as VMAP
import O4_OSM_Utils as OSM
import O4_Mesh_Utils as MESH
import O4_Mask_Utils as MASK
import O4_DSF_Utils as DSF
import O4_Overlay_Utils as OVL
from O4_Parallel_Utils import parallel_launch, parallel_join

max_download_slots = 1
max_convert_slots = 4
batch_parallel_tiles = 1
skip_downloads = False
skip_converts = False

################################################################################
def remove_if_exists(path):
    """Delete a file during cleanup; a missing file is not an error.

    Other failures (file locked, e.g. by X-Plane, or no permission) are
    reported but don't stop the build: cleanup is not essential.
    """
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError as e:
        UI.lvprint(1, "WARNING: could not delete", path, f"({e.strerror}).")

################################################################################
def download_textures(
    tile,
    download_queue,
    convert_queue,
    workers=None,
    producer_done_event=None,
    failed=None,
):
    # failed: list that receives the attributes of textures which could not
    # be downloaded after max_attempts (build_tile won't activate the DSF).
    worker_count = max(1, workers or max_download_slots)
    UI.vprint(1, f"-> Opening download queue with {worker_count} worker(s).")

    progress_lock = threading.Lock()
    progress_state = {"done": 0, "pending": 0}
    interrupted = False
    max_attempts = 3

    def _update_progress_locked():
        denom = (
            progress_state["done"]
            + progress_state["pending"]
            + download_queue.qsize()
        )
        UI.progress_bar(2, int(100 * progress_state["done"] / denom) if denom else 100)

    def _download_task(*attrs):
        nonlocal interrupted

        if UI.red_flag:
            interrupted = True
            return 0

        attrs = tuple(attrs)
        with progress_lock:
            progress_state["pending"] += 1
            _update_progress_locked()

        # The attempts run here, in this worker. They used to go back on
        # download_queue after "pending" had dropped to 0, so the loop below
        # could see an empty queue first and send "quit": the retried
        # texture was then never downloaded nor listed in failed, and the
        # DSF was activated without it.
        ok = 0
        for attempt in range(1, max_attempts + 1):
            try:
                ok = IMG.build_jpeg_ortho(tile, *attrs)
            except Exception as err:
                UI.vprint(2, f"Download failed: {err}")
                ok = 0
            if ok or UI.red_flag:
                break
            if attempt < max_attempts:
                UI.vprint(
                    2, "Retrying texture",
                    FNAMES.dds_file_name_from_attributes(*attrs),
                    f"(attempt {attempt + 1} of {max_attempts}).",
                )

        with progress_lock:
            progress_state["pending"] -= 1
            if ok:
                progress_state["done"] += 1
            elif not UI.red_flag and failed is not None:
                failed.append(attrs)
            _update_progress_locked()
        if not ok and not UI.red_flag:
            UI.lvprint(
                1, "ERROR: Could not get texture",
                FNAMES.dds_file_name_from_attributes(*attrs),
                f"after {max_attempts} attempts.",
            )

        if ok:
            convert_queue.put((tile, *attrs))

        if UI.red_flag:
            interrupted = True

        return 1 if ok else 0

    if producer_done_event is None:
        producer_done_event = threading.Event()
        producer_done_event.set()

    workers_list = parallel_launch(_download_task, download_queue, worker_count)

    while not producer_done_event.is_set() and not UI.red_flag:
        time.sleep(0.05)

    while not UI.red_flag:
        with progress_lock:
            pending = progress_state["pending"]
        if download_queue.empty() and pending == 0:
            break
        time.sleep(0.05)

    for _ in range(worker_count):
        download_queue.put("quit")

    parallel_join(workers_list)

    UI.progress_bar(2, 100)
    if interrupted or UI.red_flag:
        UI.vprint(1, "Download process interrupted.")
        return 0
    if progress_state["done"]:
        UI.vprint(1, " *Download of textures completed.")
    return 1

################################################################################
def _convert_task(tile, *attrs):
    """One DDS conversion of step 3; an exception counts as a failed one.

    convert_texture records only a converter that fails 10 times. Anything
    else (an unreadable cached JPEG, a full disk, a bad mask PNG) raised in
    the worker, and the DSF was then activated without that texture.
    """
    try:
        IMG.convert_texture(tile, *attrs)
    except Exception as e:
        name = FNAMES.dds_file_name_from_attributes(*attrs)
        UI.lvprint(
            0, "ERROR: Could not convert texture", name,
            f"({type(e).__name__}: {e}).",
        )
        UI.vprint(1, traceback.format_exc())
        IMG.failed_conversions.append(name)
    return 1


def _remove_stale_temp_files(folder, min_age=3600):
    """Remove FNAMES.temp_path_for files a killed run left in folder.

    A DDS is converted under such a name (#49); Stop in a parallel batch
    kills the converter and leaves it. Only old ones go: in a grouped build
    dir another worker may be writing one right now.
    """
    try:
        names = os.listdir(folder)
    except OSError:
        return
    now = time.time()
    for name in names:
        if not name.startswith(".tmp"):
            continue
        path = os.path.join(folder, name)
        try:
            if now - os.path.getmtime(path) >= min_age:
                os.remove(path)
        except OSError:
            pass


################################################################################
def build_tile(tile, white_retry_follows=False):
    """Step 3. white_retry_follows: the caller retries once if imagery
    came back partly white, so that alone is not reported as an ERROR."""
    if UI.is_working:
        return 0
    UI.is_working = 1
    UI.red_flag = False
    UI.logprint(
        "Step 3 for tile lat=", tile.lat, ", lon=", tile.lon, ": starting."
    )
    UI.vprint(
        0,
        "\nStep 3 : Building DSF/Imagery for tile "
        + FNAMES.short_latlon(tile.lat, tile.lon)
        + " : \n--------\n",
    )

    if not os.path.isfile(FNAMES.mesh_file(tile.build_dir, tile.lat, tile.lon)):
        UI.lvprint(
            0, "ERROR: A mesh file must first be constructed for the tile!"
        )
        UI.exit_message_and_bottom_line("")
        return 0

    # Without a known provider every texture "could not be obtained", and
    # the cause drowned in hundreds of such lines (a batch on 2026-11-04 had
    # default_website= empty in its tile configs). Say it once, up front.
    unknown_providers = [
        code
        for code in [tile.default_website]
        + [region[2] for region in tile.zone_list]
        if code not in IMG.providers_dict
        and code not in IMG.combined_providers_dict
    ]
    if unknown_providers:
        UI.lvprint(
            0,
            "ERROR: Unknown or empty imagery provider",
            ", ".join(repr(code) for code in unknown_providers),
            "for tile",
            FNAMES.short_latlon(tile.lat, tile.lon),
            "- choose one in the GUI, or set default_website in",
            os.path.join(
                tile.build_dir,
                "Ortho4XP_" + FNAMES.short_latlon(tile.lat, tile.lon) + ".cfg",
            ),
        )
        UI.exit_message_and_bottom_line("")
        return 0

    timer = time.time()

    tile.write_to_config()

    if not IMG.initialize_local_combined_providers_dict(tile):
        UI.exit_message_and_bottom_line("")
        return 0

    try:
        if not os.path.exists(
            os.path.join(
                tile.build_dir,
                "Earth nav data",
                FNAMES.round_latlon(tile.lat, tile.lon),
            )
        ):
            os.makedirs(
                os.path.join(
                    tile.build_dir,
                    "Earth nav data",
                    FNAMES.round_latlon(tile.lat, tile.lon),
                )
            )
        if not os.path.isdir(os.path.join(tile.build_dir, "textures")):
            os.makedirs(os.path.join(tile.build_dir, "textures"))
        _remove_stale_temp_files(os.path.join(tile.build_dir, "textures"))
        if UI.cleaning_level > 1 and not tile.grouped:
            for f in os.listdir(os.path.join(tile.build_dir, "textures")):
                if f[-4:] != ".png":
                    continue
                remove_if_exists(os.path.join(tile.build_dir, "textures", f))
        if not tile.grouped:
            try:
                shutil.rmtree(os.path.join(tile.build_dir, "terrain"))
            except FileNotFoundError:
                pass
            except OSError as e:
                # Stale .ter files may remain; worth knowing when a tile
                # later shows wrong textures.
                UI.lvprint(
                    1, "WARNING: could not empty the terrain folder",
                    f"({e.strerror}: {e.filename}).",
                )
        if not os.path.isdir(os.path.join(tile.build_dir, "terrain")):
            os.makedirs(os.path.join(tile.build_dir, "terrain"))
    except Exception as e:
        UI.lvprint(0, "ERROR: Cannot create tile subdirectories.")
        UI.vprint(3, e)
        UI.exit_message_and_bottom_line("")
        return 0

    dsf_file_name = os.path.join(
        tile.build_dir,
        "Earth nav data",
        FNAMES.long_latlon(tile.lat, tile.lon) + ".dsf",
    )
    # A .tmp left by an earlier failed run must never be activated below.
    remove_if_exists(dsf_file_name + ".tmp")
    download_queue = queue.Queue()
    convert_queue = queue.Queue()

    download_launched = False
    convert_launched = False
    download_workers = max_download_slots
    failed_downloads = []
    IMG.failed_conversions.clear()
    # This run's white-filled textures only: an entry left by an earlier
    # run (whose files were deleted then) must not fail this one.
    tile_coords = FNAMES.short_latlon(tile.lat, tile.lon)
    IMG.incomplete_imgs.pop(tile_coords, None)
    dsf_result = {"ok": 0}

    def _build_dsf():
        # Runs in a thread: record the outcome, since an exception or a
        # 0 return would otherwise go unnoticed and a partial DSF could be
        # activated.
        try:
            dsf_result["ok"] = DSF.build_dsf(tile, download_queue)
        except Exception:
            UI.lvprint(0, "ERROR: building the DSF failed:")
            UI.lvprint(0, traceback.format_exc())

    build_dsf_thread = threading.Thread(target=_build_dsf)
    producer_done_event = threading.Event()

    download_thread = threading.Thread(
        target=download_textures,
        args=[
            tile,
            download_queue,
            convert_queue,
            download_workers,
            producer_done_event,
            failed_downloads,
        ],
    )
    build_dsf_thread.start()
    if not skip_downloads:
        download_thread.start()
        download_launched = True
        if not skip_converts:
            UI.vprint(
                1,
                "-> Opening convert queue and",
                max_convert_slots,
                "conversion workers.",
            )
            dico_conv_progress = {"done": 0, "bar": 3}
            convert_workers = parallel_launch(
                _convert_task,
                convert_queue,
                max_convert_slots,
                progress=dico_conv_progress,
            )
            convert_launched = True
    build_dsf_thread.join()
    producer_done_event.set()
    if download_launched:
        download_thread.join()
        if convert_launched:
            for _ in range(max_convert_slots):
                convert_queue.put("quit")
            parallel_join(convert_workers)
            if UI.red_flag:
                UI.vprint(1, "DDS conversion process interrupted.")
            elif dico_conv_progress["done"] >= 1:
                UI.vprint(1, " *DDS conversion of textures completed.")
    if UI.red_flag:
        UI.exit_message_and_bottom_line()
        return 0
    # Only activate a complete tile: a DSF that references missing textures
    # looks like a successful build but shows holes in X-Plane. Leaving it
    # inactive makes the tile count as failed (CLI exit 1, batch summary);
    # a rerun of step 3 only fetches what is missing.
    problems = []
    if not dsf_result["ok"]:
        problems.append("the DSF could not be built")
    if failed_downloads:
        problems.append(f"{len(failed_downloads)} texture(s) not downloaded")
    if IMG.failed_conversions:
        problems.append(
            f"{len(IMG.failed_conversions)} texture(s) not converted"
        )
    white_imgs = IMG.incomplete_imgs.get(tile_coords, [])
    white_problem = (
        f"{len(white_imgs)} texture(s) partly white (imagery not obtained)"
    )
    if white_imgs:
        problems.append(white_problem)
        # The white JPEG and DDS would be reused by every later run (an
        # existing DDS is never rebuilt), so the hole would stay for good.
        # Removing them makes a rerun fetch them again. The list itself
        # stays: the callers retry once when they see it.
        _delete_white_files(tile, white_imgs)
    if problems == [white_problem] and white_retry_follows:
        UI.lvprint(
            1, "Tile", tile_coords, "has", len(white_imgs),
            "partly white texture(s); the DSF was not activated, retrying.",
        )
        UI.exit_message_and_bottom_line("")
        return 0
    if problems:
        UI.lvprint(
            0, "ERROR: Tile", FNAMES.short_latlon(tile.lat, tile.lon),
            "is incomplete (" + ", ".join(problems) + "); the DSF was not",
            "activated. Run step 3 again to retry the missing parts.",
        )
        UI.exit_message_and_bottom_line("")
        return 0
    UI.vprint(1, " *Activating DSF file.")
    try:
        os.replace(dsf_file_name + ".tmp", dsf_file_name)
    except OSError as e:
        UI.lvprint(
            0, "ERROR : could not rename DSF file, tile is not active",
            f"({e.strerror}).",
        )
        UI.exit_message_and_bottom_line("")
        return 0
    if UI.cleaning_level > 1:
        remove_if_exists(FNAMES.alt_file(tile))
        remove_if_exists(FNAMES.input_node_file(tile))
        remove_if_exists(FNAMES.input_poly_file(tile))
    if UI.cleaning_level > 2 and not keep_mesh_after_step3:
        _remove_mesh_files(tile.build_dir, tile.lat, tile.lon)
    if UI.cleaning_level > 1 and not tile.grouped:
        remove_unwanted_textures(tile)
    UI.timings_and_bottom_line(timer)
    UI.logprint(
        "Step 3 for tile lat=", tile.lat, ", lon=", tile.lon, ": normal exit."
    )
    return 1

################################################################################
# cleaning_level > 2 deletes a tile's mesh and .apt after its step 3. In a
# batch, the neighbours' step 2.5 still reads that mesh
# (MASK.select_neighbor_meshes, #28): deleted at once, the masks of every
# neighbour built later lacked it, so they depended on the build order
# again. Batches set this (workers too) and delete the files at the end
# instead, see _remove_meshes_after_batch (#42).
keep_mesh_after_step3 = False


def _remove_mesh_files(build_dir, lat, lon):
    remove_if_exists(FNAMES.mesh_file(build_dir, lat, lon))
    remove_if_exists(
        os.path.join(build_dir, "Data" + FNAMES.short_latlon(lat, lon) + ".apt")
    )


def _remove_meshes_after_batch(tile, built, not_built, do_dsf):
    """cleaning_level > 2: delete the meshes the batch kept for its tiles'
    neighbours, now that every step 2.5 is done.

    built: (lat, lon) of the tiles built through the last phase. A mesh
    stays when step 3 was not part of the batch (that is what deletes it
    in a single build), and when a neighbour failed: rerunning that tile
    alone would build its masks without this mesh.
    """
    if UI.cleaning_level <= 2 or not do_dsf or not built:
        return
    failed = {coords for (coords, _) in _real_failures(not_built)}
    removed, kept = 0, []
    for (lat, lon) in built:
        coords = FNAMES.short_latlon(lat, lon)
        if {FNAMES.short_latlon(*n) for n in _neighbours(lat, lon)} & failed:
            kept.append(coords)
            continue
        _remove_mesh_files(
            FNAMES.build_dir(lat, lon, tile.custom_build_dir), lat, lon
        )
        removed += 1
    UI.vprint(1, f"Cleaning: removed the mesh of {removed} built tile(s).")
    if kept:
        UI.lvprint(
            0, "   Mesh kept (next to a failed tile, for its rerun):",
            " ".join(kept),
        )
    _remove_meshes_kept_earlier(tile, built, failed)


def _neighbours(lat, lon):
    """The 8 tiles around (lat, lon), across the antimeridian too."""
    return [
        (lat + dlat, (lon + dlon + 180) % 360 - 180)
        for dlat in (-1, 0, 1) for dlon in (-1, 0, 1) if dlat or dlon
    ]


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def _awaits_masks(tile, lat, lon):
    """True if the tile's folder holds a build that has not reached step 3:
    no DSF (e.g. step 1 failed), or a mesh newer than the DSF (steps 1-2
    run again). Its step 2.5 will want the neighbours' meshes."""
    build_dir = FNAMES.build_dir(lat, lon, tile.custom_build_dir)
    if not os.path.isdir(build_dir):
        return False
    dsf = _mtime(FNAMES.dsf_file(build_dir, lat, lon))
    mesh = _mtime(FNAMES.mesh_file(build_dir, lat, lon))
    return dsf is None or (mesh is not None and mesh > dsf)


def _remove_meshes_kept_earlier(tile, built, failed):
    """Remove the meshes an earlier batch kept next to tiles built now.

    A batch keeps a built tile's mesh next to a tile that failed ("Mesh
    kept ...", #42), for that tile's rerun. The rerun is a new batch that
    knows only its own tiles, so those meshes stayed for good (14 meshes,
    1.9 GB after the Iceland rerun of 2026-11-07). Such a neighbour of a
    tile built now loses its mesh when it is built itself (DSF not older
    than the mesh) and none of its own neighbours still awaits step 2.5.
    """
    in_batch = set(built)
    candidates = {
        n for (lat, lon) in built for n in _neighbours(lat, lon)
    } - in_batch
    removed = []
    for (lat, lon) in sorted(candidates):
        build_dir = FNAMES.build_dir(lat, lon, tile.custom_build_dir)
        mesh = _mtime(FNAMES.mesh_file(build_dir, lat, lon))
        dsf = _mtime(FNAMES.dsf_file(build_dir, lat, lon))
        if mesh is None or dsf is None or mesh > dsf:
            continue
        if any(
            FNAMES.short_latlon(*n) in failed
            or (n not in in_batch and _awaits_masks(tile, *n))
            for n in _neighbours(lat, lon)
        ):
            continue
        _remove_mesh_files(build_dir, lat, lon)
        removed.append(FNAMES.short_latlon(lat, lon))
    if removed:
        UI.lvprint(
            0, "   Cleaning: removed the mesh kept by an earlier batch of:",
            " ".join(removed),
        )


################################################################################
def build_all(tile):
    # Each step returns 0 on failure; check that as well as red_flag, since
    # not every error path raises the flag.
    step1 = VMAP.build_poly_file(tile)
    if not step1 or UI.red_flag:
        UI.exit_message_and_bottom_line("")
        return 0
    if step1 == VMAP.SEA_ONLY:
        return 1  # nothing to build (#41)
    if not MESH.build_mesh(tile) or UI.red_flag:
        UI.exit_message_and_bottom_line("")
        return 0
    if not MASK.build_masks(tile) or UI.red_flag:
        UI.exit_message_and_bottom_line("")
        return 0
    ok = build_tile_retrying_white(tile)
    if not ok or UI.red_flag:
        UI.exit_message_and_bottom_line("")
        return 0
    UI.is_working = 0
    return 1


def build_tile_retrying_white(tile):
    """Step 3, run once more if some imagery came back partly white.

    build_tile does not activate such a tile and deletes the white files,
    so the second run downloads them again. If they are still white, the
    tile stays inactive and counts as failed.
    """
    ok = build_tile(tile, white_retry_follows=True)
    tile_coords = FNAMES.short_latlon(tile.lat, tile.lon)
    if not ok and not UI.red_flag and tile_coords in IMG.incomplete_imgs:
        UI.lvprint(
            1,
            f"Attempting to rebuild textures with white squares: "
            f"{IMG.incomplete_imgs[tile_coords]}",
        )
        ok = build_tile(tile)
    return ok

################################################################################
def build_tile_list(
    tile, list_lat_lon, do_osm, do_mesh, do_mask, do_dsf, do_ovl, override_cfg
):
    if UI.is_working:
        return 0
    UI.red_flag = 0
    UI.stop_requested = False
    flags = (do_osm, do_mesh, do_mask, do_dsf, do_ovl, override_cfg)
    global keep_mesh_after_step3
    keep_mesh_after_step3 = True
    _batch_leftover.clear()
    _batch_leftover.extend(list_lat_lon)
    write_leftover_tiles(_batch_leftover)
    try:
        if batch_parallel_tiles > 1 and len(list_lat_lon) > 1:
            return _build_tile_list_parallel(tile, list_lat_lon, flags)
        return _build_tile_list_sequential(tile, list_lat_lon, flags)
    finally:
        keep_mesh_after_step3 = False


def _build_tile_list_sequential(tile, list_lat_lon, flags):
    timer = time.time()
    UI.lvprint(
        0, "Batch build launched for a number of", len(list_lat_lon), "tiles."
    )
    failed_tiles = []  # (tile coords, step) of tiles skipped after an error
    built = []  # (lat, lon) of tiles through the last phase
    phases = _batch_phases(flags)
    todo = list(list_lat_lon)
    # Same two phases as the parallel batch: a tile's masks also use its
    # neighbours' meshes, so all meshes must exist before any masks.
    for (p, (name, steps)) in enumerate(phases):
        if len(phases) > 1:
            UI.vprint(0, f"Batch phase {p + 1}/{len(phases)}: {name}")
        last_phase = p == len(phases) - 1
        # Step 1 waits out Overpass outages (#81).
        gate = _OverpassGate() if steps[0] else None
        pending = list(todo)
        while pending:
            if gate:
                gate.poll(pending)
            i = _next_startable(pending, gate)
            if i is None:
                # Nothing may start now: Overpass gives no answer, or the
                # tiles left wait for their next try.
                if not _sleep_unless_stop(1):
                    UI.lvprint(0, "Batch stopped while waiting for Overpass.")
                    UI.exit_message_and_bottom_line()
                    return 0
                continue
            (lat, lon) = pending.pop(i)
            tile_coords = FNAMES.short_latlon(lat, lon)
            UI.vprint(1, "Dealing with tile", tile_coords, f"({len(pending)} "
                      "more in this phase)")
            needed = gate.needs_overpass(lat, lon) if gate else False
            failed_step = _build_one_tile(tile, lat, lon, *steps)
            if needed and _step1_passed(failed_step):
                gate.answered()
            if failed_step == SEA_SKIPPED:
                # Open sea, nothing to build (#41): not a failure, but
                # no later phase either.
                failed_tiles.append((tile_coords, SEA_SKIPPED))
                UI.is_working = False
                _remove_from_todo_map(lat, lon)
                continue
            if failed_step:
                if UI.stop_requested:
                    # The user pressed Stop: end the whole batch.
                    UI.exit_message_and_bottom_line()
                    return 0
                UI.red_flag = False
                UI.is_working = False
                if (gate and _failed_on_overpass(failed_step)
                        and gate.failed(lat, lon)):
                    pending.append((lat, lon))
                    continue
                # An error in this tile: the step has already reported
                # it and left the previous files in place. Skip the
                # tile so a long unattended batch still builds the
                # others.
                UI.lvprint(
                    0, "ERROR: Tile", tile_coords, "failed in step",
                    failed_step, "- skipped, continuing with the next "
                    "tile.",
                )
                failed_tiles.append((tile_coords, failed_step))
                continue
            if last_phase:
                _remove_from_todo_map(lat, lon)
                built.append((lat, lon))
        failed = {coords for (coords, _) in failed_tiles}
        todo = [(lat, lon) for (lat, lon) in todo
                if FNAMES.short_latlon(lat, lon) not in failed]
    _remove_meshes_after_batch(tile, built, failed_tiles, flags[3])
    _batch_summary(timer, len(list_lat_lon), failed_tiles)
    if IMG.incomplete_imgs:
        UI.lvprint(
            0,
            f"\nERROR: Parts of the following images could not be obtained "
            f"(tile not activated; run step 3 again to retry): "
            f"{IMG.incomplete_imgs}",
        )
    return 0 if _real_failures(failed_tiles) else 1


# Order matters: a batch worker's exit code is 10 + the index of its failed
# step (see batch_worker and _build_tile_list_parallel).
BATCH_STEPS = (
    "1 (vector data)", "2 (mesh)", "2.5 (masks)", "3 (DSF/imagery)", "overlay"
)
# Step 1 found open sea (VMAP.SEA_ONLY): listed with the failed tiles so
# that no later phase runs, but counted apart and not an error (#41).
SEA_SKIPPED = "sea only"
SEA_EXIT_CODE = 3  # a batch worker's exit code for SEA_SKIPPED
# A batch worker's exit code when step 1 failed only because Overpass gave
# no answer (OSM.overpass_gave_up): the batch tries such tiles again.
OVERPASS_EXIT_CODE = 4
# Overpass outages (#44, #46, #78, #81). In the 346-tile batch of
# 2026-11-08 Overpass failed for about 40 of 53 hours: tiles kept starting
# into the outage (221 failed step 1 tries, ~28 min each, 78 % of the
# phase's worker time), and the retry pass at the end of the phase took
# 20.7 h. Now, once overpass_pause_after tiles in a row lost step 1 to
# Overpass, no tile whose step 1 needs Overpass starts (tiles with all OSM
# layers cached go on) until a real query on the first held tile is
# answered, asked every overpass_probe_interval seconds, at most
# overpass_wait_max. A tile that lost step 1 to Overpass goes back into the
# queue, not before overpass_retry_wait seconds, and fails for good after
# overpass_tile_tries such failures. Since #83 a failed step 1 has already
# asked every server (in ~1 min when they are down), so the batch pauses on
# the first such tile (was 3).
overpass_pause_after = 1
overpass_tile_tries = 3
overpass_retry_wait = 600
overpass_probe_interval = 300
overpass_wait_max = 6 * 3600
# The cached OSM layers of a tile (FNAMES.osm_cached): a tile with all of
# them needs no Overpass in step 1. small_roads is missing below road_level
# 2, which only holds such a tile back during a pause too.
OSM_LAYERS = ("coastline", "airports", "big_roads", "small_roads", "water")


def _real_failures(not_built):
    return [(c, s) for (c, s) in not_built if s != SEA_SKIPPED]


def _failed_on_overpass(failed_step):
    """True if a tile's step 1 stopped because Overpass gave no answer."""
    return (
        failed_step == BATCH_STEPS[0]
        and OSM.overpass_gave_up
        and not UI.stop_requested
    )


def _step1_passed(failed_step):
    """True if the tile got through step 1 (so Overpass answered it)."""
    return failed_step in (None, SEA_SKIPPED) or failed_step in BATCH_STEPS[1:]


def _run_in_background(fn):
    """Run fn in a daemon thread; the list returned gets bool(result).

    The Overpass probe can take minutes (90 s read timeout per server); the
    parallel batch must go on polling and starting its workers meanwhile.
    """
    out = []

    def run():
        try:
            out.append(bool(fn()))
        except Exception:  # a failed probe is no answer, never a crash
            out.append(False)

    threading.Thread(target=run, daemon=True).start()
    return out


def _next_startable(pending, gate):
    """Index of the first tile in pending that may start now, or None."""
    for (i, (lat, lon)) in enumerate(pending):
        if gate is None or gate.can_start(lat, lon):
            return i
    return None


class _OverpassGate:
    """Step 1 of a batch phase during Overpass outages (#81).

    The batch asks can_start() before it starts a tile, reports each step 1
    result of a tile that needed Overpass (answered / failed) and calls
    poll() regularly with the tiles not started yet.
    """

    def __init__(self):
        self.in_row = 0  # tiles in a row that lost step 1 to Overpass
        self.paused = None  # time.time() of the pause, None when open
        self.next_probe = 0.0
        self.probes = 0
        self.probe = None  # result list of the running probe
        self.tries = {}  # (lat, lon) -> step 1 tries lost to Overpass
        self.not_before = {}  # (lat, lon) -> earliest time of its next try
        self._needs = {}

    def needs_overpass(self, lat, lon):
        key = (lat, lon)
        if key not in self._needs:
            self._needs[key] = not all(
                os.path.isfile(FNAMES.osm_cached(lat, lon, layer))
                for layer in OSM_LAYERS
            )
        return self._needs[key]

    def can_start(self, lat, lon):
        if time.time() < self.not_before.get((lat, lon), 0.0):
            return False
        return self.paused is None or not self.needs_overpass(lat, lon)

    def answered(self):
        """A tile that needed Overpass got through step 1."""
        self.in_row = 0
        if self.paused is not None:
            self._resume(
                "Overpass answered a tile's step 1 again after "
                + UI.nicer_timer(time.time() - self.paused)
                + ": starting the held tiles."
            )

    def failed(self, lat, lon):
        """A tile lost step 1 to Overpass; True if it gets another try."""
        now = time.time()
        key = (lat, lon)
        self._needs[key] = True
        self.in_row += 1
        n = self.tries[key] = self.tries.get(key, 0) + 1
        coords = FNAMES.short_latlon(lat, lon)
        again = n < overpass_tile_tries
        if again:
            self.not_before[key] = now + overpass_retry_wait
            UI.lvprint(
                0, "Tile", coords, "failed in step", BATCH_STEPS[0],
                f"(no answer from Overpass, try {n} of {overpass_tile_tries})"
                " - it will be tried again"
                + (f", not before {UI.nicer_timer(overpass_retry_wait)}"
                   if overpass_retry_wait >= 1 else "") + ".",
            )
        else:
            UI.lvprint(
                0, "Tile", coords, f"got no answer from Overpass in {n} tries.",
            )
        if self.paused is None and self.in_row >= overpass_pause_after:
            self.paused = now
            self.probes = 0
            self.probe = None
            self.next_probe = now + overpass_probe_interval
            UI.lvprint(
                0, f"Overpass failed {self.in_row} tiles in a row: tiles whose "
                "step 1 needs Overpass wait until it answers again (checked "
                f"every {UI.nicer_timer(overpass_probe_interval)}, at most "
                f"{UI.nicer_timer(overpass_wait_max)}); the others go on.",
            )
        return again

    def poll(self, pending):
        """While paused, probe Overpass now and then; reopen on an answer."""
        if self.paused is None:
            return
        now = time.time()
        if self.probe is not None:
            if not self.probe:
                return  # still asking
            ok = self.probe[0]
            self.probe = None
            self.probes += 1
            if ok:
                self._resume(
                    "Overpass answers again after "
                    + UI.nicer_timer(now - self.paused)
                    + ": starting the held tiles."
                )
                return
            self.next_probe = now + overpass_probe_interval
        if now - self.paused >= overpass_wait_max:
            self._resume(
                "Overpass still gives no answer after "
                + UI.nicer_timer(now - self.paused)
                + ": starting the held tiles anyway."
            )
            return
        if now < self.next_probe:
            return
        held = [t for t in pending if self.needs_overpass(*t)]
        if held:
            (lat, lon) = held[0]
            self.probe = _run_in_background(
                lambda: OSM.overpass_answers((lat, lon, lat + 1, lon + 1))
            )

    def _resume(self, message):
        UI.lvprint(0, message)
        self.paused = None
        self.in_row = 0
        self.probe = None


def _sleep_unless_stop(seconds):
    """Sleep, checking the Stop button every second; False if pressed."""
    end = time.time() + seconds
    while time.time() < end:
        if UI.stop_requested:
            return False
        time.sleep(min(1.0, max(0.0, end - time.time())))
    return not UI.stop_requested


def _batch_phases(flags):
    """The phases of a batch: [(name, flags for _build_one_tile)].

    Steps 1-2 for every tile, then steps 2.5-3 and overlays: the masks of
    a tile also use the meshes of its neighbours (#28,
    MASK.select_neighbor_meshes). Phases with no step ticked are left out.
    """
    (do_osm, do_mesh, do_mask, do_dsf, do_ovl, override_cfg) = flags
    return [
        (name, steps + (override_cfg,)) for (name, steps) in (
            ("steps 1-2", (do_osm, do_mesh, False, False, False)),
            ("steps 2.5-3", (False, False, do_mask, do_dsf, do_ovl)),
        ) if any(steps)
    ]


def _build_one_tile(tile, lat, lon, *flags):
    """Build one tile of a batch; return the failed step or None.

    An unexpected exception (a bug, odd OSM geometry, a full disk) fails
    only this tile: in a sequential batch it used to end the whole batch
    without a summary and leave UI.is_working set, so the GUI refused any
    further work until restarted. A parallel worker returns the step's
    exit code instead of a bare traceback exit.
    """
    current = ["tile setup"]
    try:
        return _build_one_tile_steps(tile, lat, lon, current, *flags)
    except Exception:
        UI.lvprint(
            0, "ERROR: unexpected error in tile",
            FNAMES.short_latlon(lat, lon), "during step", current[0] + ":",
        )
        UI.lvprint(0, traceback.format_exc())
        return current[0]


def _build_one_tile_steps(
    tile, lat, lon, current,
    do_osm, do_mesh, do_mask, do_dsf, do_ovl, override_cfg
):
    """The steps of _build_one_tile; current[0] names the running step."""
    (tile.lat, tile.lon) = (lat, lon)
    tile.build_dir = FNAMES.build_dir(tile.lat, tile.lon, tile.custom_build_dir)
    tile.dem = None
    if override_cfg:
        tile.read_from_config(use_global=True)
    else:
        tile.read_from_config()
    if do_osm or do_mesh or do_dsf:
        tile.make_dirs()
    # A step failed if it returned 0 or raised red_flag; not every error
    # path raises the flag (e.g. Triangle4XP giving up in step 2).
    if do_osm:
        current[0] = BATCH_STEPS[0]
        OSM.overpass_gave_up = False
        step1 = VMAP.build_poly_file(tile)
        if not step1 or UI.red_flag:
            return BATCH_STEPS[0]
        if step1 == VMAP.SEA_ONLY:
            return SEA_SKIPPED
    if do_mesh:
        current[0] = BATCH_STEPS[1]
        if not MESH.build_mesh(tile) or UI.red_flag:
            return BATCH_STEPS[1]
    if do_mask:
        current[0] = BATCH_STEPS[2]
        if not MASK.build_masks(tile) or UI.red_flag:
            return BATCH_STEPS[2]
    if do_dsf:
        current[0] = BATCH_STEPS[3]
        ok = build_tile_retrying_white(tile)
        if not ok or UI.red_flag:
            return BATCH_STEPS[3]
    if do_ovl:
        current[0] = BATCH_STEPS[4]
        if not OVL.build_overlay(lat, lon) or UI.red_flag:
            return BATCH_STEPS[4]
    return None


# The tiles of the last batch not done yet, kept in a file so that the
# tile window can select them again after the GUI (or the PC: a Windows
# Update restart killed a 346-tile batch on 2026-11-11) was closed.
LEFTOVER_FILE = ".last_batch_tiles.txt"
_batch_leftover = []  # (lat, lon) of the running batch not done yet


def leftover_tiles_path():
    return FNAMES.resource_path(LEFTOVER_FILE)


def write_leftover_tiles(tiles):
    """Record tiles ([(lat, lon)]) as the last batch's tiles not done.

    No tiles: the file is removed. A failed write only costs the
    preselection, so it is reported and the batch goes on.
    """
    path = leftover_tiles_path()
    try:
        if not tiles:
            if os.path.exists(path):
                os.remove(path)
            return
        FNAMES.write_text_atomic(
            path,
            "# Tiles of the last batch not built yet (failed, stopped or not"
            " started), " + time.strftime("%Y-%m-%d %H:%M") + ".\n"
            "# The tile window selects them when it opens.\n"
            + "".join(FNAMES.short_latlon(lat, lon) + "\n"
                      for (lat, lon) in tiles),
        )
    except OSError as e:
        UI.vprint(1, "   Could not update", path, f"({e})")


def read_leftover_tiles():
    """[(lat, lon)] from the leftover file, [] if there is none.

    The file is plain text and may have been edited by hand: lines that
    are not a tile are skipped, duplicates dropped.
    """
    tiles = []
    try:
        with open(leftover_tiles_path(), encoding="utf-8",
                  errors="replace") as f:
            for line in f:
                tile = _parse_short_latlon(line.strip())
                if tile and tile not in tiles:
                    tiles.append(tile)
    except FileNotFoundError:
        pass
    except OSError as e:
        UI.vprint(1, "   Could not read", leftover_tiles_path(), f"({e})")
    return tiles


def _parse_short_latlon(text):
    m = re.fullmatch(r"([+-]\d{2})([+-]\d{3})", text)
    if not m:
        return None
    (lat, lon) = (int(m.group(1)), int(m.group(2)))
    if -90 <= lat < 90 and -180 <= lon < 180:
        return (lat, lon)
    return None


def _remove_from_todo_map(lat, lon):
    """A tile of the batch is done: off the map's selection and the file."""
    if (lat, lon) in _batch_leftover:
        _batch_leftover.remove((lat, lon))
        write_leftover_tiles(_batch_leftover)
    try:
        UI.gui.earth_window.canvas.delete(
            UI.gui.earth_window.dico_tiles_todo[(lat, lon)]
        )
        UI.gui.earth_window.dico_tiles_todo.pop((lat, lon), None)
    except Exception:
        # Cosmetic only: no GUI (AttributeError), tile not on the map
        # (KeyError) or Earth window closed (tkinter.TclError).
        pass


def _batch_summary(timer, nbr_tiles, not_built):
    UI.lvprint(
        0, "Batch process completed in", UI.nicer_timer(time.time() - timer)
    )
    failed_tiles = _real_failures(not_built)
    sea = [coords for (coords, step) in not_built if step == SEA_SKIPPED]
    UI.lvprint(
        0, f"Tiles built: {nbr_tiles - len(not_built)}, "
        + (f"skipped (open sea): {len(sea)}, " if sea else "")
        + f"failed: {len(failed_tiles)}."
    )
    if sea:
        UI.lvprint(0, "   Open sea, nothing built:", " ".join(sea))
    for (coords, step) in failed_tiles:
        UI.lvprint(0, f"   FAILED: {coords} in step {step}")


def batch_worker(tile, flags):
    """Build one tile for a parallel batch, in its own process.

    flags is the "0"/"1" string of (osm, mesh, mask, dsf, ovl, override).
    Returns the exit code: 0 when built, SEA_EXIT_CODE for open sea,
    OVERPASS_EXIT_CODE when step 1 failed for want of an Overpass answer,
    10 + index in BATCH_STEPS when a step failed otherwise.
    """
    UI.red_flag = 0
    UI.stop_requested = False
    global keep_mesh_after_step3
    # The parent deletes the meshes once the whole batch is done (#42).
    keep_mesh_after_step3 = True
    failed_step = _build_one_tile(
        tile, tile.lat, tile.lon, *(c == "1" for c in flags)
    )
    if IMG.incomplete_imgs:
        UI.lvprint(
            0,
            f"ERROR: Parts of the following images could not be obtained "
            f"(tile not activated; run step 3 again to retry): "
            f"{IMG.incomplete_imgs}",
        )
    if failed_step is None:
        return 0
    if failed_step == SEA_SKIPPED:
        return SEA_EXIT_CODE
    if _failed_on_overpass(failed_step):
        return OVERPASS_EXIT_CODE
    if failed_step in BATCH_STEPS:
        return 10 + BATCH_STEPS.index(failed_step)
    return 1  # "tile setup": the parent reports the exit code


def _kill_process_tree(proc):
    """Stop a batch worker and the tools it started (Triangle4XP, ...)."""
    if sys.platform == "win32":
        # terminate() would leave the worker's own child processes running.
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
            capture_output=True,
        )
    else:
        proc.kill()
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        pass


def _build_tile_list_parallel(tile, list_lat_lon, flags):
    """Build the tiles of a batch in up to batch_parallel_tiles processes.

    Each tile runs in its own Ortho4XP.py --batch-worker process: tile
    settings are module globals, so tiles cannot share one process. Fresh
    tiles mostly wait on Overpass and imagery servers, which is what makes
    running a few at once worth it.

    Two phases: steps 1-2, then steps 2.5-3 (and overlays). The masks of a
    tile also use the meshes of its neighbours (MASK.select_neighbor_meshes),
    so a tile starts steps 2.5-3 only once it and its neighbours in the
    batch are through steps 1-2 (#82; before, all tiles of the batch had
    to be); otherwise its masks would depend on which neighbour happened to
    finish its mesh first. Each phase runs up to batch_parallel_tiles
    workers, so imagery downloads overlap the Overpass requests of others.
    """
    nbr_slots = min(batch_parallel_tiles, len(list_lat_lon))
    timer = time.time()
    phases = _batch_phases(flags)
    UI.lvprint(
        0, "Batch build launched for a number of", len(list_lat_lon),
        "tiles,", nbr_slots, "in parallel"
        + (" per phase." if len(phases) > 1 else "."),
    )
    if len(phases) > 1:
        UI.vprint(
            0, f"Batch phases: {phases[0][0]}, then {phases[1][0]} once a "
            "tile and its neighbours in the batch are through the first.",
        )
    built = []  # (lat, lon) of tiles through the last phase
    # The provider, zoomlevel and custom zones picked in the GUI only live
    # in this process (CFG globals, copied into tile); a tile without its
    # own config takes them from there. Workers are new processes that
    # only read Ortho4XP.cfg, where they are not stored: hand them over.
    context_file = os.path.join(FNAMES.Tmp_dir, "batch_context.json")
    with open(context_file, "w", encoding="utf-8") as f:
        json.dump(
            {
                "default_website": tile.default_website,
                "default_zl": tile.default_zl,
                "zone_list": tile.zone_list,
            },
            f,
        )
    UI.is_working = 1
    try:
        failed_tiles = _run_batch_phases(
            tile, list_lat_lon,
            [(name, steps, k == len(phases) - 1)
             for (k, (name, steps)) in enumerate(phases)],
            nbr_slots, context_file, built=built,
            gate=_OverpassGate() if phases and phases[0][1][0] else None,
        )
        if failed_tiles is None:  # Stop button
            return 0
    finally:
        UI.is_working = 0
        try:
            os.remove(context_file)
        except OSError:
            pass
    _remove_meshes_after_batch(tile, built, failed_tiles, flags[3])
    _batch_summary(timer, len(list_lat_lon), failed_tiles)
    return 0 if _real_failures(failed_tiles) else 1


def _worker_env():
    """Environment of a --batch-worker process.

    The worker's output goes to its tmp log, which _run_batch_phases opens
    as UTF-8; without PYTHONIOENCODING the worker would write it in the
    ANSI code page and crash on names it cannot encode (a Polish airport
    in +54+015 failed step 1).
    """
    return dict(
        UI.subprocess_env(), PYTHONUNBUFFERED="1",
        PYTHONIOENCODING="utf-8:backslashreplace",
    )


def _run_batch_phase(
    tile, list_lat_lon, flags, nbr_slots, last_phase, context_file,
    built=None, gate=None,
):
    """One phase of a parallel batch for list_lat_lon (see _run_batch_phases)."""
    return _run_batch_phases(
        tile, list_lat_lon, [("", flags, last_phase)], nbr_slots,
        context_file, built=built, gate=gate,
    )


def _phase2_ready(lat, lon, in_batch, ended1):
    """True when (lat, lon) and its neighbours in the batch are through
    phase 1 (#82): its masks read their meshes (#28)."""
    return (lat, lon) in ended1 and all(
        n in ended1 for n in _neighbours(lat, lon) if n in in_batch
    )


def _run_batch_phases(
    tile, list_lat_lon, phases, nbr_slots, context_file, built=None,
    gate=None,
):
    """Run one worker per tile and phase, up to nbr_slots per phase.

    phases: [(name, flags for _build_one_tile, last phase of the batch?)],
    one or two. A tile starts the second once it and its neighbours in
    list_lat_lon have ended the first (built, failed or open sea): their
    meshes are final then. Returns the list of (coords, failed step), or
    None after Stop. Tiles through the batch's last phase are added to
    built (when given). With a gate (_OverpassGate, first phase with step
    1), a tile whose step 1 found no Overpass answer goes back into the
    queue while it has tries left, and tiles that need Overpass are held
    back during an outage; without one it is a step 1 failure.
    """
    script = FNAMES.resource_path("Ortho4XP.py")
    # A frozen (PyInstaller) build is its own interpreter and script.
    launcher = [sys.executable] if getattr(sys, "frozen", False) else [
        sys.executable, script]
    flag_strings = ["".join("1" if f else "0" for f in flags)
                    for (_, flags, _) in phases]
    creationflags = (
        subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    )
    env = _worker_env()
    in_batch = set(list_lat_lon)
    queues = [list(list_lat_lon)] + [[] for _ in phases[1:]]
    ended1 = set()  # tiles through phase 1, whatever the result
    # proc -> (phase, lat, lon, coords, log path, log file, start)
    running = {}
    failed_tiles = []
    started = [0] * len(phases)
    needed = {}  # (lat, lon) -> needed Overpass when started

    def next_tile(p):
        if p == 0:
            return _next_startable(queues[0], gate)
        for (i, (lat, lon)) in enumerate(queues[p]):
            if _phase2_ready(lat, lon, in_batch, ended1):
                return i
        return None

    def end_phase1(lat, lon, ok):
        ended1.add((lat, lon))
        if ok and len(phases) > 1:
            queues[1].append((lat, lon))

    while any(queues) or running:
        if gate:
            gate.poll(queues[0])
        for p in range(len(phases)):
            while queues[p] and not UI.stop_requested and sum(
                    1 for info in running.values() if info[0] == p
            ) < nbr_slots:
                i = next_tile(p)
                if i is None:
                    break  # held back (Overpass, retry wait, neighbours)
                (lat, lon) = queues[p].pop(i)
                if gate and p == 0:
                    needed[(lat, lon)] = gate.needs_overpass(lat, lon)
                started[p] += 1
                coords = FNAMES.short_latlon(lat, lon)
                log_path = os.path.join(FNAMES.Tmp_dir, f"batch_{coords}.log")
                log_file = open(log_path, "w", encoding="utf-8")
                proc = subprocess.Popen(
                    launcher + ["--batch-worker", str(lat), str(lon),
                                flag_strings[p], tile.custom_build_dir or "",
                                context_file],
                    stdout=log_file, stderr=subprocess.STDOUT,
                    cwd=os.path.dirname(script), env=env,
                    creationflags=creationflags,
                )
                running[proc] = (p, lat, lon, coords, log_path, log_file,
                                 time.time())
                n_running = sum(1 for info in running.values()
                                if info[0] == p)
                UI.vprint(
                    0, f"Tile {coords} started"
                    + (f" ({phases[p][0]})" if len(phases) > 1 else "")
                    + f" ({started[p]}/{len(list_lat_lon)}, {n_running} "
                    f"running), output in {log_path}",
                )
        if UI.stop_requested:
            for (proc, info) in running.items():
                _kill_process_tree(proc)
                info[5].close()
            UI.lvprint(
                0, "Batch stopped:", len(running), "running tile(s)",
                "interrupted,", sum(len(q) for q in queues),
                "waiting to start.",
            )
            UI.exit_message_and_bottom_line()
            return None
        for proc in list(running):
            code = proc.poll()
            if code is None:
                continue
            (p, lat, lon, coords, log_path, log_file, start) = running.pop(proc)
            log_file.close()
            last_phase = phases[p][2]
            if p == 0 and needed.get((lat, lon)) and (
                    code in (0, SEA_EXIT_CODE)
                    or 11 <= code < 10 + len(BATCH_STEPS)):
                gate.answered()  # it got through step 1
            if code == 0:
                UI.vprint(
                    0, f"Tile {coords}", "built" if last_phase else "done",
                    "in", UI.nicer_timer(time.time() - start),
                )
                if last_phase:
                    _remove_from_todo_map(lat, lon)
                    if built is not None:
                        built.append((lat, lon))
                if p == 0:
                    end_phase1(lat, lon, True)
                try:
                    os.remove(log_path)  # keep tmp clean; errors keep it
                except OSError:
                    pass
                continue
            if code == SEA_EXIT_CODE:
                UI.vprint(0, f"Tile {coords} is open sea, nothing to build.")
                _remove_from_todo_map(lat, lon)
                failed_tiles.append((coords, SEA_SKIPPED))
                if p == 0:
                    end_phase1(lat, lon, False)
                try:
                    os.remove(log_path)
                except OSError:
                    pass
                continue
            if (p == 0 and code == OVERPASS_EXIT_CODE and gate
                    and gate.failed(lat, lon)):
                queues[0].append((lat, lon))
                continue
            if code == OVERPASS_EXIT_CODE:
                step = BATCH_STEPS[0]
            elif 10 <= code < 10 + len(BATCH_STEPS):
                step = BATCH_STEPS[code - 10]
            else:
                step = f"? (worker exit code {code})"
            UI.lvprint(
                0, "ERROR: Tile", coords, "failed in step", step,
                "- skipped, see", log_path,
            )
            failed_tiles.append((coords, step))
            if p == 0:
                end_phase1(lat, lon, False)
        time.sleep(0.5)
    return failed_tiles

################################################################################
def remove_unwanted_textures(tile):
    texture_list = []
    for f in os.listdir(os.path.join(tile.build_dir, "terrain")):
        if f[-4:] != ".ter":
            continue
        if f[-5] == "y":  # water overlay
            texture_list.append("_".join(f[:-4].split("_")[:-2]) + ".dds")
        if f[-5] == "a":  # sea
            texture_list.append("_".join(f[:-4].split("_")[:-1]) + ".dds")
        else:
            texture_list.append(f.replace(".ter", ".dds"))
    for f in os.listdir(os.path.join(tile.build_dir, "textures")):
        if f[-4:] != ".dds":
            continue
        if f not in texture_list:
            print("Removing obsolete texture", f)
            remove_if_exists(os.path.join(tile.build_dir, "textures", f))

def _delete_white_files(tile, file_names):
    """Delete the orthophoto JPEGs with white squares and their DDS."""
    # download_jpeg_ortho files them under the tile's own imagery folder
    # (that folder's name is how incomplete_imgs is keyed), so only that
    # folder is searched, not the whole imagery cache.
    imagery_dir = os.path.join(
        FNAMES.Imagery_dir, FNAMES.long_latlon(tile.lat, tile.lon)
    )
    for file_name in file_names:
        file_name_dds = os.path.splitext(file_name)[0] + ".dds"
        for (top, name) in ((imagery_dir, file_name),
                            (tile.build_dir, file_name_dds)):
            for root, _, files in os.walk(top):
                if name in files:
                    file_path = os.path.join(root, name)
                    remove_if_exists(file_path)
                    if not os.path.exists(file_path):
                        UI.lvprint(1, f"Deleted: {name} in {file_path}")
