# CLAUDE.md — Ortho4XP fork (Xhathis/Ortho4XP)

Guidance for Claude Code working in this repository.

## Project

- Fork of Ortho4XP (upstream: shred86 / oscarpilote), used to build orthophoto
  scenery tiles for **X-Plane 12**.
- Goal: find and fix bugs, make the code more robust, and make batch builds
  more error-tolerant. Correctness first, refactors second.
- Platform: **Windows only.** Development, builds and testing all happen on
  this machine. Linux/macOS code paths are not tested here; don't break them
  on purpose, but they are not a target.
- Python **3.13** (matches the bundled wheels in `Utils/win/`:
  `gdal-3.12.2-cp313`, `scikit_fmm-2025.6.23-cp313`).
- Commit identity: `Xhathis <262661273+Xhathis@users.noreply.github.com>`.

## Layout (main parts)

- `Ortho4XP.py` — entry point (GUI by default, also CLI).
- `src/O4_*.py` — all live code. Largest modules: `O4_Imagery_Utils` (download
  and imagery), `O4_GUI_Utils` (Tkinter GUI), `O4_Config_Utils`,
  `O4_Airport_Utils`, `O4_DSF_Utils`, `O4_Vector_Utils`, `O4_Mask_Utils`.
- `src/Unused/` — dead code, not imported. Ignore unless asked.
- `Utils/win/` — bundled Windows tools: `Triangle4XP.exe`, `DSFTool.exe`,
  `nvcompress`, `7z.exe`, `moulinette.exe`, plus the wheels above.
- `Providers/`, `Filters/`, `Patches/` — data/config, not code.
- Concurrency is **threads only** (`threading`), no `multiprocessing`.
- There are **no tests**. A real tile build is currently the only check.

## Safety rules (must follow)

1. **Never write into X-Plane folders** (in particular `Custom Scenery`).
   Build output goes only to a dedicated folder inside or next to this repo
   (e.g. `G:\Ortho4XP\Tiles` or a separate build dir configured in the .cfg).
   The user copies tiles into X-Plane manually.
2. Ask before installing or upgrading packages, or changing anything outside
   this repo.
3. Builds are heavy (CPU, RAM, disk, network). Say before starting one, and
   don't start a second one in parallel.
4. Don't delete cached imagery/OSM/DEM data without asking — it is slow to
   re-download.

## Git workflow

- `master` — untouched mirror of upstream. Never commit directly to it.
- `fix/<short-name>` — one topic per branch, small focused commits.
- `test` — merges of fix branches that are ready for a test build.
- `dev` — fixes that have passed a test build.
- One logical change per commit so a regression can be bisected.
- Mark commits that touch Windows-only branches (`sys.platform` / `os.name`)
  or the bundled `.exe` tools in the message.
- Commit or push only when the user asks.

## Testing method

There is no test suite, so every change is checked against a **baseline**:

1. Build the agreed reference tile from unmodified `master`; keep its log,
   masks (PNG), and the DSF/terrain output as the baseline. (Reference tile,
   zoom level and provider: ask the user if not recorded below.)
2. Build the same tile, same config, from the branch under test.
3. Compare: log errors/warnings, masks pixel by pixel, DSF contents
   (`DSFTool.exe --dsf2text`, then diff). Explain every difference — an
   unexplained difference is a failure, even if the tile "looks fine".
4. Where possible add `pytest` tests for pure functions (coordinate
   conversion in `O4_Geo_Utils`, file naming in `O4_File_Names`, config
   parsing) before refactoring them.

Reference tile: `+55+012` (lat 55, lon 12 — Zealand / Copenhagen, Denmark).
Provider `Arc` (Esri World Imagery, `Providers/Global/Arc.lay`), ZL 17.
Build output: `G:\Ortho4XP\Tiles` (default; no custom build dir).
Baseline: `G:\Ortho4XP_baseline\+55+012_Arc_ZL17_master-3cff870_cached\`
(see its `BASELINE.txt` and `SHA256SUMS`), built from cached inputs only.
Before a test build, check `OSM_data\+50+010\+55+012\*.osm.bz2` against its
`SHA256SUMS`; compare masks and DSF by hash, then `--dsf2text` diff (skip the
header lines with the file path). The order of "Created …png" lines in
`console.log` varies between runs (parallel threads) and is not a difference.
Older folders, reference only: no suffix = invalid (no inland water, #7);
`_run2` = superseded (fresh water download, #9).
Test builds go to `G:\Ortho4XP_tests\<tile>_<provider>_<ZL>_<branch>-<sha>\`.
Test helpers (run from the repo root with the venv Python) are in
`G:\Ortho4XP_tests\tools\`: `run_masks.py` (step 2.5 only, optional
custom extent / alternative module dir), `sim_osm_failure.py` (CLI
build with a simulated Overpass failure on the water layer) and
`sim_water_geometry_failure.py` (CLI build where cleaning the inland
water geometry fails), `sim_mask_dem_failure.py` (CLI build where the
DEM for masks fails in step 2.5), `sim_batch.py error|stop` (batch
of 3, steps 1-2.5, with an error or a Stop on tile 2) and
`gui_smoke.py` (scripted run of the real GUI: Earth and config
windows, tile selection; no downloads, no Custom Scenery links; back
up .last_gui_params.txt around it) and `cache_roundtrip.py
fresh|cached <dir>` (step 1 with the water layer downloaded into, then
recycled from, a scratch cache; needs Overpass), `sim_mesh_failure.py`
(Triangle4XP fails), `sim_step3_failures.py download|convert|dsf <held>`
(one texture fails, or build_dsf raises; restore the held DDS and the
DSF .bak afterwards) and `time_convert.py <slots> <N> <scratch>`.
`Ortho4XP.cfg` uses `overpass_server_choice=DE` (KU times out).
Since 2026-11-03 the user's global `Ortho4XP.cfg` holds their own build
settings (curvature_tol 1.0, limit_tris 4, mask_zl 15, ICAO airport cover
at ZL18 over 2 km, road_level 3, apt_curv_tol 0.5 / 2 km, XP12 water,
...), so it no longer matches the baseline. For regression tests, back up
Ortho4XP.cfg, copy the baseline's saved Ortho4XP.cfg over it, run the
tests, then restore the backup. Never leave the baseline config in place.
The values before the 2026-11-03 tuning are in Ortho4XP.cfg.before-tuning.bak
(coast_curv_tol 10 had no effect: it only refines when < curvature_tol).

Test results:
- `test` @ d07031d (fix/gitattributes + fix/mask-utils-nameerrors),
  2026-11-03: DSF byte-identical, 17/17 masks identical to baseline; only
  log change is the removed duplicate step 2.5 lines. Custom extent
  (`Denmark`) checked separately at step 2.5: master builds 0 masks
  (4 worker threads die), fixed code builds 18. → on `dev` since 2026-11-03.
- `fix/osm-layer-failure` @ f955376 (issue #7), 2026-11-03: normal build
  DSF byte-identical, 17/17 masks identical, exit 0. Simulated Overpass
  failure on the water layer (`G:\Ortho4XP_tests\tools\sim_osm_failure.py`:
  closed port, water cache hidden): ERROR in log, step 1 stops, steps 2-3 not
  run, .poly/.node/.mesh untouched, CLI exit 1.
- `test` @ d35ed49 (all three fix branches), 2026-11-03: DSF
  byte-identical, 17/17 masks identical, app log identical, exit 0;
  simulated OSM failure stops step 1 with exit 1.
  → `dev` fast-forwarded to d35ed49 on 2026-11-03.
- `fix/subprocess-links` @ f968a8c (issue #4), 2026-11-03: tested on
  scratch folders only (never in X-Plane): plain, "&", "^ ()" and
  "%OS%" paths (old MKLINK broke "%OS%" silently, exit 0), existing
  link, missing parent, overlay toggle. GUI tile click and the
  macOS/Linux os.symlink branch not run.
- `test` @ 1fca344 (+ docs/claude-md, subprocess-links), 2026-11-03:
  DSF byte-identical, 17/17 masks identical, app log identical, exit 0.
  → `dev` fast-forwarded to 9cf55ef (with this note) on 2026-11-03.
- `fix/install-windows` @ 8996e6d (#10): dry run in a scratch copy
  (`pip --dry-run`): picks Python 3.13; missing wheel / wrong Python stop
  with FAILED. Real install not run.
- `fix/debug-print` @ 4080812 (#8): build byte-identical, 216 stray
  number lines gone from the console.
- `fix/bare-excepts-tile-utils` @ 4cd0930 (#3): 10 sites; helper
  `remove_if_exists()` unit-tested with locked files; build identical.
  Cleanup deletions only run at cleaning_level > 1 (not in a build).
- `fix/bare-excepts-imagery-utils` @ d426784 (#3): 34 sites; config
  dicts identical to master, 13 broken config files give identical
  results to master; build identical, also with one DDS forced through
  convert_texture() (DDS identical).
- `test` @ 2c11379 (+ the four branches above), 2026-11-03: DSF
  byte-identical, 17/17 masks, app log identical, exit 0, console 171
  lines; OSM failure simulation still stops with exit 1.
  Merge note: install_windows.bat conflicted (line endings only,
  renormalized on `test` by fix/gitattributes); took the fix branch.
  → `dev` fast-forwarded to 520c57b (with these notes) on 2026-11-03.
- `fix/bare-excepts-vector-map` @ 554ea16 (#3, 13 sites + #14): a
  water geometry failure now stops step 1 (sim: master built a tile
  without water, exit 0). Synthetic broken patches give identical
  .poly/.node with master. keep_obj8 crash fixed. Build identical.
- `fix/bare-excepts-mesh-utils` @ 5404c25 (#3, 12 sites): broken
  inputs raise only the caught types; build_mesh with a corrupt .apt
  warns and completes; build identical.
- `fix/bare-excepts-airport-utils` @ 58f35a2 (#3, 12 sites): step 1 on
  real OSM data and on a copy with bad widths, smoothing_pix and
  removed names gives identical .poly/.node/.apt with master; build
  identical.
- `test` @ 103b02c (+ the three branches above), 2026-11-03: DSF
  byte-identical, 17/17 masks, app log identical, exit 0; both failure
  simulations (OSM download, water geometry) stop step 1 with exit 1.
  → `dev` fast-forwarded to 0b139d6 (with these notes) on 2026-11-03.
- `fix/bare-excepts-osm-utils` @ ed1769f (#3, 8; from dev): crafted OSM
  data (relation to a missing way, one-point way) same as master; a
  one-point way raises shapely GEOSException (not a ValueError).
- `fix/bare-excepts-mask-utils` @ a203e3d (#3, 6; from dev): an
  undeletable old mask now warns, 17 masks still built.
- `fix/bare-excepts-dem-utils` @ 55a3575 (#3, 7): 10 DEM files (real,
  missing, broken .hgt/.raw/.tif) give identical grids with master.
- `fix/bare-excepts-dsf-utils` @ dc014f6 (#3, 3): Global Scenery copy
  failure reports its cause, tmp stays clean.
  (Each: full build byte-identical.)
- `test` @ ed2edc8 (+ the four branches above), 2026-11-03: DSF
  byte-identical, 17/17 masks, app log identical, exit 0; both failure
  simulations stop step 1 with exit 1.
  Branch base rule since then: a fix for a module already changed on
  `dev` branches from `dev`, otherwise from `master` (avoids conflicts).
  → `dev` fast-forwarded to 9774e17 (with these notes) on 2026-11-03.
- `fix/mask-errors-stop-build` @ b66a59b (#16), `fix/dsf-raster-tmp-errors`
  @ a7448fe (#15), `fix/batch-skip-failed-tiles` @ 9da5892 (#7 follow-up),
  all from dev, each with its own sims and a byte-identical build.
- `test` @ 26a89c4 (+ the three above), 2026-11-03: DSF byte-identical,
  17/17 masks, app log identical; CLI sims: OSM and water geometry stop
  in step 1, mask/DEM failure stops in step 2.5, all exit 1; batch sims:
  an error on tile 2 of 3 is skipped ("built 2, failed 1"), Stop during
  tile 2 ends the batch.
  → `dev` fast-forwarded to ff86062 (with these notes) on 2026-11-03.
- `fix/bare-excepts-config-utils` @ c820a6d (15), `fix/bare-excepts-gui-utils`
  @ 214745d (30, from dev), `fix/bare-excepts-small-modules` @ 043ce7e (9),
  `fix/cli-read-tile-config` @ ed16185 (#17, from dev). Config: broken
  global/tile configs give the same values as master; GUI: scripted run
  same as dev's module; overlay extraction identical to master.
- `test` @ 53c6742 (+ the four above), 2026-11-03: 4-arg and 2-arg CLI
  builds byte-identical, all five sims as designed, gui_smoke 7/7 ok.
  → `dev` fast-forwarded to 9a2662d (with these notes) on 2026-11-03.
- `fix/overlay-tmp-cleanup` @ f6e9ec8 (#18), `fix/validate-max-threads` @
  c456e36 (#13), `fix/remove-swp-file` @ 32b3217 (#12), `fix/geotag-script`
  @ ca530f3 (#11), `fix/osm-cache-order` @ 6070f6e (#9).
- `test` @ 2571102 (+ the five above), 2026-11-03: builds byte-identical,
  all sims and gui_smoke as before, providers unchanged, and
  cache_roundtrip: fresh download and recycled cache now give identical
  .poly/.node.
  → `dev` fast-forwarded to 7693fb0 (with these notes) on 2026-11-03.
- `fix/pyflakes-cleanup` @ fc5914a (#6): pyflakes reports 0 findings;
  config still applied via exec; builds byte-identical; gui_smoke 7/7.
- `test` @ df760d1 (+ #6), 2026-11-03: build byte-identical, all five
  sims as designed. All issues in this file are now fixed.
  → `dev` fast-forwarded to cc6e1b1 (with these notes) on 2026-11-03.
- Code review 2026-11-03: `fix/pipeline-step-results` @ 63d6ce7 (#19),
  `fix/step3-integrity` @ f6d4b8b (#20), `fix/small-robustness` @ 7e49496
  (#21, #22). `test` @ 5650123: builds byte-identical, all 8 failure sims
  exit 1 (incl. sim_mesh_failure and sim_step3_failures download/convert/
  dsf), batch sims and gui_smoke as before.
X-Plane 12 is at `E:\X-Plane 12`. `Ortho4XP.cfg` sets `custom_overlay_src` to
its Global Scenery (read only: DSF rasters are copied to `tmp\`) and
`custom_scenery_dir` to its `Custom Scenery`. The latter is only used by the
GUI map's link toggle (`add_symlink`/`remove_symlink`/`add_overlay_symlink`),
which would write there — never trigger those. `Custom Scenery` already holds
the user's own `zOrtho4XP_+55+012 - Shortcut.lnk` (older tile, not ours).

## Known issues (found at commit 3cff870)

Items 1–6 come from static analysis, 7–9 from the baseline builds.
**FIXED** items are on `dev` (test results above); the rest are open.

1. **FIXED** (`aeb4200`; worse than described: all mask worker threads died
   and 0 masks were written, silently).
   **`src/O4_Mask_Utils.py:175` — NameError.** Inside the nested
   `build_mask()`, the custom-extent array is created as `custom_array`
   (line ~161) but used as `custom_mask`. Any build with
   `masks_custom_extent` set crashes at this point once the tile has water/DEM
   content. Fix: use `custom_array`.
2. **FIXED** (`fa7510c`, block removed). **`src/O4_Mask_Utils.py:426` —
   dead/broken code.** `record_water_tris()`
   uses `dest_dir`, which is not defined in that function. The `NameError` is
   swallowed by a bare `except: pass`, so the "Deleting existing masks" step
   silently does nothing. `delete_old_masks_in_tile(tile, dest_dir)` exists
   separately. Decide: remove the block, or pass `dest_dir` in. Check which
   caller is responsible for deleting old masks before changing it.
3. **FIXED** — no bare `except:` left in live code (only 2 in
   commented-out code in Mask and Vector_Map). Pattern: ignore only the
   expected error (e.g. FileNotFoundError), report other OSErrors, let
   coding errors raise; `except Exception` only at trust boundaries
   (eval of config, user code, downloaded data) with a comment.
   **166 bare `except:` clauses** in live code. They also catch
   `KeyboardInterrupt`/`SystemExit` and hide coding errors (see #2). Do NOT
   mass-replace: some are used as control flow ("file missing → continue").
   Narrow them module by module, to the specific exceptions
   (`OSError`, `ValueError`, `KeyError`, `requests` exceptions, ...), and log
   what was caught.
4. **FIXED** (`f968a8c` GUI links, `ca530f3` O4_Geotag.py).
   **Shell commands built from strings:**
   `src/O4_GUI_Utils.py` ~lines 1618–1721 create links with
   `os.system('MKLINK /J "..." "..."')` (Windows) / `ln -s` (other), and
   `src/O4_Geotag.py` uses `os.system`. They break on paths containing quotes
   or special characters and never check the result. Replace with
   `subprocess.run([...], check=True)` (list arguments, no shell); for
   junctions, `subprocess.run(["cmd", "/c", "mklink", "/J", link, target],
   check=True)` or `_winapi.CreateJunction`.
5. **FIXED** (`20dbfe3`). **No `.gitattributes`.** Add `* text=auto eol=lf` for source files and
   keep `*.bat` as `eol=crlf`, to avoid whole-file CRLF diffs.
6. **FIXED** (`fc5914a`). pyflakes is installed in the venv
   (`venv\Scripts\python.exe -m pyflakes Ortho4XP.py src/O4_*.py` must
   stay at 0 findings). The IMG/OSM/OVL/TILE/UI imports in
   O4_Config_Utils are exec() targets (see `_EXEC_TARGETS`), not unused.
   Minor (pyflakes): 10 unused imports, 9 unused local variables, 3 f-strings
   without placeholders, 1 unused `global extents_dict`.
7. **FIXED** (`ac12969`, `d48aaa0`, `f955376`: build stops with ERROR, CLI
   exits 1, real exception shown). Follow-up FIXED (`9da5892`): a batch
   build skips a failed tile, continues and logs a summary; only the
   Stop button (UI.stop_requested) ends the batch.
   **Failed OSM query silently drops a whole vector layer** (confirmed by the
   first baseline build, 2026-11-02). In `O4_OSM_Utils.OSM_queries_to_OSM_layer`
   one query that fails all `max_osm_tentatives` returns 0 for the whole
   layer; `O4_Vector_Map.include_water()` (and the other `include_*`) return 0,
   and `build_poly_file()` ignores that. The build ends "normally" with no
   inland water and nothing cached. Batch builds need this to fail loudly
   (or retry) instead. Related: `get_overpass_data()` logs every exception
   as "server was too busy" without the actual error, and gives up after 8
   tries with waits up to 256 s (step 1 took 51 min).
8. **FIXED** (`fa7510c` doubled lines, `4080812` debug print).
   Log oddities seen in the baseline: step 2.5 prints "-> Deleting existing
   masks" / "-> Reading mesh data" twice (check against #2), and step 3
   prints a bare number (`11184952`) twice — a leftover debug print.
   (The doubled step 2.5 lines are FIXED by `fa7510c`; the debug print is
   open.)
9. **FIXED** (`6070f6e`): write_to_file() wrote ways/relations in set
   order, so a re-read cache got other ids than the download. Cache files
   written before the fix keep their old order (the baseline relies on
   them); re-downloaded caches now match fresh downloads.
   **Freshly downloaded and recycled OSM data give different meshes.** Same
   code (master 3cff870), same config: building from a fresh Overpass
   download of the water layer gave 984,186 triangles; recycling the cached
   `+55+012_water.osm.bz2` gave 984,150 (18 fewer vertices, 1 mask and the
   DSF differ). Likely the cache write/read round trip (`write_to_file` /
   `update_dicosm`) changes element order or drops data. Not yet analysed.
   Consequence: compare test builds only against a baseline built from the
   *same cached* OSM files.
10. **FIXED** (`8996e6d`, also selects Python 3.13 and stops on errors).
    **`install_windows.bat:13`** installs `gdal-3.11.1-cp313…whl`, but only
    `gdal-3.12.2` is bundled in `Utils/win/`, so the script fails there.
11. **FIXED** (`ca530f3`, GDAL API instead of os.system).
    **`src/O4_Geotag.py:5`** calls `Transformer.transform("epsg:4326",
    "epsg:3857")`; should be `Transformer.from_crs(...)`. Standalone script,
    not imported by the app, crashes when run. Also uses `os.system` (#4).
12. **FIXED** (`32b3217`). `Providers/Sweden/.SE.lay.swp` is a stray vim swap file committed
    upstream.
14. **FIXED** (`554ea16`): `keep_obj8()` returned an unassigned
    variable when an OBJ8 patch had no usable TRIS, crashing step 1
    (also on master).
15. **FIXED** (`a7448fe`, also checks the 7z exit code).
    `O4_DSF_Utils.extract_elevation_and_bathymetry_data`: the
    `os.replace(tmp_file, tmp_file + ".7z")` has no try; a locked
    tmp/+LL+LLL.dsf crashes step 3 (also on master).
16. **FIXED** (`b66a59b`). `build_masks()` returns early on errors (bad DEM, missing mesh)
    without raising `UI.red_flag`, so the CLI still runs step 3.
17. **FIXED** (`ed16185`): `Ortho4XP.py lat lon` never read the tile
    config, built with an empty provider (exit 0) and saved that into
    the tile config; it now reads the tile config or exits 1.
18. **FIXED** (`f6e9ec8`). `build_overlay()` removed only the elevation and sea_level rasters
    from tmp; the 9 other XP12 rasters (seasons, soundscape) stay
    (also on master).
19. **FIXED** (`63d6ce7`): CLI, build_all and batch only stopped on
    red_flag; build_mesh returns 0 without it when Triangle4XP gives up
    (and on node file/DEM errors), so steps 2.5/3 ran on the previous
    mesh and the build "succeeded". Pipelines now also check return
    values; build_masks returns 1.
20. **FIXED** (`f6d4b8b`): step 3 activated the DSF even when textures
    failed to download (dropped silently after 3 tries) or convert, or
    when build_dsf failed in its thread (a partial or stale .tmp could
    be activated). Now the tile is only activated when complete.
21. **FIXED** (`7e49496`): overlay 7z step unchecked (like #15).
22. **FIXED** (`7e49496`): parallel_worker shared a mutable default.
13. **FIXED** (`c456e36`, also rejects 0 and negatives).
    **`max_threads` in a .lay file is not validated:** when `int()`
    fails (e.g. `max_threads=many`), the raw string stays in the
    provider dict (found by the broken-config test, same on master).

## Performance notes (measured 2026-11-03, cached +55+012, 24 cores)

- Cached build ~110 s: step 1 ~44 s (Vector_Utils insert_edge/rtree
  ~30 s), step 2 ~14 s (Triangle4XP), step 2.5 ~13 s (numpy convolve in
  blur_mask), step 3 ~28-38 s (build_dsf, single-threaded).
- DDS conversion runs in parallel with build_dsf and finishes inside it:
  96 conversions took the same step 3 time with 4, 12 or 20 convert
  slots. Keep max_convert_slots=4.
- max_download_slots=1 already means 16 parallel requests per texture
  (provider max_threads); fresh tiles are bound by Overpass and imagery
  download times, not CPU.
- Ideas not done (need a new baseline or larger changes): one Overpass
  request per layer instead of per query (fewer slow requests in step 1,
  but changes element order); running several CLI processes in parallel
  for different tiles of a batch (separate globals; needs a real
  multi-tile test); algorithmic work in insert_edge, blur_mask,
  build_dsf.

## Planned order of work

1. ~~Check the environment~~ — done 2026-11-02 (Python 3.13.17 venv,
   bundled wheels, tools run, git identity set locally).
2. ~~Build the baseline tile from `master`~~ — done (`_cached` baseline).
3. ~~`fix/gitattributes` (#5)~~ — on `dev`.
4. ~~`fix/mask-utils-nameerrors` (#1, #2)~~ — on `dev`, tested with
   `masks_custom_extent` off and on.
4b. ~~`fix/osm-layer-failure` (#7)~~ — on `dev`.
5. ~~`fix/subprocess-links` (#4)~~ — merged to `test` @ 1fca344.
5b. ~~#10, #8~~ — on `test`.
6. Bare excepts (#3), one module per branch, starting with the modules on the
   batch-build path (`O4_Tile_Utils`, `O4_Imagery_Utils`, `O4_Mask_Utils`).

## Coding style

- PEP 8, with comments explaining *why*, not *what*.
- Keep changes minimal and behaviour-preserving unless the change is the fix.
- Prefer `os.path`/`pathlib` over string path concatenation.
- Use the project's own `UI.vprint` / `UI.lvprint` for messages, not `print`.
