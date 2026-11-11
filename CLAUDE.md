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

Unit tests: `venv\Scripts\python.exe -m pytest` (repo root, ~15 s, 465
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
Baseline (since the airport smoothing fix #73, 2026-11-08):
`G:\Ortho4XP_baseline\+55+012_Arc_ZL17_test-4fa5e9f_frozen\` — `inputs\`
(4 OSM layers of the old baseline, DEM N54-N56 E011-E013 = the user's
library .hgt files, X-Plane 12 Global Scenery +55+012.dsf, the old
baseline's Ortho4XP.cfg), `expected\` (DSF, dsf2text, 17 masks, logs),
`SHA256SUMS`, `BASELINE.txt`. Mesh 1,094,356 triangles at min_angle 10,
no WARNING. Same inputs (copied from the previous baseline, hash-checked),
older baselines: `+55+012_Arc_ZL17_test-702e768_frozen` (#32 to #72:
1,094,388 triangles; same 17 masks) and
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
in a fix worktree), restored afterwards (since 2026-11-11 also a module
the commit lacks is removed again; before, it blocked the next checkout
of a commit that has it; same in sims_in_ws.py).
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
`G:\Ortho4XP_baseline` holds only the three `_frozen` baselines.
Test builds go to `G:\Ortho4XP_tests\<tile>_<provider>_<ZL>_<branch>-<sha>\`.
Test helpers (venv Python; the sims below through sims_in_ws.py) are in
`G:\Ortho4XP_tests\tools\`: `run_masks.py` (step 2.5 only, optional
custom extent / alternative module dir), `sim_osm_failure.py` (CLI
build with a simulated Overpass failure on the water layer) and
`sim_water_geometry_failure.py` (CLI build where cleaning the inland
water geometry fails), `sim_mask_dem_failure.py` (CLI build where the
DEM for masks fails in step 2.5), `sim_batch.py error|stop` (batch
of 3, steps 1-2.5, with an error or a Stop on tile 2; since #81 the
Overpass error fails all 3 tries of tile 2 (step 1 calls 2, 4, 5;
before: tile 2 and its one retry, calls 2 and 4), `error-once` only
the first try, so the next try builds it) and
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
local mock servers DE and FR; no real Overpass traffic; since #83 the
order DE, DE, FR and the skip of a dead server, health file in a
scratch OSM_dir; 12 checks), `sim_dem_failure.py
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
(#30, #80: 3 processes query a mock server at most 2 at once, and
do reach 2; a killed slot holder frees its slot; 429 wait), `check_step3_provider.py [tile_dir]` (#31: empty,
unknown and zone providers stop build_tile at once, GO2/Arc pass; uses
an existing tile's mesh read-only and silences UI.logprint, which
build_tile calls directly).
`Ortho4XP.cfg` uses `overpass_server_choice=DE`; since #23 tentatives
5-8 alternate with the other servers in overpass_servers.txt (since
#78: DE and FR; KU was dead). The failure sims replace the whole server list
with one closed port, so they still fail without fallback.
Never run the full-build sims (sim_osm_failure, sim_water_geometry_failure,
sim_mask_dem_failure, sim_mesh_failure, sim_step3_failures, sim_dem_cli,
sim_batch) with cwd G:\Ortho4XP: they would build into the user's
Tiles\zOrtho4XP_+55+012, one of their 9 test tiles (+54..+56 /
+010..+012, GO2 ZL16, their settings), and use their config, caches
and log. Use sims_in_ws.py. Only test_batch_order, test_parallel_batch
and gui_smoke still run in G:\Ortho4XP (other tiles; see their notes).
Since 2026-11-03 the user's global `Ortho4XP.cfg` holds their own build
settings; since 2026-11-08 13:41 (saved from the GUI after the
+65-019 DEM experiment, see Performance notes; the 1.0 state is in
Ortho4XP.cfg.bak): curvature_tol 0.5, limit_tris 5, mesh_zl 19,
min_angle 10, mask_zl 16, airport cover at ZL18 for all airports
(cover_airports_with_highres=True, cover_extent 3 km, apt_smoothing_pix
8; was ICAO only, see .before-bushflying.bak), road_level 4,
apt_curv_tol 0.25 / 2 km, coast_curv_tol 0.5 / 0.5 km (= curvature_tol,
so no effect, #55), XP12 water, use_decal_on_terrain True,
distance_masks_too True, batch_parallel_tiles 3, cleaning_level 3
(since 2026-11-05 14:22, see #42), max_download_slots 2 (2026-11-11).
The GUI gives GO2 at ZL16. Tile configs win over the global one: a
changed global setting reaches an existing tile only when its tile
config is changed too (or deleted before the rebuild). That bit the
346-tile batch: 66 queued Iceland/Denmark rebuilds kept curvature_tol
1.0, decal and distance masks off in their tile configs, and phase 1
re-meshed them at 1.0 on 2026-11-09. On 2026-11-11 those 66 tile
configs were set to the global values (5 lines each; backups with
SHA256SUMS in G:\Ortho4XP_tests\cfg_backups\2026-11-11_curvature_tol
and \2026-11-11_masks_decal); since then all 133 tile configs equal the
global cfg in every tile setting. Their 1.0 meshes are replaced only
when the batch reruns steps 1-2.
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
  Then on dev a3f5bc7 in G:\Ortho4XP: gui_smoke 7/7 (85 tiles on the
  map, 0 callback errors; cfg, .last_gui_params.txt and log
  unchanged). Not run: test_parallel_batch.
- Low items #57-#62, each `fix/<name>` from dev 3ddeb72. `test` @
  ba5bb4b: 291 unit tests, pyflakes 0, regression PASS (DSF, 17/17
  masks, app log identical), sims_in_ws all 15/15. CLI usage errors
  checked by hand: "55", "55 x", "55 12 Arc", "55 12 Arc zz" exit 2.
- #63 `fix/osm-reader-keyerror` @ 9690e8f: new unit test (two lakes
  sharing a way; KeyError on dev), all 35 bundled extents read and
  polygonised. `test` @ 2bd7c60: 292 unit tests, pyflakes 0,
  regression PASS (DSF, 17/17 masks, app log identical). sims_in_ws
  not run: no sim reads an OSM file without target tags.
- Second review 2026-11-08 (#64-#72), each `fix/<name>` from dev
  2835720 with unit tests where testable (12 new; #65's, #64's and
  #72's fail on dev): `fix/comb-color-code`, `fix/download-retry-race`,
  `fix/airport-small`, `fix/small-leftovers` (#67-#71, one commit
  each), `fix/tile-config-bad-value`. `test` @ 2afd392: 304 unit
  tests, pyflakes 0, regression PASS (DSF, 17/17 masks, app log
  identical), sims_in_ws all 15/15, sim_overlay 7/7 (tmp clean on every path).
- #73 `fix/airport-smoothing-step` @ b2be126 and #74
  `fix/zones-in-tile` @ 9e26a65 (10 new unit tests; #73's fail on
  dev: window one column east and one row south). `test` @ 4fa5e9f:
  314 unit tests, pyflakes 0; regression vs test-702e768_frozen FAIL
  as expected: masks 17/17 and app log identical, mesh 1,094,356 vs
  1,094,388 triangles from the same 269,909 input vertices, DSF
  differs. Explained with the frozen .apt and .mesh: 2,410 moved and
  3,300 re-elevated vertices, all within 1.3 km of the 10 airports
  (the intended change); 7,899 re-elevated farther away, median
  0.012 m (one DSF elevation step), all on water (5,086 of the 5,088
  that match a .mesh node are water-triangle vertices, the rest are
  step 3's XP12 water recut nodes). Cause: build_mesh smooths inland
  water 10 passes over a Python set of triangles; 16 fewer vertices
  renumber the mesh, so the set order and the sequential means change
  everywhere. New baseline test-4fa5e9f_frozen (inputs copied from
  test-702e768_frozen, 15 files hash-checked), DSF 38,698,067 bytes,
  same hash as the first 4fa5e9f run; repeat run PASS;
  sims_in_ws all 15/15.
- Third pass 2026-11-08 (config review for low-level flying): #75
  `fix/mesh-cap-warning` @ e82d50c, #76 `fix/decal-land-only` @
  5534d9c (11 new unit tests; #76's fail on dev). `test` @ 2125eb4:
  325 unit tests, pyflakes 0, regression PASS against
  test-4fa5e9f_frozen (DSF, 17/17 masks, app log identical: no
  WARNING), sim_mesh_failure as designed.
- #77 `fix/osm-cache-check` @ 68c7d5c: 14 new unit tests (339 pass),
  pyflakes 0, regression --overlay PASS (DSF, 17/17 masks, app log
  identical); real check of +34+024 an hour after its download: 4
  layers unchanged (counts equal to the cache), coastline no answer
  (Overpass outage).
- 346-tile batch (Mediterranean, NW America, Norway, Iceland; 2026-11-08
  16:07): killed by a Windows Update restart on 2026-11-11 02:29 in
  phase 2 (workers exit 0x40010004). 65 built, 178 waiting for steps
  2.5-3, 102 lost step 1 to Overpass (DE ConnectTimeout, KU
  ReadTimeout, 11-08 19:00 to 11-10 ~20:00; the #46 retry at 11-10
  00:14 failed again), +35+028 open sea. 11 overlays failed: the
  user's Global Scenery has no DSF for +44..+46 / -122..-125.
- #78 `fix/overpass-outage` @ dad25be: 13 new unit tests (352 pass;
  10 fail on dev), pyflakes 0, regression --overlay PASS (DSF, 17/17
  masks, app log identical), sims_in_ws dad25be all 15/15 (sim_batch's
  overpass_answers stub now takes the bbox argument); the new probe
  against the real servers: DE answers both queries (33-39 s).
- #79 `fix/batch-leftover-tiles` @ 297b4d5: 8 new unit tests (360
  pass), pyflakes 0, regression PASS (DSF, 17/17 masks, app log
  identical), the 5 batch sims as designed (leftover file: 3 x +55+012
  after error/stop/dem/exception, none after error-once; the sims'
  tile list has one tile 3 times, see #28), and
  `G:/Ortho4XP_tests/tools/gui_leftover.py <src> <png>` (cwd
  G:\Ortho4XP, real GUI, refuses to run if the user has a leftover
  file): 6/6 (selected on open, again after reopening, Clear empties
  it and removes the file); .last_gui_params.txt and Ortho4XP.log
  unchanged. The overlay fix of regression.py/sims_in_ws.py (a module
  new in the overlay is removed afterwards) is in the tools since
  2026-11-11.
- #80 `fix/overpass-two-slots` @ ba2dad2, #81 `fix/batch-overpass-pause`
  @ 12119d7, #82 `fix/batch-neighbour-barrier` @ 736e9c1 (from #81),
  2026-11-11: 3 new slot tests (one with a second process holding both
  locks), the #44/#46/#78 retry tests replaced by 20 gate/requeue/pause
  tests (fake clock, probe run synchronously), 7 neighbour-barrier
  tests (3 fail on #81's global barrier); check_overpass_slot.py (now
  expects a peak of exactly 2) 4/4. `test` @ 755f292: 366 unit tests,
  pyflakes 0, regression PASS (DSF, 17/17 masks, app log identical),
  sims_in_ws all 15/15 (sim_batch error: tile 2 fails try 1, 2 and 3
  = step 1 calls 2, 4, 5, "Tiles built: 2, failed: 1."; error-once
  builds it on try 2), sim_batch_cleaning par with real workers: phase
  2 of +55+012 started right after its own steps 1-2 (the sea tile
  ended first), mesh kept until the cleanup, DSF byte-identical to
  test-4fa5e9f_frozen (the sim compared against the pre-#73 baseline
  and reported FAIL; its path is fixed in the tools).
  test_parallel_batch on `test` @ 323f13c, run from the _test worktree
  (cwd = code under test: junctions to the F: caches, a copy of the
  user's Ortho4XP.cfg, and tmp/Tiles/Geotiffs/yOrtho4XP_Overlays made
  by hand, as Ortho4XP.py's startup would; without tmp the first try
  failed in step 3 and at batch_context.json; the user's G:\Ortho4XP,
  Masks and log untouched; junctions removed with rmdir afterwards):
  compare 166/166 masks and 3 DSFs identical seq/par (seq 11m20s,
  par 7m57s; the 3 tiles are one row, -066 neighbours both, so the
  barrier acts as the global one here), fail, stop (2 slots: third
  tile never started, no tool left) and context all ok; all cached,
  no download. Not run: gui_smoke, and a real outage.
- #83 `fix/overpass-server-switch` @ 93c123f, 2026-11-11: 18 new unit
  tests (test_overpass_servers.py: order, no wait after the last try,
  failure kinds, 429 wait, shared skip/probation/clear, probe clears
  the skip, broken health file, layer fallback only after timeout/size,
  old-data NOTE), the #23 server-choice tests replaced by _server_order
  tests, the #81 batch tests kept at pause_after 3 in their fixture
  (probe interval 0 on the real clock) plus one for the default 1;
  sim_overpass_fallback (rewritten for DE/FR) 12/12. `test` @ ceafb3a:
  384 unit tests, pyflakes 0, regression PASS (DSF, 17/17 masks, app
  log identical; no health file written), sims_in_ws all 15/15
  (sim_batch now sets overpass_probe_interval 0): sim_osm_failure stops
  after the combined request ("... from any Overpass server (last: DE:
  ConnectionError)"), no per-query requests; sim_batch error: try 1
  and 2 fail on DE (the 3rd DE failure skips it), try 3 fails at once
  ("all servers skipped"), "Tiles built: 2, failed: 1."; error-once
  builds it on try 2. Not run: a real outage. Cosmetic: the pause line
  says "failed 1 tiles in a row" (fixed by #92).
- Full code review 2026-11-11, #84-#96 (branches under item 20 of the
  planned order). `test` @ 5c3b818 (#84-#93): 453 unit tests, pyflakes
  0, regression PASS (DSF, 17/17 masks, app log identical; step 3 28.3
  -> 20.6 s), sims_in_ws all 15/15, gui_smoke 7/7 against _test/src
  (131 tiles on the map; the user's .last_gui_params.txt, log and cfg
  unchanged, hash-checked). `test` @ 9de01b9 (+ #94-#96): 453 unit
  tests (no ResourceWarning), pyflakes 0, regression PASS (DSF, 17/17
  masks, app log identical, 74 s), sims_in_ws all 15/15 (Triangle4XP
  pipe change through sim_mesh_failure), sim_overlay 7/7 (DSFTool).
- #97 `fix/custom-dem-coverage` @ c67f9e8 (the Nov 8 work rebased on
  dev e62595e, plus the total-sample limit): 12 new unit tests (10
  fail on dev; the 2 "stays quiet" pass there), regression PASS (DSF,
  17/17 masks, app log identical; the tile has no custom_dem),
  sim_dem_failure 9/9, sims_in_ws all 15/15. #98 `fix/test-lint` @
  58588f0: same 453 tests, pyflakes 0 incl. tests. `test` @ a6bbe04:
  465 unit tests, pyflakes 0, regression PASS (DSF, 17/17 masks, app
  log identical). `sim_custom_dem_gap.py <scratch>` (new, cwd =
  regression worktree; steps 1-2 of +55+012 with an east-half raster
  cut from the frozen N55E012.hgt, build dir in <scratch>): 7/7, one
  WARNING "(missing: west)", west half at the edge value (36 m at
  55.7 N), mesh built, no second WARNING in step 2.
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
   (`venv\Scripts\python.exe -m pyflakes Ortho4XP.py check_osm_cache.py
   src/O4_*.py tests/*.py` must stay at 0 findings; tests since #98). The IMG/OSM/OVL/TILE/UI imports in
   O4_Config_Utils are setattr targets (`_CFG_MODULES`, #84), not unused.
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
57. **FIXED** (`23c54cc`): an altitude_high/altitude_low patch
    polygon counted as closed when its ends differed in one coordinate
    only ((a != b).all(), now .any()); an OBJ8 patch file without
    ANCHOR stayed open; the large-lake log line swapped lat and lon.
58. **FIXED** (`be2be64`, moulinette.exe call): sort_mesh (GUI
    Shift-click on step 2) never wait()ed for moulinette and logged
    "Moulinette applied" whatever happened; now ERROR with the exit
    code, a missing tool is reported.
59. **FIXED** (`3172b4e`): CLI usage errors (missing or non-numeric
    lat/lon/zoomlevel) exited 0; now 2 (as argparse). Missing Utils
    folder or an uncreatable data folder exits 1. No bare except left
    in Ortho4XP.py.
60. **DONE** (`3a3ad44`): dead code removed: split_polygon,
    indexed_difference, ensure_ccw, point_to_segment_distance,
    convolve_periodic, Vector_Map.are_encroached_old (no caller; some
    broken under shapely 2) and O4_Recut_Water.py (never imported, an
    older copy of O4_Bathymetry.recut_water_tris).
61. **FIXED** (`b69107c`): GeoPunt2012/2015 named extent GeoPunt,
    IAU2008 extent IdF; neither exists. GeoPunt -> Vlanderen; IAU2008
    (in_GUI=False) has no extent line now (global). A unit test checks
    every .lay extent exists.
62. **DONE** (`2115b84`): DEM.alt_vec_nostrict picks its samples by
    numpy fancy indexing instead of per-point list comprehensions;
    byte-identical (unit test against the old code), 6x faster for
    200,000 nodes, but step 1 of +55+012 is unchanged (32.6 vs 32.9 s):
    elevation lookups are a small part of it.
63. **FIXED** (`9690e8f`, a regression from #3 / `ed1769f`): reading
    an OSM file without target tags (combined-provider extents,
    custom coastline/water files, patch files) crashed with KeyError
    when two relations share a way: the bare except around
    dicosmfirst["w"].remove() had been narrowed to ValueError, but it
    is a set. 2 of the 35 bundled extents crashed (Italy/Veneto,
    LowRes/Finland), so a combined provider using them failed. Normal
    layer reads pass target tags and were never affected. Now
    discard(). Found while measuring the water options (below).
    Second review 2026-11-08 (audit of the 145 except handlers from
    #3, then the modules the first review read only in part):
64. **FIXED** (`3260df9`): a combined provider line whose color code
    was neither a named filter nor L/D left `b` unbound; the
    UnboundLocalError dropped the whole combined provider instead of
    that line. Second (and last) wrong narrowing of #3.
65. **FIXED** (`ff95ab4`): download_textures put a failed texture back
    on the queue after its "pending" count had dropped, so the main
    loop could send "quit" first: the retried texture was neither
    downloaded nor in `failed`, and the DSF was activated without it
    (#20 class, timing dependent). The 3 attempts now run inside the
    worker's task.
66. **FIXED** (`f3989a6`): Airport_Utils: a runway > 3.5 km from all
    airports named like an existing key (two "Airstrip"s, an ICAO
    code) replaced that airport (_add_far_airport); an 'include'
    apron was tested with runway_pol.is_valid (NameError without
    runways -> apron dropped); the runway centerline was overwritten
    by the first piece's outline (second piece of a runway cut by the
    tile edge); two "Bad runway" log lines began with "1".
67. **FIXED** (`2cd4ec5`): overlay tmp text files closed on errors
    (with), so Windows can delete them.
68. **FIXED** (`ecf8e5a`): build_mesh's custom_dem ERROR now carries
    the cause (was print() to the console only); community_mesh tests
    r.status_code instead of str(Response).
69. **FIXED** (`9b1d867`, log only): merge_pol's dropped polygon
    (unary_union failure) is a logged WARNING with its bounds;
    insert_edge(check=False) returns (output unchanged).
70. **FIXED** (`5c4916d`): requests sessions closed (one per texture,
    and the ones made after a connection failure).
71. **FIXED** (`8c966a1`): custom coastline/water folders: the merged
    file was rewritten after every input file and written even when a
    file failed to parse, then used for good instead of the folder.
    OSM.read_custom_osm_dir: one write, an unreadable file stops the
    step with an ERROR naming it.
72. **FIXED** (`1088576`): a tile config line with a bad value for a
    known setting ("true", "abc") was skipped silently (tile built
    with the value from before); now a logged WARNING. Unknown keys
    stay quiet. The user's 90 tile configs have none.
73. **FIXED** (`b2be126`, CHANGES OUTPUT, new baseline):
    smooth_raster_over_airports used (x1 - x0) / nxdem as the DEM
    sample spacing; the DEM has nxdem samples from x0 to x1 inclusive
    (DEM.alt_vec divides by nxdem - 1). The smoothing window and the
    airport image in it sat up to one sample east and south of the
    airport (a full sample at the tile's east/north edge). Every tile
    with an airport gets a slightly different DEM there; tiles built
    before keep the old placement until rebuilt (not worth a rebuild).
74. **FIXED** (`9e26a65`): the GUI saved a zone in a tile's config
    when the tile's lat and lon were both among the zone's vertex
    coordinates truncated to integers (3 copies in O4_Config_Utils):
    a zone covering the tile with all vertices outside it was lost
    for the CLI and batch workers, and lat/lon were not told apart.
    Now zones_in_tile(): polygon overlap with non-zero area. The
    user's 90 tile configs have no zones.
75. **FIXED** (`e82d50c`, log only): limit_tris goes to Triangle4XP as
    a cap on Steiner points (-S); at the cap Triangle stops refining
    silently, so parts of the mesh stay coarser than curvature_tol.
    build_mesh now logs a WARNING (steiner_cap_reached; the bundled
    triangle.exe adds exactly int(S) points, checked by a test). None
    of the user's 90 tiles came near it (largest DSF 67 MB, ~1.9 M
    triangles; cap ~5.2 M at limit_tris 5).
    **REOPENED 2026-11-11: the WARNING never fires on a real tile.**
    Triangle4XP.exe (not the plain triangle.exe of the test) stops
    with only ~83 % of -S as new vertices: +65-019 at curvature_tol 0.5,
    limit_tris 5: -S 2,515,274, 2,074,524 added, 4.19 M bad triangles
    left (-V statistics), no WARNING; uncapped the same tile needs 10.08
    M triangles. An uncapped 1.0 mesh used 78 % of its -S, so the
    vertex count cannot tell capped from not; where the budget goes is
    not found (only 2.42 M circumcenters computed). A fix needs
    Triangle4XP to report steinerleft (rebuild the exe) or another
    signal. Also the "~1.9 M triangles" above was wrong: DSFs hold ~15
    bytes per triangle (+65-019: 60 MB, 4.12 M), so 67 MB is ~4.5 M:
    the user's largest tiles were at the cap.
76. **FIXED** (`5534d9c`): use_decal_on_terrain put the decal on
    masked sea terrain too (tri_type != 1); now land only, as the
    option is documented. No effect with the option off.
77. **DONE** (`68c7d5c`, new tool): check_osm_cache.py [tiles]
    [--csv f] reports which cached OSM layers changed since their
    download (the cache keeps no ids or dates, only the file mtime).
    One Overpass request per layer (src/O4_OSM_Freshness.py): count
    of matching elements now, and of elements edited after mtime - 1 h
    (newer:); unchanged = no edits and the same counts as the cache
    file. Also flags a small_roads cache without a road type the
    tile's road_level wants: the file name is the same at every level,
    so raising road_level (e.g. to 5 for tracks) silently reuses the
    old cache (not fixed in the build; the user's caches are complete
    for level 4). Read only, uses the Overpass slot; ~1 min per layer
    (as much server time as a download). The layer queries are now
    VMAP constants (`ec0a49e`, output unchanged).
78. **FIXED** (`a29d404`, `3b42d30`, `de396a6`, `dad25be`): the
    Overpass outage of 2026-11-08..10 (DE overloaded: 1,090
    ConnectTimeouts in the failed tiles' logs, yet 426 layer downloads
    in between) cost the 346-tile batch 102 tiles and ~1 day: KU never
    answered (234 fallback tries of up to 190 s), the #46 probe's
    empty-box query was answered at 11-10 00:14 while real requests
    kept failing, and the retry pass then took 20.7 h for 119 tiles,
    holding up phase 2. Now: (1) overpass_servers.txt has FR
    (overpass.openstreetmap.fr: whole planet, 3-4 s, but its data was
    a month old) instead of KU; tested and not usable: kumi.systems,
    mail.ru, openstreetmap.ru, osm.jp (no answer), osm.ch
    (Switzerland only), lz4./z.overpass-api.de (the same DE machines).
    (2) check_osm_cache.py refuses an answer whose osm_base is older
    than the cache file (FR's would report every layer unchanged).
    (3) The batch's wait probe counts aeroway elements in the first
    tile to retry (read timeout 90 s; HTTP 200 with <remark> is no
    answer). (4) The retry pass ends after overpass_retry_give_up (3)
    tiles in a row fail on Overpass again; the rest fail untried with
    one ERROR line listing them, and the next phase starts (a success
    or another error resets the count; sequential and parallel).
79. **DONE** (`297b4d5`, GUI feature): a batch keeps its tiles not
    done yet in .last_batch_tiles.txt (repo root, gitignored; written
    at the start, a tile removed when built through the last phase or
    skipped as open sea; failed, stopped and unstarted tiles stay; empty
    = no file). The tile window selects them when it opens, so Batch
    Build carries on after a crash, a restart or failures. New button
    "Clear selection": unselects all, and removes the file when no
    batch runs. Plain text, one +LL+LLL per line, # comments.
    Choke points of the 346-tile batch (2026-11-08..11, from its logs):
    phase 1 took 52.8 h and 154.7 worker-hours, 121.4 of them (78 %) in
    221 step 1 tries lost to Overpass (median 28 min each); the 127
    successful step 1 downloads spent 30.9 of 31.9 h waiting for
    Overpass (0.3 min computing each); good hours saturated the single
    Overpass slot (40-87 layers/h), ~40 bad hours gave 0-3. Steps 2,
    2.5 and cached step 1 took under 2 min per tile: CPU is not a
    choke point. 178 tiles with finished meshes waited for phase 2.
80. **DONE** (`ba2dad2`): two Overpass requests at a time
    (OSM.overpass_max_parallel = 2, a module constant): overpass-api.de
    grants 2 per IP; lock files .overpass.lock and .overpass.lock1, a
    request takes the first free one (three at once got HTTP 429, #30).
81. **DONE** (`12119d7`): batches (sequential and parallel) hold step 1
    back during Overpass outages (_OverpassGate): after 3 tiles in a
    row lost step 1 to Overpass (overpass_pause_after), tiles whose 5
    OSM layers are not all cached do not start; cached tiles go on. A
    real query on the first held tile (OSM.overpass_answers with bbox,
    in a thread) every 5 min, or a running tile getting through step 1,
    reopens it; after 6 h it reopens anyway. A tile that lost step 1 to
    Overpass goes back into the queue, not before 10 min
    (overpass_retry_wait), and fails after 3 such tries
    (overpass_tile_tries). Replaces #44's end-of-phase retry pass,
    #46's wait before it and #78's give-up (overpass_retry_give_up and
    _wait_for_overpass_retry are gone). A tile at road_level < 2 has no
    small_roads cache and counts as needing Overpass (held during a
    pause only).
82. **DONE** (`736e9c1`): parallel batches start steps 2.5-3 of a tile
    once it and its neighbours in the batch (the 8 around it, whose
    meshes step 2.5 reads, #28) have ended steps 1-2 (built, failed or
    sea), not once all tiles have; up to batch_parallel_tiles workers
    per phase (so up to 2 x N processes), and imagery downloads overlap
    other tiles' Overpass requests. Masks and DSFs as with the global
    barrier (a neighbour's mesh is final once its phase 1 ended;
    cleanup still waits for the batch end, #42). Sequential batches
    keep the strict two phases (#28).
83. **DONE** (`93c123f`): Overpass server order and failures. Before:
    a layer went 4 times to DE as one request, then each query 8 times
    (FR only on the 5th and 7th), waits up to 256 s also after the last
    try: up to ~55 min and 12 requests before a layer failed, and every
    worker and layer found out on its own that DE was down. Now
    get_overpass_data asks the configured server twice (10 s apart;
    after 429 the server's wait, >= 60 s), then each other server once,
    no wait after the last try. Failure kinds: down (no connection,
    429, 5xx), timeout (read), size (<remark>, error or cut answer; an
    answer with a <remark> over 1000 bytes used to pass as complete). A
    layer falls back to one request per query only after a timeout or
    size failure; all servers down fails the layer at once (~1 min).
    OSM_data\.overpass_health.json (+ .lock; shared by all processes,
    written only when something fails, never in a cached build): 3
    down/timeout failures in a row skip a server for 15 min, the
    remaining tries of the running request included; then one try
    (probation: a failure skips it again at once); a success or an
    answer to the batch's probe (which asks skipped servers too) clears
    it. A downloaded layer whose osm_base is more than 2 days old is
    logged ("NOTE: OSM <layer> layer of <tile> has data of <date> from
    server FR (n days old)"): the cache does not record its source, so
    this line is the only trace (check_osm_cache.py, or a rebuild once
    FR caught up). Batch: overpass_pause_after 1 (was 3). Data dates on
    2026-11-11 08:16 UTC: DE 1 min old, FR 2026-10-13 (29 days; 10-10
    earlier that day, so catching up, not a fixed lag). overpass_servers.txt
    comment updated; max_osm_tentatives, layer_request_tentatives and
    _pick_overpass_server are gone (the sims set max_osm_tentatives, now
    unused, harmlessly).
    Full code review 2026-11-11 (all live modules, a profile and an
    audit of every exception caught during a build, sys.monitoring):
84. **FIXED** (`238b198`): setting values from Ortho4XP.cfg, tile
    configs, .last_gui_params.txt, the GUI and .lay files went through
    exec()/eval(), so a config line ran as Python code. Values are now
    data: O4_Cfg_Vars.parse_cfg_value (bool/list via ast.literal_eval,
    else the declared type), get/set_cfg_variable instead of exec;
    the old "zone_list.append(...)" lines still load
    (parse_legacy_zone). .lay fake_headers may name
    user_agent_generic (literal_with_names). The user's 133 tile
    configs, the global config and all 68 providers read to identical
    values (checked by script).
85. **FIXED** (`ff01135`): parallel_worker's success flag was a
    read-modify-write shared by the threads; a failed item could be
    overwritten by a concurrent success (lost update), so the caller
    saw success. Now only ever set to 0.
86. **FIXED** (`ddb6fbd`): an imagery answer without Content-Type
    raised KeyError; 429/408/5xx were retried at once. Now retried
    after Retry-After (429/503) or 2 * 2^n s (2-60 s), Stop checked
    every 0.25 s.
87. **FIXED** (`05c1277`): the per-texture requests session had
    urllib3's 10-connection pool for up to 16 threads: 12-15 "pool is
    full" discards per Arc texture (new TCP+TLS each). Now
    pool_maxsize = max(max_threads, 10). Download time unchanged
    (~1.5-1.9 s per texture, Arc ZL17 and GO2 ZL16, bound by the
    servers); 2 textures at once ~20% faster than one after the other
    (max_download_slots=2 is the user's choice, not set).
88. **DONE** (`4432c6c`): needs_mask decoded the mask PNG for every
    texture (566 decodes on +55+012 for 17 masks). LRU of 8 decoded
    masks keyed by (path, mtime_ns, size), cleared after build_dsf:
    48 decodes. Same bytes.
89. **DONE** (`0c990af`): improved_buffer used shapely's deprecated
    resolution=; quad_segs=1 gives identical WKB (shapely 2.1.2).
90. **DONE** (`053880c`): 32 open()/close() pairs became with-blocks
    (a raise left the file open, on Windows it could not be deleted or
    replaced); batch worker log closed when Popen fails.
91. **DONE** (`28fa45f`): build_texture_from_bbox_and_size had a
    per-piece downscale that never ran (its condition was never true);
    removed (running it would add seams).
92. **DONE** (`e0a612d`, log only): the #81 pause line says "failed 1
    tile" or "N tiles in a row".
93. **DONE** (`5f46a25`): build_dsf wrote pools and patch commands
    with one struct.pack + write per 16-bit value (15.6 M calls, ~10 s
    for +55+012); now array.tobytes() per plane/command
    (_pool_planes, _patch_triangle_cmds, _cross_pool_triangle_cmds),
    float2qquad via format(). Same bytes (unit tests against the old
    loops; regression DSF byte-identical). Step 3 with #88: 28.3 s ->
    20.5 s.
94. **DONE** (`085fe2f`): removed the disabled ("for ... in []")
    runways-as-lines block in encode_runways_taxiways_and_aprons; it
    used numpy.array(LineString), broken on shapely 2.
95. **FIXED** (`ee300f7`): parallel_worker called progress_bar(None)
    at "quit" and caught the TypeError (seen in the exception audit).
96. **DONE** (`5870e56`, `d8dc741`, `e100f95`; Triangle4XP.exe,
    moulinette.exe and DSFTool.exe calls): their stdout pipes are
    closed before wait(), record_water_tris's mesh file in a with;
    tests read and write files through pathlib. pytest -W
    default::ResourceWarning reports none.
    Looked at and left: Vector_Map's "if False" road block (upstream's
    switch), insert_edge (~21 s) and blur_mask (~17 s) (change the
    output, see item 12 below), the log write race (3 processes x 4000
    lines, none lost).
97. **FIXED** (`c67f9e8`; started 2026-11-08 in an uncommitted
    worktree, finished 2026-11-11): outside a custom_dem raster the
    altitude is the raster's nearest edge value (alt_nostrict clamps,
    so does Triangle4XP), but the config hint said zero and nothing was
    logged. Step 1 now logs a WARNING naming the tile, file and
    uncovered sides (DEM.raster_gaps_in_tile; one sample spacing short
    is no gap, e.g. Copernicus). Composite local sources, iterate's
    LIDAR and step 2.5's reread pass partial_ok (quiet), info_only
    reads too. A GDAL raster over 65535 samples per side (uint16
    indices in alt_vec_*) or over 2^31 - 1 in all (Triangle4XP's
    alt[ny * nxdem + nx] is a C int: 46341 x 46341 overflows) gave wrong
    altitudes silently; now DEMError stops step 1. Hint documents
    {latlon} (N55E012). Viewfinder and .hgt paths unchanged.
98. **DONE** (`58588f0`, tests only): the batch tests' shared `lines`
    fixture moved to conftest.py (O4 imports inside the fixture, after
    pytest_collection's cwd switch); pyflakes is 0 for tests/ too
    (was 10: fixture imports, one unused variable).
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
- Ideas not done: algorithmic work in insert_edge, blur_mask.
- 2026-11-11 (#88, #93): step 3 of the regression 28.3 s -> 20.5 s,
  same DSF. Profile of a cached build: insert_edge/rtree ~21 s,
  blur_mask ~17 s; both left (they would change mesh/mask bytes).
- Imagery downloads (#87): ~1.5-1.9 s per texture whatever the pool;
  2 textures in parallel ~20% faster. The user set max_download_slots=2
  on 2026-11-11 (old cfg: Ortho4XP.cfg.before-download-slots.bak).
- Mesh accuracy vs DEM source, 2026-11-08 (+65-019 Iceland, steps 1-2,
  limit_tris 5; mesh altitude error on land against IslandsDEM v1
  native (~8 x 20 m) as truth, so the IslandsDEM builds are favoured):
  Viewfinder ct 1.0: RMSE 1.68 m, p99 6.2 m, 3.96 M tris;
  Viewfinder ct 0.5: 1.37 / 5.2 m, 4.37 M; IslandsDEM native ct 1.0:
  1.76 / 6.3 m, 4.16 M; native ct 0.5: 1.22 / 4.5 m, 4.41 M;
  IslandsDEM 1" ct 1.0: 2.71 / 9.7 m, 2.43 M. So curvature_tol matters
  more than the DEM here; a 1" resample of a finer DEM is worse than
  Viewfinder. Source rasters kept in G:\Ortho4XP_tests\dem_data
  (98 MB); the experiment's worktree dem_ws was removed 2026-11-11.
- Mesh budget, 2026-11-11 (+65-019, dev 84d09cd, Viewfinder input,
  the user's tile config: apt 0.25, coast 0.5; error in m on land vs
  IslandsDEM native; vs Viewfinder itself within ~0.07 m, so the error
  is the mesh simplifying the DEM, not the DEM). Results and -V log in
  G:\Ortho4XP_tests\dem_results\2026-11-11_+65-019\.
  ct / limit_tris -> triangles, RMSE, p99, steep (>20 deg) p99:
  1.0/5 -> 4.12 M, 1.68, 6.2, 7.3 (not capped: same with 40);
  0.5/5 (user) -> 4.37 M, 1.37, 5.2, 6.6 (CAPPED, no WARNING, #75);
  0.5/5 mesh_zl 18 -> 4.76 M, 1.26, 4.7, 6.1 (fewer input nodes leave
  more of the -S budget; imagery max is ZL18, so no loss);
  0.25/5 -> 4.38 M (same as 0.5/5: the cap decides);
  0.25/10 -> 9.13 M, 0.87, 3.2, 4.2 (capped);
  0.5/40 -> 10.08 M, 0.90, 3.2, 3.8 (uncapped);
  0.35/40 -> 15.8 M, 0.70, 2.5, 3.1; 0.25/40 -> 23.6 M, 0.60, 2.1, 2.8.
  The cap refines worst triangles first (priority queue), so a low ct
  with the cap as budget is as good per triangle as an uncapped
  higher ct (0.25/10 vs 0.5/40), and flat tiles stay under any cap.
  Step 2: 36 s at 4.4 M, 72 s at 9 M, 171 s at 23.6 M; mesh file
  ~63 MB per M triangles (removed at cleaning_level 3).

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
12. ~~#47-#63~~ — from the full code review of 2026-11-07.
    Evaluated 2026-11-08 and NOT done (each changes the output, so
    each would need a new baseline; measured on the user's data):
    - Repair invalid OSM water polygons (make_valid): the 90 cached
      water layers (211,251 closed ways, 11,129 relations) hold 0
      invalid polygons; 1 "Invalid OSM way" line in the log since
      2026-11-03. No benefit now. Cheap middle way if it is ever
      wanted: log the relation rings dropped silently by is_valid.
    - Empty relation member role as outer: 22 log lines since
      2026-11-03, from 2 relations (-147 Greenland, -204 Denmark) in
      ~250 tiles; an empty role is not always outer.
    - Speedups: insert_edge (~30 s of step 1's ~33 s on a cached tile)
      and blur_mask (~13 s per tile) are each ~1% of a real batch
      (the 66-tile Iceland batch: 10 h, bound by Overpass and imagery
      downloads); both would change mesh or mask bytes.
14. ~~#75, #76~~ — third pass with the config review, 2026-11-08.
15. ~~#77~~ — OSM cache check, 2026-11-11.
16. ~~#78~~ — Overpass outage of the 346-tile batch, 2026-11-11.
17. ~~#79~~ — tile window selects the last batch's leftover tiles.
18. ~~#80-#82~~ — choke points of the 346-tile batch, 2026-11-11.
    Not done: one Overpass request per tile instead of per layer
    (measure first).
19. ~~#83~~ — Overpass server order, failure kinds, shared skip of a
    dead server, 2026-11-11.
20. ~~#84-#96~~ — full code review 2026-11-11. Branches:
    fix/config-literal-eval (#84), fix/imagery-http (#85-#87, #91),
    fix/mask-cache (#88), fix/small-hygiene (#89, #90, #92; branched
    from fix/config-literal-eval: same reader code), fix/dsf-writer
    (#93; from fix/small-hygiene), fix/airport-dead-block (#94-#96).
21. ~~#97, #98~~ — the leftover custom_dem worktree finished and the
    test lint cleaned, 2026-11-11.
13. ~~#64-#74~~ — second review, 2026-11-08; #73 and #74 were the two
    items left for the user, done the same day (#73 with a new
    baseline). Noted, not changed: build_mesh's inline water
    smoothing depends on set order (see the #73 result); making it
    order-independent would change every tile with inland water.

## Coding style

- PEP 8, with comments explaining *why*, not *what*.
- Keep changes minimal and behaviour-preserving unless the change is the fix.
- Prefer `os.path`/`pathlib` over string path concatenation.
- Use the project's own `UI.vprint` / `UI.lvprint` for messages, not `print`.
