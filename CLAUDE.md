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
- Unit tests (pytest, `tests/`) cover pure functions only; builds are
  checked with the regression worktree (see Testing method).

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
- `docs/claude-md` — this file; merged into `test` like a fix branch.
- Once a fix branch is on `dev` and pushed, delete it (local and
  origin) and remove its worktree; the `--no-ff` merge commit keeps
  its name and history. The 46 merged fix branches up to #37 were
  deleted on 2026-11-05 (the commit SHAs in this file still resolve).
  Only `master`, `dev`, `test`, `docs/claude-md` and open fix branches
  should exist.
- One logical change per commit so a regression can be bisected.
- Mark commits that touch Windows-only branches (`sys.platform` / `os.name`)
  or the bundled `.exe` tools in the message.
- Commit or push only when the user asks.

## Testing method

Unit tests: `venv\Scripts\python.exe -m pytest` (repo root, ~14 s, 279
tests; pytest 9.2.0 from requirements-dev.txt, installed in the venv
2026-11-04). They cover O4_Geo_Utils, O4_File_Names, tile config
read/write, the helpers of #23/#28/#32 and the Viewfinder downloads of
#38 (fake server, in-memory zips) and the fixes from #45 on. tests/conftest.py switches
to an empty temp folder in pytest_collection, before any O4 module is
imported (FNAMES paths and CFG's Ortho4XP.cfg come from the cwd), so
they never touch the user's data. Run them before every commit; add a
test before changing a pure function. Everything else (builds) is
checked against a **baseline**:

1. The baseline is the reference tile built from frozen inputs (OSM,
   DEM, Global Scenery DSF, config), all kept inside the baseline folder.
2. Build the same tile from the commit under test in the isolated
   regression worktree (below), never in `G:\Ortho4XP`.
3. Compare: masks and DSF by hash, then `--dsf2text` diff, then the app
   log. Explain every difference — an unexplained difference is a
   failure, even if the tile "looks fine".
4. Run the unit tests (above); add `pytest` tests for a pure function
   before refactoring it.

Reference tile: `+55+012` (lat 55, lon 12 — Zealand / Copenhagen, Denmark).
Provider `Arc` (Esri World Imagery, `Providers/Global/Arc.lay`), ZL 17.
Baseline (since the Triangle4XP stack fix #32, 2026-11-04):
`G:\Ortho4XP_baseline\+55+012_Arc_ZL17_test-702e768_frozen\` — `inputs\`
(4 OSM layers of the old baseline, DEM N54-N56 E011-E013 = the user's
library .hgt files, X-Plane 12 Global Scenery +55+012.dsf, the old
baseline's Ortho4XP.cfg), `expected\` (DSF, dsf2text, 17 masks, logs),
`SHA256SUMS`, `BASELINE.txt`. Mesh 1,094,388 triangles at min_angle 10,
no WARNING. Same inputs, previous baseline
`+55+012_Arc_ZL17_dev-c85e958_frozen` (before #32: Triangle4XP crashed
and fell back to min_angle 2, 869,192 triangles; master 3cff870 gives
that one byte for byte).
Run a regression (any cwd, venv Python):
`venv\Scripts\python.exe G:\Ortho4XP_tests\tools\regression.py run <commit> [--label name]`
(~2 min; exit 0 = PASS). It checks the commit out in the git worktree
`G:\Ortho4XP_tests\regression\ws` (detached HEAD), resets that
worktree's data folders from `inputs\` and runs `Ortho4XP.py 55 12 Arc
17` there: Ortho4XP takes all data folders and Ortho4XP.cfg from its
cwd, so the user's folders, config, log and tiles are never touched,
and no neighbour meshes exist (masks are deterministic, #28).
custom_overlay_src points at the frozen Global Scenery copy, Custom
Scenery is empty. Only imagery (Orthophotos, textures) persists in the
worktree; it is not in the DSF or masks. After the build every input
is re-hashed: an added or changed file (a download) fails the run.
Results: `G:\Ortho4XP_tests\+55+012_Arc_ZL17_<label>-<sha>\` (console.log,
DSF, masks, app_log.diff, dsf.diff if needed). The order of "Created
…png" lines in console.log varies between runs and is not a difference.
`regression.py freeze|baseline` made the baseline; a new one needs a
new folder (they refuse to overwrite). `--overlay <src_dir>` builds
`<commit>` with that folder's O4_*.py copied over it (uncommitted code
in a fix worktree), restored afterwards.
`sims_in_ws.py <commit> [--overlay <src_dir>] all` runs the 10 CLI
sims and the 5 batch sims in the same worktree (~20 min),
each after a fresh reset from the frozen inputs, and checks each
one's exit code and specific message (FAILURES: 0 = all as designed;
logs in `G:\Ortho4XP_tests\sims_<sha>\`). A texture
sim_step3_failures moves to `regression\held` is put back (a .jpg to
the worktree's Orthophotos, a .dds to the tile's textures). Single
sims: `sims_in_ws.py <commit> sim_batch.py error ; sim_batch.py stop`.
`test_batch_order.py <src_dir> <out_dir>` (#28, cwd G:\Ortho4XP for the
cached +43-067/-066/-065 data): sequential batch forward and reversed,
masks and DSFs must match; writes Masks\+40-070 and Ortho4XP.log, so
back both up around it.
Fix branches are edited in their own worktree `G:\Ortho4XP_wt\<name>`,
so the user's checkout stays on `dev` while Ortho4XP may be open.
`probe_mesh.py [--skip-step1] [key=value]` (cwd = the regression
worktree) logs every Triangle4XP run's options and exit code and
saves the mesh command to tmp\mesh_cmd.json; `pe_stack.py <exe>
[<MB> <out.exe>]` shows or sets an exe's stack reserve.
The older `master-3cff870*` baselines (not reproducible, or invalid
by #7/#9) and the old result folders were deleted on 2026-11-05;
`G:\Ortho4XP_baseline` holds only the two `_frozen` baselines.
Test builds go to `G:\Ortho4XP_tests\<tile>_<provider>_<ZL>_<branch>-<sha>\`.
Test helpers (venv Python; the sims below through sims_in_ws.py) are in
`G:\Ortho4XP_tests\tools\`: `run_masks.py` (step 2.5 only, optional
custom extent / alternative module dir), `sim_osm_failure.py` (CLI
build with a simulated Overpass failure on the water layer) and
`sim_water_geometry_failure.py` (CLI build where cleaning the inland
water geometry fails), `sim_mask_dem_failure.py` (CLI build where the
DEM for masks fails in step 2.5), `sim_batch.py error|stop` (batch
of 3, steps 1-2.5, with an error or a Stop on tile 2; since #44 the
Overpass error fails tile 2 and its retry, `error-once` only the
first try, so the retry builds it) and
`gui_smoke.py` (scripted run of the real GUI: Earth and config
windows, tile selection; no downloads, no Custom Scenery links; back
up .last_gui_params.txt around it) and `cache_roundtrip.py
fresh|cached <dir>` (step 1 with the water layer downloaded into, then
recycled from, a scratch cache; needs Overpass), `sim_mesh_failure.py`
(Triangle4XP fails), `sim_step3_failures.py download|convert|dsf <held>`
(one texture fails, or build_dsf raises; `white` / `white-once`: its
imagery comes back partly white always / only the first time, #35),
`sim_batch.py exception` (tile 2's mesh step raises, #37),
`sim_overlay.py <src_dir>` (cwd = regression worktree; build_overlay
for +55+012: normal, stale tmp, 3 DSFTool failures, missing source,
blocked destination, #34; ~30 s) and `time_convert.py <slots> <N> <scratch>`,
`sim_overpass_fallback.py [src_dir]` (get_overpass_data against two
local mock servers; no real Overpass traffic), `sim_dem_failure.py
<scratch>` (DEM() cases A-I against a scratch Elevation_data copy,
downloads blocked), `sim_dem_cli.py` (CLI build without elevation
data: step 1 must stop, exit 1), `sim_batch.py dem` (tile 2 of 3
without elevation data is skipped) and `check_ned_names.py [--head]`
(USGS NED names; --head asks USGS that the files exist),
`sim_sea_tile.py [lat lon ...]` (#41, through sims_in_ws.py; real
network: CLI on -07+072 and +15-061 must exit 0 with "Open sea",
no tile folder, only the coastline layer; not in `all`),
`sim_batch_cleaning.py seq|par` (#42, through sims_in_ws.py; batch
+55+012 and -07+072, steps 1-3 at cleaning_level 3: the mesh must
still exist when the batch's cleanup starts and be gone after it, DSF
equal to the baseline; one real Overpass request). Unit sims set
`UI.log = False`: lvprint would otherwise append to the user's log.
`sim_osm_layer_request.py <scratch>` (#26 against a mock server),
`compare_layer_request.py <scratch> [lat lon]` (real Overpass:
combined vs per-query layer download, same set of ways?),
`check_atomic_files.py <scratch>` and `test_parallel_batch.py
compare|fail|stop <out_dir>` (#27: real builds of +43-067/-066/-065,
GO2 ZL16, user's global cfg, custom build dir; ~7 min for all three
modes; writes Masks\+40-070 as usual; back up Ortho4XP.log around it;
mode `context`: no tile configs, provider only as CFG globals like the
GUI, DSFs must equal those of `par`), `check_overpass_slot.py`
(#30: 3 processes never query a mock server at once; killed slot
holder; 429 wait), `check_step3_provider.py [tile_dir]` (#31: empty,
unknown and zone providers stop build_tile at once, GO2/Arc pass; uses
an existing tile's mesh read-only and silences UI.logprint, which
build_tile calls directly).
`Ortho4XP.cfg` uses `overpass_server_choice=DE` (KU times out); since
#23 tentatives 5-8 alternate with the other servers in
overpass_servers.txt. The failure sims replace the whole server list
with one closed port, so they still fail without fallback.
Never run the full-build sims (sim_osm_failure, sim_water_geometry_failure,
sim_mask_dem_failure, sim_mesh_failure, sim_step3_failures, sim_dem_cli,
sim_batch) with cwd G:\Ortho4XP: they would build into the user's
Tiles\zOrtho4XP_+55+012, one of their 9 test tiles (+54..+56 /
+010..+012, GO2 ZL16, their settings), and use their config, caches
and log. Use sims_in_ws.py. Only test_batch_order, test_parallel_batch
and gui_smoke still run in G:\Ortho4XP (other tiles; see their notes).
Since 2026-11-03 the user's global `Ortho4XP.cfg` holds their own build
settings (curvature_tol 1.0, limit_tris 4, mask_zl 15, airport cover
at ZL18 for all airports (cover_airports_with_highres=True,
apt_smoothing_pix 8; was ICAO only, see .before-bushflying.bak), road_level 3,
apt_curv_tol 0.5 / 2 km, XP12 water, batch_parallel_tiles 3, ...;
cleaning_level 3 since 2026-11-05 14:22, see #42).
Never leave a test config in place. Ortho4XP.cfg and *.lnk are in
.gitignore (the user's own files). The values before the 2026-11-03
tuning are in Ortho4XP.cfg.before-tuning.bak
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
- `fix/overpass-fallback` @ 85aacc2 (#23): sim_overpass_fallback 8/8.
  `test` @ 1c09d30: builds byte-identical, all 8 failure sims exit 1
  (OSM sim ERROR line now ends "(last: DE: ConnectionError)"), batch
  sims and gui_smoke as before.
- `fix/dem-errors-stop-build` @ d5a9a97 (#24), `fix/ned-tile-name` @
  cffd6f4 (#25): sim_dem_failure 9/9 (dev: 4 cases built flat),
  check_ned_names 4/4 with USGS HTTP 200 (dev: e173/e179).
  `test` @ c473a68: builds byte-identical, all 9 failure sims exit 1
  (incl. sim_dem_cli), batch sims error/stop/dem as designed,
  gui_smoke 7/7, unit sims 0 failures.
- `fix/osm-layer-request` @ 6c9c6d4 (#26): sim_osm_layer_request 7/7;
  real Overpass on +55+012: same set of ways combined/per query (big
  roads 8167, water 13224), 48 s vs 317 s and 51 s vs 217 s, 1
  duplicated water way gone. `fix/parallel-batch` @ c180af9 (#27):
  check_atomic_files 6/6; test_parallel_batch compare (masks 39/39
  and 3 DSFs identical to a two-phase sequential reference, 115 s vs
  169 s), fail and stop as designed. `test` @ 72772f9: builds
  byte-identical, all sims as before, gui_smoke 7/7, unit sims 0.
- First real parallel batch (9 fresh Danish tiles, 3 workers),
  2026-11-04: 0 of 9 built (#29, #30). `fix/batch-worker-gui-state` @
  5abde83 (#29), `fix/overpass-slot` @ 249807c (#30). `test` @
  a34a069: all failure/batch sims, gui_smoke 7/7, unit sims 0;
  test_parallel_batch compare/fail/stop/context all ok; A/B on
  +55+012 (current inputs, see above): dev and test DSF, 17 masks and
  app log byte-identical.
- Second run of the 9 tiles: steps 1-2.5 fine (#30 works), step 3
  failed on all: their tile configs still had default_website= empty
  from the first run (tile config wins over the GUI). Set to GO2 by
  hand. `fix/step3-provider-check` @ 4326c43 (#31): check 6/6 (dev
  fails the empty/unknown cases). `test` @ ac1acff: all sims, gui_smoke
  7/7, unit sims 0; A/B dev/test DSF, masks, app log identical.
- Third run (step 3 only, 9 tiles, 3 parallel), 2026-11-04: 9 built,
  0 failed, 1h27m, download-bound (~12 textures/min per worker).
- Frozen baseline `+55+012_Arc_ZL17_dev-c85e958_frozen`, 2026-11-04:
  built in 923 s (Arc imagery downloaded once into the worktree);
  `regression.py run` of c85e958 again (107 s) and of master 3cff870
  (83 s): DSF byte-identical, 17/17 masks, app log identical, inputs
  unchanged. So every fix on dev leaves a normal build unchanged.
- `fix/sequential-batch-phases` @ aac178a (#28): test_batch_order on dev
  fails (forward 38 / reverse 37 masks, 2 of 3 DSFs differ), on the fix
  39/39 masks and 3 DSFs identical (132 s per order); _batch_phases
  equals the old parallel phase list for all 64 flag combinations;
  sim_batch error/stop/dem in the worktree as designed (a duplicated
  tile that fails is dropped from phase 2 entirely: sim artefact, GUI
  lists are unique); regression --overlay PASS (DSF, 17/17 masks, log).
- Sims moved into the regression worktree, 2026-11-04: `sims_in_ws.py
  57305b7 all`: 11/11 as designed (8 CLI sims exit 1 with their own
  message, 3 batch sims), user's Ortho4XP.log and tiles untouched.
- `fix/triangle4xp-stack` @ 31392f5 (#32): probe_mesh.py showed exit
  0xC00000FD at min_angle 10/8/6/4 (regression and user settings);
  stack 3-6 MB still overflows, 8 MB and up pass with identical
  meshes (regression cfg 1,094,388 tris, user cfg 1,813,974 vs
  1,548,040 at min_angle 2). Old and patched exe at min_angle 2:
  identical .node/.ele/.poly except the "Generated by" path comment.
  Regression vs dev-c85e958_frozen: FAIL as expected (no WARNING,
  1,094,388 tris; DSF differs; all 17 masks differ in <= 0.27% of
  pixels, same water coverage; app log identical); sims 11/11.
  `test` @ 702e768: new baseline `test-702e768_frozen` (82 s, DSF
  38,698,543 bytes, same as the 31392f5 build), repeat run PASS.
- `fix/pytest-pure-functions` @ 94efcec (#33 + unit tests): 135 tests
  pass; the same tests on master 3cff870: 58 pass (geo, file names,
  config reading unchanged by this fork), 77 fail only for code added
  here (helpers, atomic temp files) and #33. `test` @ e887b72:
  regression PASS (DSF, 17/17 masks, app log).
- Readiness review 2026-11-05: `fix/overlay-step-checks` @ 57a63b3
  (#34; sim_overlay 7/7, overlay DSF byte-identical to dev's),
  `fix/white-squares-fail-tile` @ d75c421 (#35), `fix/log-console-
  warnings` @ 0f53681 (#36), `fix/batch-catch-tile-errors` @ d54ed55
  (#37; dev: sim_batch exception ends the batch at tile 2, exit 1).
  `test` @ e6ba425 (one conflict in _build_one_tile, both kept):
  regression PASS (DSF, 17/17 masks, app log identical), sims_in_ws
  all 14/14, sim_overlay 7/7, 135 unit tests, pyflakes 0. Not run:
  gui_smoke and test_parallel_batch (they use G:\Ortho4XP).
- `fix/viewfinder-best-resolution` @ 6446e0c (#38): 23 new unit tests
  (zone name identical to the old code for all 64,800 tiles; fake
  server: 1"-only, both, 3"-only, upgrade, outage, archive without the
  tile, Wellington); real download of dem1/P22 into a scratch folder:
  N61W050 3601 x 3601 in 2 s; dem1/E36 404, dem3/E36 200;
  sim_dem_failure 9/9. `test` @ f6d21c2: regression PASS (DSF, 17/17
  masks, app log identical, nothing downloaded), sims_in_ws all
  14/14, sim_overlay 7/7, 158 unit tests, pyflakes 0.
- Greenland batch on `dev` 085280b (17 tiles +59..+61 / -043..-050,
  3 parallel, steps 1-3 + overlays), 2026-11-05: 17 built, 0 failed,
  1h50m; +61-050 got dem1/P22, 17 overlay DSFs. The one WARNING
  (holes filled with zero) is +61-050's NW margin corner: neighbour
  N62W051 is 17% void, see #39.
- `fix/dem-hole-warning` @ aaa9bdd (#39): 6 new unit tests (164
  pass), real +61-050 read gives one INFO naming the tile with the
  same altitudes. `test` @ d2bbee9: regression PASS (DSF, 17/17
  masks, app log identical), sim_dem_failure 9/9, sim_dem_cli and
  sim_batch dem as designed, pyflakes 0, gui_smoke 7/7,
  test_parallel_batch compare/fail/stop/context all ok (compare now
  122 mask files: ZL16 airport masks from cover_airports_with_highres
  for all airports; the 83 extra files were removed afterwards).
  `sim_dem_cli.py` needs the tile arguments when run on its own
  (without them Ortho4XP.py opens the GUI and the sim hangs), also
  through sims_in_ws.py: `sim_dem_cli.py 55 12 Arc 17`.
- First island batch (1182 tiles, St Helena, Ascension, Maldives,
  Lesser Antilles, ...), 2026-11-05: +15-061 failed in step 1 (#40);
  the user stopped the batch at 17:02 after 36 tiles of phase 1.
  `fix/viewfinder-no-land` @ 2b01a2a (#40): 6 new unit tests (169
  pass); real Viewfinder in a scratch folder: +15-061 and N16W061
  recorded as sea, +15-061 flat, second read 0.2 s without download,
  +15-062 (Dominica) max 1420 m. `test` @ a88ad77: regression PASS
  (DSF, 17/17 masks, app log identical), sim_dem_failure 9/9,
  sim_dem_cli exit 1 with the Elevation data ERROR, sim_batch dem as
  designed, pyflakes 0.
- In that batch 6 of the 35 tiles that reached step 1 were open sea
  (empty coastline layer: -09-015, -07+072, -01+072, +01+072,
  +12-061, +12-060; 5-29 min each in step 1). `fix/skip-sea-tiles` @
  f16b079 + f4504d2 (#41): 20 new unit tests (189 pass);
  sim_sea_tile -07+072 and +15-061 (real network): exit 0, ~34 s
  each, no tile folder, only the coastline layer downloaded;
  regression PASS, sims_in_ws all 14/14. `test` @ 1379f70:
  regression PASS (DSF, 17/17 masks, app log identical), pyflakes 0.
  Not run: gui_smoke, test_parallel_batch (the parallel parent's
  exit code 3 path is unit-tested with fake workers). The 6 sea
  tiles above still have their step 1-2 folders in Tiles (the user
  deletes them).
- Readiness check 2026-11-05 evening: caches clean (no temp, empty or
  broken files; the 181 OSM files of the island batch decompress
  fully). The user switched to cleaning_level 3 at 14:22, which broke
  #28 in batches (#42). `fix/batch-mesh-cleanup` @ 9542d07 (#42): 13
  new unit tests (202 pass); sim_batch_cleaning seq and par (real
  workers): mesh kept until the batch's cleanup, then mesh and .apt
  gone, DSF byte-identical to the baseline, -07+072 skipped as open
  sea in a real batch; regression PASS, sims_in_ws all 14/14.
  `test` @ 891c932: regression PASS (DSF, 17/17 masks, app log
  identical), pyflakes 0. Not run: gui_smoke, test_parallel_batch.
- Iceland batch on `dev` bd49dd9 (40 tiles +63..+66 / -025..-014, 3
  parallel, steps 1-3 + overlays, fresh caches), 2026-11-05/06: 40
  built, 0 failed, 7h34m, no WARNING; meshes removed after the batch
  (#42). The next batch (185 tiles, Denmark/Poland, 2026-11-06) lost
  +54+015 in step 1 to #43 and was then abandoned by the user.
  `fix/worker-output-encoding` @ 24bec0c (#43): 7 new unit tests (209
  pass; a real child process with the old environment exits 1 on
  "ł", with _worker_env writes it intact); regression PASS (DSF,
  17/17 masks, app log identical); sim_batch_cleaning par (real
  workers) and sim_batch error as designed. `test` @ 2142c51 (same
  tree as 24bec0c on dev): 209 unit tests, pyflakes 0.
- 66-tile batch on `dev` 30f01d1 (Iceland, 2026-11-06): 21 tiles
  lost step 1 to an Overpass outage (11:23-14:47; DE's IPv4
  65.109.112.52 timed out, the shown error was the IPv6 WinError
  10051); the user's next 66-tile batch (15:43, 10h06m): 57 built,
  9 failed the same way (16:23-18:03). `fix/overpass-batch-retry` @
  fd127ab (#44): 16 new unit tests (225 pass); a real request with
  no IPv6 route goes out over IPv4 only; regression PASS (DSF, 17/17
  masks, app log identical); sims_in_ws all 14: sim_batch error
  "failed" only because the retry now builds tile 2 (12 min with the
  600 s wait) -> sim changed (error fails both tries, new
  error-once), both as designed, the other 13 as before. `test` @
  65d99b8: 225 unit tests, pyflakes 0.
- Iceland rerun on `dev` e2fdc9f (the 9 tiles, 2026-11-07): 9
  built, 0 failed, 1h12m, no WARNING; the 14 meshes kept next to
  them stayed (#45). `fix/kept-mesh-cleanup` @ 81c7e6b (#45): 7 new
  unit tests (5 fail on dev). `fix/overpass-retry-probe` @ e9e40c5
  (#46): 8 new unit tests; one real check: DE answered (44 s).
  sim_batch now stubs OSM.overpass_answers. `test` @ 35a0e4d: 240
  unit tests, pyflakes 0, regression PASS (DSF, 17/17 masks, app log
  identical), sims_in_ws all 15/15 (with error-once), sim_batch_
  cleaning seq/par as designed; then on dev in G:\Ortho4XP:
  gui_smoke 7/7 (66 tiles on the map), test_parallel_batch compare
  (83/83 masks, 3 DSFs identical; seq 1087 s with all downloads,
  par 140 s), context, fail, stop all ok. The Nova Scotia OSM, DEM
  and GO2 imagery were downloaded again for it and stay cached;
  Masks\+40-070 was removed and Ortho4XP.log restored afterwards.
- Nova Scotia batch on `dev` 74e0c12 (24 tiles, 2026-11-07): 24
  built, no ERROR or WARNING, no mesh left. Then a full code review:
  #47-#56, each `fix/<name>` from dev 74e0c12 with unit tests (39 new;
  where testable they fail on dev). `test` @ abc9914 (one conflict in
  O4_Tile_Utils: #47 and #49 added helpers at the same place, both
  kept): 279 unit tests, pyflakes 0, regression PASS (DSF, 17/17
  masks, app log identical; it reuses its DDS files), sims_in_ws all
  15/15; sim_step3_failures convert/white/white-once ran nvcompress
  for real through the temp name, no .tmp left in textures.
  Not run: gui_smoke, test_parallel_batch (G:\Ortho4XP).
Drives (2026-11-04): G: is a 13 TB USB hard disk (repo, Tiles,
yOrtho4XP_Overlays, test folders); F: "ortho" is an NVMe SSD. The
download caches `G:\Ortho4XP\OSM_data`, `Orthophotos` and
`Elevation_data` (310 GB, the user's DEM library) are junctions to
`F:\Ortho4XP_data\<same name>` (copied with robocopy, every file
SHA-256 checked, tools\verify_copy.py). Ortho4XP only renames within a
folder, so junctions across drives are safe. Tiles and Overlays stay
real folders on G: because X-Plane's scenery_packs.ini names them by
absolute path. The originals on G: were deleted on 2026-11-05. The
user cleared Orthophotos and OSM_data around 14:19 on 2026-11-05 (the
built tiles keep their DDS); since then OSM_data holds only the
island batch's tiles, so the cached +43-065/-066/-067 Nova Scotia data
for test_batch_order and test_parallel_batch is gone: their next run
downloads it from Overpass again (Masks\+40-070 still exists). Never delete a junction with a recursive delete
(it would empty the F: folder): remove only the link (`rmdir`).
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
23. **FIXED** (`85aacc2`): with a fixed overpass_server_choice all 8
    tentatives went to the same server, and the 60 s read timeout was
    shorter than Overpass's 180 s query default; a batch lost tile
    +43-066 (residential roads, ~15 min). Now fallback to the other
    servers from tentative 5, read timeout 190 s, and the ERROR line
    names the last failure.
24. **FIXED** (`d5a9a97`): a missing, unreadable or wrongly sized DEM
    for the tile itself was replaced with zero altitude and only
    logged, so a batch counted a flat tile as built (custom_dem=NED1,
    2026-11-03). Now DEM.DEMError stops step 1 (red flag) and steps
    2/2.5; a neighbour only warns (36-sample margin), ocean tiles and
    info_only reads stay as before.
25. **FIXED** (`cffd6f4`): NED tile id for eastern longitudes lost its
    latitude (`tid + "w" if lon < 0 else "e"`), e.g. western Aleutians.
26. **DONE** (`6c9c6d4`): a layer with several queries (big/small
    roads, water) goes to Overpass as one union request
    ([timeout:300], read 310 s); 4 failed tries fall back to one
    request per query. Fresh downloads lose duplicated ways (a way
    matched by two queries was stored twice), so a fresh tile can
    differ slightly from one built before; cached layers unchanged.
27. **DONE** (`6c49c86`, `15562e4`, `c180af9`): app setting
    `batch_parallel_tiles` (default 1 = sequential as before). Above 1
    the batch runs `Ortho4XP.py --batch-worker` processes (output in
    tmp\batch_<tile>.log, kept only on failure), in two phases: steps
    1-2 for all tiles, then 2.5-3. Stop kills the worker trees
    (taskkill /T). Shared Viewfinder/NED/imagery files are written to a
    temp name and os.replace'd. Recommended 2-3 (Overpass allows few
    parallel requests per IP; each tile adds its imagery downloads).
28. **FIXED** (`aac178a`): build_masks also uses the neighbour tiles'
    meshes (select_neighbor_meshes), so in a sequential batch over a
    fresh region a tile's masks depended on the order (earlier tiles
    saw no later neighbour). Sequential batches now run in the same two
    phases as parallel ones (_batch_phases: steps 1-2 for all tiles,
    then 2.5-3 and overlays). Single-tile builds still see only the
    neighbour meshes that exist at that time.
29. **FIXED** (`5abde83`): parallel batch workers built fresh tiles
    with no provider: the GUI's provider, zoomlevel and custom zones
    live only in the GUI process (CFG.default_website, default_zl,
    zone_list). The parent now hands them over in
    tmp\batch_context.json.
30. **FIXED** (`249807c`): 3 workers queried overpass-api.de at once
    (HTTP 429, then connection resets, 7 tiles lost in step 1). A lock
    on OSM_data\.overpass.lock (msvcrt.locking) lets one Overpass
    request run at a time across processes; a 429 waits >= 60 s.
31. **FIXED** (`4326c43`): build_tile ran on with an empty or unknown
    provider and reported every texture as "could not get" (hundreds
    of lines); it now stops before any work with one ERROR naming the
    provider and the tile config.
32. **FIXED** (`141cd14` exe, `31392f5` messages): the bundled
    Windows Triangle4XP.exe had a 2 MB stack and crashed with
    STATUS_STACK_OVERFLOW (exit 0xC00000FD) in quality refinement on
    detailed tiles. build_mesh blamed an "uncatched OSM error" and
    retried with min_angle 8, 6, 4, 2, 0, so such tiles were meshed
    with a lower min_angle than configured (+55+012: 2 with the
    regression and the user's settings, a Nova Scotia tile 0). Of the
    user's 9 Danish tiles only +55+012 and +56+010 were affected; the
    other 7 rebuilt to DSFs of the same size. The exe now reserves
    256 MB (needed: 6-8 MB; only SizeOfStackReserve + PE checksum
    changed, see tools\pe_stack.py); where the old exe succeeded the
    output is identical. The WARNING now gives the exit code;
    build_mesh and triangulate wait() for the tool instead of
    sleep + poll().
    Effect on quality (measured on +55+012, user settings, same input):
    NOT a clear improvement. 2 deg mesh 1,548,040 tris vs 10 deg
    1,813,974 (+17%). 82% of the triangles touch a constrained segment
    (roads, coast, water; Triangle4XP runs with -Y, so no Steiner points
    on those and no angle guarantee there): < 2 deg 5.1% (2 deg mesh)
    vs 8.0% (10 deg mesh). Open terrain was fine in both (< 2 deg
    0.001% vs 0.000%, smallest 0.9 vs 2.6 deg). So the fix makes the
    configured min_angle hold on Windows as on Linux/macOS; it does
    not remove slivers, and a lower min_angle is a valid choice for
    leaner meshes. Upstream's Triangle4XP.exe will have the same
    crash if it is ever updated from there: re-run pe_stack.py.
33. **FIXED** (`ad120a3`): Tile.write_to_config(config_file) raised
    UnboundLocalError (the .bak name was set only for the default
    path). No caller passes a path; found by the unit tests.
34. **FIXED** (`57a63b3`): build_overlay read DSFTool's returncode
    before waiting for it (always None, the check never fired) and
    did not check the text2dsf run, so a failed overlay could count
    as built; no "normal exit" log line; final copy not atomic; an
    OSError killed the thread with UI.is_working set. The overlay
    tick itself always worked: `yOrtho4XP_Overlays` was empty because
    no batch since 2026-11-03 had it ticked (the Nov 3 overlays were
    removed from the folder that evening, cause unknown).
35. **FIXED** (`38d3aeb`, `d75c421`): imagery that stayed partly white
    after the one retry was activated and counted as built; the white
    JPEG and DDS were reused by every later run (an existing DDS is
    never rebuilt), and a parallel batch's summary never mentioned
    it (incomplete_imgs lives in the worker). Now handled like a
    failed download (#20): DSF not activated, tile failed, white files
    deleted for a rerun. The retry (build_tile_retrying_white) is now
    also used by the CLI and the GUI step 3 button. Tiles built before
    this with white patches cannot be detected afterwards.
36. **FIXED** (`0f53681`): warnings that mean a tile differs from its
    settings (Triangle4XP min_angle fallback, DEM holes/no_data/EPSG,
    .apt missing, failed geotag/convert, OSM cache unwritable) went
    only to the console: in a parallel batch that is the worker's
    tmp log, deleted on success. Now also in Ortho4XP.log.
37. **FIXED** (`d54ed55`): an unexpected exception in a step ended a
    sequential batch (also every one-tile batch) without a summary,
    with UI.is_working left set (GUI refused work until restarted).
    Now only that tile fails, in the step that was running.
38. **FIXED** (`6446e0c`): Viewfinder DEM resolution came from a
    hard-coded list of 1" zones and the other resolution was never
    tried. Zone P22 (SW Greenland) exists only as dem1, so the dem3
    request gave 404: +61-050 failed in step 1 (first user batch of
    Greenland tiles, 2026-11-05; older code built it flat) and
    +60-049/+61-049 got a zero-altitude west margin (rebuild them).
    Now 1" first everywhere, then 3"; an existing 3" file is upgraded
    when a 1" archive exists; zones with a real 404 for dem1 are
    listed in Elevation_data\viewfinder_no_dem1.txt (delete it to
    check again); 1" or finer files are never re-downloaded or
    replaced, and a zone download no longer rewrites same-size files.
    Wellington Intl (-42,174) stays 3" (1" has holes). Library on
    2026-11-05: 12,633 files at 1", 613 at 3" (53 blocks, mostly
    tropics / Africa / South America; upgraded where Viewfinder has
    1" when those tiles are built), 33 custom at 0.5".
    Same day: 1,546 library .hgt files (2020, older folder rule) sat
    one 10-degree folder too far west/south for tiles on a W/S
    multiple of 10 (W050, S90, ...), so Ortho4XP never saw them
    (+61-050's 1" data was on disk in +60-060). Moved by
    `G:\Ortho4XP_tests\tools\fix_dem_folders.py` (dry run by default,
    `--apply`, `--undo`): 1,470 moved, 70 3" files replaced by the
    misfiled 1" ones, 6 identical copies parked. Replaced and
    duplicate files are in Elevation_data\_misfiled_hold (0.33 GB,
    the user deletes it), the moves in _misfiled_moves.csv; 37 old
    folders (-100..., +80-010) are empty. A rescan finds 0.
39. **FIXED** (`aaa9bdd`, log only): the "raster contain holes that
    seem to big to be filled" WARNING named neither tile nor file, and
    fill_nodata_values_with_nearest_neighbor stops after 20 rounds,
    so a fully void 36-sample margin corner (void neighbour) always
    triggered it (set to 0 m, the tile itself fine). Now it names the
    tile (or 3" file) and the sample count; holes left only in the
    COMBINED_MARGIN are a console INFO, holes in the tile stay a
    logged WARNING. Filling unchanged. Note: Viewfinder leaves the sea
    void, so coastal tiles have many voids (+48-003: 29%, all in the
    Channel, bordered by 0 m): ">= 10000 voids -> zero" is right there.
40. **FIXED** (`2b01a2a`): Viewfinder publishes no .hgt for a tile
    without land, but Utils\world_tiles.png flags some sea tiles as
    land (+15-061, open sea east of Dominica; also N16W061), so since
    #24 such a tile stopped in step 1 ("would be flat") and each
    neighbour downloaded the zone archive again. Now, when every
    archive the zone has (404 = none) came and none holds the tile,
    it is sea: zero altitude, one log line, listed in
    Elevation_data\viewfinder_no_land.txt (delete it to check again;
    a file put in place later wins). A failed request, or a zone with
    no archive at all, still stops the tile. A 1" archive without the
    tile now falls back to the 3" one.
41. **DONE** (`f16b079`): open sea tiles are skipped. A tile is open
    sea when custom_dem is empty (or Viewfinder), there is no generic
    .tif or custom coastline, the default elevation has no land
    (sea in world_tiles.png and no .hgt in the library, or #40's
    no-land record) and OSM has no coastline way in it. build_poly_file
    checks this before the airport layer (one Overpass request, cached
    as the coastline layer) and returns VMAP.SEA_ONLY (= 2, truthy):
    CLI exit 0 "Open sea, nothing to build.", build_all stops,
    batches drop the tile from phase 2 and print "Tiles built: N,
    skipped (open sea): K, failed: M." plus the list (the old line
    when K = 0), a parallel worker exits 3 (SEA_EXIT_CODE), a batch
    with only sea skips returns success. The empty build dir made for
    the run is removed; an existing tile folder is left alone. Before:
    every layer queried (all empty) and a flat-water DSF built that
    only replaced X-Plane's own ocean (imagery was already ~0: sea
    triangles get textures only under masks, i.e. near a coast).
42. **FIXED** (`9542d07`): cleaning_level > 2 deleted a tile's .mesh
    and .apt at the end of its step 3, but in a batch's phase 2 the
    neighbours' step 2.5 still reads that mesh (#28), so masks
    depended on the build order again. Batches (sequential, and the
    --batch-worker processes) set TILE.keep_mesh_after_step3 and the
    batch deletes the files after the last phase
    (_remove_meshes_after_batch): only for tiles built through step 3,
    not next to a tile that really failed (its rerun needs them; log
    line "Mesh kept ..."), not after Stop. Single builds unchanged.
    No tile was affected: the switch to level 3 came after the
    Greenland batch, and the island batch stopped in phase 1.
43. **FIXED** (`24bec0c`, Windows only): a --batch-worker's stdout
    goes to its tmp log (opened as UTF-8), but redirected output is
    encoded in cp1252 on Windows; printing a Polish airport name ("ł",
    +54+015, Denmark/Poland batch 2026-11-06) raised
    UnicodeEncodeError and failed step 1. Every name with a letter
    outside cp1252 (Polish, Czech, Baltic, ...) did; Icelandic and
    Danish letters are in cp1252. Workers now get
    PYTHONIOENCODING=utf-8:backslashreplace (_worker_env), the CLI
    escapes such characters on a redirected stdout/stderr
    (UI.safe_console_streams), and logprint escapes them instead of
    silently dropping the line (Ortho4XP.log stays in the ANSI code
    page). The GUI writes to its own window and was not affected.
44. **DONE** (`fd127ab`): an Overpass outage failed tiles for the
    whole batch: 2026-11-06 11:23-14:47 overpass-api.de (one of its
    two IPv4 addresses dead, the other failing) and KU (read timeouts)
    cost 21 of 66 tiles their step 1 after 8 tentatives each. Now a
    tile whose step 1 stopped for want of an Overpass answer
    (OSM.overpass_gave_up, reset before each batch step 1; parallel
    worker exit code 4 = OVERPASS_EXIT_CODE) is put aside and built
    once more at the end of the phase, at least overpass_retry_wait
    (600 s) after the last such failure; failing again is final,
    Stop works while waiting, other step 1 errors are not retried.
    Also: without an IPv6 route (this PC: no IPv6 gateway) requests
    connect over IPv4 only (urllib3 HAS_IPV6 = False); before, the
    IPv6 addresses tried last failed at once with WinError 10051
    "unreachable network", which hid the IPv4 timeouts in every ERROR
    line.
45. **FIXED** (`81c7e6b`): the meshes a batch keeps next to a failed
    tile (#42, "Mesh kept ...") stayed for good: the rerun is a new
    batch that only cleans its own tiles (14 meshes, 1.9 GB after the
    Iceland rerun of 2026-11-07; the user deleted them by hand). After
    its own cleanup a batch now also removes the mesh and .apt of a
    neighbour of a tile it built (_remove_meshes_kept_earlier) when
    that neighbour has a DSF not older than its mesh and none of its
    own neighbours failed now or still awaits step 2.5 (a tile folder
    without DSF, or with a mesh newer than the DSF). Log line
    "Cleaning: removed the mesh kept by an earlier batch of: ...".
46. **DONE** (`e9e40c5`): #44's retry came 10 min after the last
    failure, but the outages of 2026-11-06 lasted 1.5-3.5 h, so in a
    batch whose phase ends sooner the retry fell into the same outage.
    After the 10 min pause the batch now asks every configured server
    for the nodes of an empty box (OSM.overpass_answers) every 5 min
    (overpass_probe_interval) and starts the retry once one answers,
    at most overpass_wait_max (6 h), then tries anyway. Still one
    retry; Stop works throughout. A real check took 44 s for DE's
    empty answer (2026-11-07), hence its 60 s read timeout.
    Full code review 2026-11-07 (all live modules): #47-#52 could make
    a broken tile count as built or leave the GUI stuck, #53-#56 are
    medium; the low items, speedups and water-quality options found are
    under "Open (low priority)" in the planned order of work.
47. **FIXED** (`013242a`): a task that raised in an O4_Parallel_Utils
    worker killed that worker silently; the queue then drained with
    fewer workers and the caller never knew. Used for masks (a mask
    missing, tile counted as built), step 3 conversions (DSF activated
    without the DDS) and imagery pieces. The worker now logs ERROR
    with the task's arguments, counts the task failed (result 0) and
    goes on; build_masks fails the tile when any mask failed; step 3
    wraps convert_texture (_convert_task) so an exception lands in
    IMG.failed_conversions (#20).
48. **FIXED** (`23cf6c9`): PIL opens lazily, so a cut or corrupt
    imagery response passed http_request_to_image and only raised
    later in paste() (outside the retry). Now load()ed inside the try:
    retried like any bad answer.
49. **FIXED** (`8896889`, nvcompress.exe call): the DDS was written
    under its final name; a converter killed by Stop (parallel batch
    taskkill) or a crash left a cut DDS that every later run reused
    (an existing DDS is never rebuilt). Now written under
    FNAMES.temp_path_for and os.replace'd only after a success;
    build_tile removes temp files older than 1 h from the textures
    folder (_remove_stale_temp_files).
50. **FIXED** (`90ba0d8`): when the Global Scenery DSF could not be
    copied or un-7z'd, extract_elevation_and_bathymetry_data called
    exit_message_and_bottom_line and returned nothing; build_dsf went
    on without XP12 rasters and the tile counted as built. Now None
    (ERROR) stops build_dsf; no custom_overlay_src or no Global
    Scenery DSF for the tile stays allowed with a WARNING (rasters
    empty, as before).
51. **FIXED** (`035b7bd`): a coastline that cannot be closed into
    polygons (broken OSM data) made include_sea treat the tile as
    having no sea: built as land. Now coastline_to_MultiPolygon
    returns None on its 3 error paths and step 1 stops with an ERROR
    naming the tile (a custom coastline file works around it).
52. **FIXED** (`1fbf22f`): a GUI step button (steps 1-3, build all,
    geotiffs, obj export, tile list) whose function raised left
    UI.is_working set: the GUI refused all work until restarted.
    The threads now run through UI.run_guarded (ERROR, traceback,
    is_working cleared; SystemExit/KeyboardInterrupt pass).
53. **FIXED** (`50b9caf`): Stop while step 2.5 read the meshes made
    record_water_tris return 0, and build_masks crashed unpacking it;
    a mesh under 100 triangles divided by zero (step_stones 0).
54. **FIXED** (`5139c61`): a patch file that failed to parse (e.g. no
    </osm>) was partly applied (the ways read so far); now skipped
    with a logged WARNING naming the file.
55. **FIXED** (`a58ca0a`): build_curv_tol_weight_map loaded the
    coastline layer for every tile (an Overpass query when not
    cached) even when coast_curv_tol >= curvature_tol cannot refine
    anything (the user's 10 vs 1.0, see the cfg note above), and a
    failed query was ignored (mesh built without coast refinement).
    Now only loaded when the ratio exceeds the lowest weight; a failed
    load stops step 2.
56. **FIXED** (`75f7e40`): tile config, global config (config window,
    app settings, default creation) and .last_gui_params.txt were
    written by moving the old file to .bak, then opening the real name:
    a failure in between left no config or a cut one.
    FNAMES.write_text_atomic copies the old file to .bak, writes a
    temp file and os.replace()s it.
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
- Done 2026-11-03: one Overpass request per layer (#26) and parallel
  batch tiles (#27, 3 cached Nova Scotia tiles: 115 s vs 169 s; fresh
  tiles gain more, they wait on servers).
- Ideas not done: algorithmic work in insert_edge, blur_mask,
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
6. ~~Bare excepts (#3)~~ — on `dev`, as are all issues up to #37.
7. Readiness review 2026-11-05: no known issue left that silently
   produces a broken or incomplete tile; `dev` is the production
   version (run from G:\Ortho4XP on `dev`, fixes in worktrees).
8. ~~#39~~ — on `dev`; gui_smoke and test_parallel_batch run on it.
9. ~~#40, #41, #42~~ — on `dev` (from the first island batch).
10. ~~#43, #44~~ — on `dev` (from the Denmark/Poland and Iceland
    batches).
11. ~~#45, #46~~ — on `dev` (from the Iceland rerun); gui_smoke and
    test_parallel_batch run on it.
12. ~~#47-#56~~ — from the full code review of 2026-11-07.
    Open (low priority, from that review; none breaks a tile):
    - O4_Vector_Map patch shapes test `.all()` where `.any()` is meant;
      OBJ8 patch file handle not closed; the large-lake log line
      swaps lat and lon.
    - MESH.sort_mesh starts its tool without wait().
    - Ortho4XP.py: exit 0 on bad CLI arguments, 3 bare `except:`.
    - Dead code: O4_Recut_Water.py, split_polygon, indexed_difference,
      ensure_ccw, point_to_segment_distance, convolve_periodic,
      are_encroached_old.
    - Providers GeoPunt2012/GeoPunt2015/IAU2008 name extents that do
      not exist.
    - Speedups: DEM elevation lookup with numpy fancy indexing (7x,
      byte-identical, measured), insert_edge, blur_mask.
    - Water quality options: repair invalid OSM polygons instead of
      dropping them; treat empty relation roles as outer.

## Coding style

- PEP 8, with comments explaining *why*, not *what*.
- Keep changes minimal and behaviour-preserving unless the change is the fix.
- Prefer `os.path`/`pathlib` over string path concatenation.
- Use the project's own `UI.vprint` / `UI.lvprint` for messages, not `print`.
