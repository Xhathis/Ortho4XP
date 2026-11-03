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
custom extent / alternative module dir) and `sim_osm_failure.py` (CLI
build with a simulated Overpass failure on the water layer).
`Ortho4XP.cfg` uses `overpass_server_choice=DE` (KU times out).

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
3. **166 bare `except:` clauses** in live code. They also catch
   `KeyboardInterrupt`/`SystemExit` and hide coding errors (see #2). Do NOT
   mass-replace: some are used as control flow ("file missing → continue").
   Narrow them module by module, to the specific exceptions
   (`OSError`, `ValueError`, `KeyError`, `requests` exceptions, ...), and log
   what was caught.
4. **FIXED** for the GUI links (`f968a8c`, `make_dir_link()`);
   `O4_Geotag.py` still open (see #11).
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
6. Minor (pyflakes): 10 unused imports, 9 unused local variables, 3 f-strings
   without placeholders, 1 unused `global extents_dict`.
7. **FIXED** (`ac12969`, `d48aaa0`, `f955376`: build stops with ERROR, CLI
   exits 1, real exception shown). Open follow-up: a failed tile now stops
   a whole batch; skipping just that tile would suit long batches better.
   **Failed OSM query silently drops a whole vector layer** (confirmed by the
   first baseline build, 2026-11-02). In `O4_OSM_Utils.OSM_queries_to_OSM_layer`
   one query that fails all `max_osm_tentatives` returns 0 for the whole
   layer; `O4_Vector_Map.include_water()` (and the other `include_*`) return 0,
   and `build_poly_file()` ignores that. The build ends "normally" with no
   inland water and nothing cached. Batch builds need this to fail loudly
   (or retry) instead. Related: `get_overpass_data()` logs every exception
   as "server was too busy" without the actual error, and gives up after 8
   tries with waits up to 256 s (step 1 took 51 min).
8. Log oddities seen in the baseline: step 2.5 prints "-> Deleting existing
   masks" / "-> Reading mesh data" twice (check against #2), and step 3
   prints a bare number (`11184952`) twice — a leftover debug print.
   (The doubled step 2.5 lines are FIXED by `fa7510c`; the debug print is
   open.)
9. **Freshly downloaded and recycled OSM data give different meshes.** Same
   code (master 3cff870), same config: building from a fresh Overpass
   download of the water layer gave 984,186 triangles; recycling the cached
   `+55+012_water.osm.bz2` gave 984,150 (18 fewer vertices, 1 mask and the
   DSF differ). Likely the cache write/read round trip (`write_to_file` /
   `update_dicosm`) changes element order or drops data. Not yet analysed.
   Consequence: compare test builds only against a baseline built from the
   *same cached* OSM files.
10. **`install_windows.bat:13`** installs `gdal-3.11.1-cp313…whl`, but only
    `gdal-3.12.2` is bundled in `Utils/win/`, so the script fails there.
11. **`src/O4_Geotag.py:5`** calls `Transformer.transform("epsg:4326",
    "epsg:3857")`; should be `Transformer.from_crs(...)`. Standalone script,
    not imported by the app, crashes when run. Also uses `os.system` (#4).
12. `Providers/Sweden/.SE.lay.swp` is a stray vim swap file committed
    upstream.

## Planned order of work

1. ~~Check the environment~~ — done 2026-11-02 (Python 3.13.17 venv,
   bundled wheels, tools run, git identity set locally).
2. ~~Build the baseline tile from `master`~~ — done (`_cached` baseline).
3. ~~`fix/gitattributes` (#5)~~ — on `dev`.
4. ~~`fix/mask-utils-nameerrors` (#1, #2)~~ — on `dev`, tested with
   `masks_custom_extent` off and on.
4b. ~~`fix/osm-layer-failure` (#7)~~ — on `dev`.
5. ~~`fix/subprocess-links` (#4)~~ — merged to `test` @ 1fca344.
6. Bare excepts (#3), one module per branch, starting with the modules on the
   batch-build path (`O4_Tile_Utils`, `O4_Imagery_Utils`, `O4_Mask_Utils`).

## Coding style

- PEP 8, with comments explaining *why*, not *what*.
- Keep changes minimal and behaviour-preserving unless the change is the fix.
- Prefer `os.path`/`pathlib` over string path concatenation.
- Use the project's own `UI.vprint` / `UI.lvprint` for messages, not `print`.
