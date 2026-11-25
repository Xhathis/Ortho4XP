# Ortho4XP fork — history and full notes

Moved out of CLAUDE.md on 2026-11-25 (it had grown to 2,705 lines, loaded
into every session). Nothing was shortened here: the sections below are
the old CLAUDE.md text as it stood at docs/claude-md 48694b0. Search by
issue number ("#106") or tool name. CLAUDE.md keeps the rules, how to
test and the current state.

## Fix branches deleted (from the old Git workflow section)

- Once a fix branch is on `dev` and pushed, delete it (local and
  origin) and remove its worktree; the `--no-ff` merge commit keeps
  its name and history. The 46 merged fix branches up to #37 were
  deleted on 2026-11-05 (the commit SHAs in this file still resolve),
  fix/overpass-dangling-refs, fix/local-osm-extracts and
  fix/geofabrik-auto (#99-#101, never on origin) on 2026-11-13.
  fix/geofabrik-continent-gap, fix/stale-distance-masks,
  fix/tile-zones-kept and fix/xp-flatten-override (#120-#123, never on
  origin) on 2026-11-21, after dev 4864d7c was pushed.
  fix/xp-airport-objects (#124, never on origin) on 2026-11-21, after
  dev 22fb48e was pushed.
  fix/dsf-backup-setting and fix/earth-preview-message (#125, #126,
  never on origin) on 2026-11-24, when dev was pushed with them.
  fix/geofabrik-url-variants, fix/geofabrik-index-refresh and
  fix/geofabrik-store (#127-#129, never on origin) on 2026-11-24, when
  dev 31671af was pushed. fix/airstrip-lines, fix/geofabrik-store-
  hardening and fix/airport-pack-sweep (#130-#132, never on origin) on
  2026-11-24, when dev was pushed with them. fix/drop-fr-overpass (never
  on origin) the same day, when dev was pushed with it.
  fix/overpass-out-plain, fix/remove-unused, fix/flatten-ramp-edges,
  fix/extract-answer-leftover and fix/overlay-source-check (#133-#137,
  never on origin) on 2026-11-24, when dev fb066b2 was pushed.
  fix/dataforsyningen and fix/faroe-provider (#139, #138, never on
  origin) on 2026-11-24, when dev was pushed with them.
  fix/zone-overlap (#140, never on origin) on 2026-11-24, when dev
  dc1e423 was pushed.
  Only `master`, `dev`, `test`, `docs/claude-md` and open fix branches
  should exist.

## Testing method (full notes, as of 2026-11-25)

Unit tests: `venv\Scripts\python.exe -m pytest` (repo root, ~25 s, 769
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
Baseline (since the water smoothing fix #103, 2026-11-13):
`G:\Ortho4XP_baseline\+55+012_Arc_ZL17_test-d74d672_frozen\` — `inputs\`
(4 OSM layers of the old baseline, DEM N54-N56 E011-E013 = the user's
library .hgt files, X-Plane 12 Global Scenery +55+012.dsf, the old
baseline's Ortho4XP.cfg), `expected\` (DSF, dsf2text, 17 masks, logs),
`SHA256SUMS`, `BASELINE.txt`. Mesh 1,094,356 triangles at min_angle 10,
no WARNING. Same inputs (copied from the previous baseline, hash-checked),
older baselines: `+55+012_Arc_ZL17_test-4fa5e9f_frozen` (#73 to #102:
same mesh and masks, water altitudes of the old smoothing),
`+55+012_Arc_ZL17_test-702e768_frozen` (#32 to #72:
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
`G:\Ortho4XP_baseline` holds only the four `_frozen` baselines
(`regression.py freeze` copies from the deleted master-3cff870_cached
one: for a new baseline copy inputs\ of the current one and check it
against its SHA256SUMS, then `regression.py baseline`).
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
#78: DE and FR; KU was dead; since 2026-11-24 DE only). The failure sims replace the whole server list
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
Ortho4XP.cfg.bak): curvature_tol 0.25, limit_tris 10, mesh_zl 18 (all
three since 2026-11-11, from the mesh budget measurement in Performance
notes; were 0.5 / 5 / 19, backups of the global and all 133 tile
configs in G:\Ortho4XP_tests\cfg_backups\2026-11-11_mesh_budget),
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


## Test results and batch history

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
- 455-tile batch on `dev` 07a3f65 (started 2026-11-11 17:38, the first
  with the new mesh budget): 17 tiles (all Maldives +00..+07 / +072,
  +073, -01+073, -08+072, and +25-079) failed in step 1 with KeyError
  in update_dicosm (#99). #99 `fix/overpass-dangling-refs` @ 2794a27:
  4 new tests (3 fail on dev, the layer one with the batch's KeyError),
  469 pass, pyflakes 0; real request: FR's water answer for +02+072
  rejected naming node 29171402 (the batch's), no per-query fallback.
  `test` @ fb8c19f: 469 unit tests. After the batch, `test` @ 46e0393:
  regression PASS (DSF, 17/17 masks, app log identical), sims_in_ws
  all 15/15. → `dev` fast-forwarded to 46e0393 (not pushed).
- The 455-tile batch was killed by the user on 2026-11-13 ~07:07 (396
  built; 58 left in .last_batch_tiles.txt, 32 of them missing OSM
  layers). Cause: overpass-api.de dropped every TCP connection from
  the user's home IP (the same server answered the user's phone, "2/2
  slots available": a block of this IP, not an outage), and FR
  answered HTTP 403 ("white-listed usages" only). The batch ended
  without its cleanup, so all 396 meshes (142 GB) are still in Tiles
  (the user deletes them, or a later batch over the same tiles does).
- #100 `fix/local-osm-extracts` @ 9212bb9 (from dev 07a3f65), 2026-11-13:
  24 new unit tests (489 pass), pyflakes 0 (incl. prepare_osm_extracts.py).
  pyosmium 4.3.2 installed in the venv (user's OK). Geofabrik files in
  F:\Ortho4XP_data\OSM_extracts (11 files, 6.7 GB, MD5 checked, +
  index-v1.json). compare_extract.py (answers and caches in a scratch
  folder, ways by tags and coordinates against the user's caches):
  +68+016 (Norway, DE caches of 11-09) all 5 layers identical, the
  decompressed cache files byte-identical; +28-016 (Gran Canaria, FR
  caches with data of ~10-20) differs only by OSM edits since then.
  Norway alone: 343 s, peak 4.6 GB (the first version, all files in
  one MergeInputReader with a Python callback per node, reached 42 GB).
  sim_extract_step1.py 9212bb9 28 -18 (La Palma; Overpass replaced by a
  function that raises): build_poly_file 1, 0 Overpass calls, the 3
  answered layers read from the extract and cached; worktree clean
  afterwards. Answers prepared into the user's OSM_data for the 32
  leftover tiles that lack layers, except -08+072 (Diego Garcia: only
  asia covers it) and +07+072/+07+073 (need india/southern-zone).
  `test` @ 0d70495 (#99 + #100): 493 unit tests, pyflakes 0,
  regression PASS (DSF, 17/17 masks, app log identical), sims_in_ws
  all 15/15. → `dev` fast-forwarded to f2d3362 on 2026-11-13 (not
  pushed).
- Overpass servers checked 2026-11-13 from this PC (small aeroway query
  on Copenhagen): DE no TCP connection (IP block, see above), FR HTTP
  403 "only available to white-listed usages", overpass.kumi.systems =
  overpass.private.coffee (one server) answers a one-node query in
  80-115 s with data of 2026-05-31 (not usable), maps.mail.ru 504,
  osm.jp no connection, osm.ch Switzerland only.
- #101 `fix/geofabrik-auto` @ f2cb7d3 (6bb73cd: 403; from dev f2d3362),
  2026-11-13: 28 new unit tests (521 pass; the 2 new 403/401 cases fail
  on dev), pyflakes 0. The user's 10 extracts moved (rename on F:) from
  F:\Ortho4XP_data\OSM_extracts into OSM_data\Geofabrik with Geofabrik's
  folder layout. Real runs: region choice for 14 tiles (provinces for
  +52+004, NJ/NY/CT for +40-074, oberbayern/austria/nord-est for
  +47+011, nord-norge for +68+016, -08+072 to Overpass); --check of
  +52+004 downloaded the 3 Dutch provinces (503 MB, 62 s, MD5 ok), read
  them in 39 s and gave the same differences as the whole netherlands
  file (so the provinces hold that tile's data); vs the caches of 11-09
  and 11-11 (FR, October data) airports -453 +446 ways, 445 of them the
  same geometry with surface concrete -> asphalt (Schiphol mass edit):
  real edits. Update: a scratch copy of maldives with its header set 2
  days back got Geofabrik's 2 daily diffs through ensure_file in 1.1 s
  (header 2026-11-12 21:23, sequence 4053); a second call within the
  hour did not update. `sim_geofabrik_step1.py 46e0393 28 -18 --overlay
  G:\Ortho4XP_wt\geofabrik-auto` (new; regression worktree, no OSM data
  for the tile, Overpass and downloads raise, the user's Geofabrik
  folder read only): build_poly_file 1, all 5 layers read from the
  canary-islands extract and cached. gui_smoke against the branch's src
  7/7 (config window with the new settings; the user's
  .last_gui_params.txt, log and cfg unchanged). sim_osm_failure now
  stubs GEOFABRIK.prepare_tile, cache_roundtrip sets osm_source
  overpass (both are about Overpass). `test` @ b515416: 521 unit tests,
  regression PASS (DSF, 17/17 masks, app log identical, nothing
  downloaded: every layer of the tile is cached), sims_in_ws all 15/15
  (no Geofabrik download in any of them). → `dev` fast-forwarded to
  476f330 on 2026-11-13 (not pushed).
- Asia check 2026-11-13: of the 1° tiles Asia's outline touches, 6,922
  with land have a country/sub-region extract; only 4 land tiles are
  continent-only, all Chagos: -08+072 (Diego Garcia), -07+071, -06+071,
  -06+072. The scan used DEM.default_source_has_no_land, which downloads
  missing Viewfinder zones: 7,071 new .hgt (23.8 GB, nothing replaced)
  landed in Elevation_data; the user keeps them. Use
  DEM.world_tile_has_land for read-only land checks.
  The 4 Chagos tiles came from the main OSM API instead (user's OK):
  `G:\Ortho4XP_tests\tools\fetch_osm_api.py <out_dir> <tiles>` (4 map
  calls of 0.5 x 0.5 degrees per tile; 16 calls, 19 MB, files in
  G:\Ortho4XP_tests\osm_api\<tile>), then prepare_osm_extracts.py with
  those files and --no-coverage: all 4 OK (coastline 26/10/32/16 ways;
  -08+072's airports and big_roads were already cached, 8 runway ways).
- Fourth review 2026-11-13 (the code new since the review of 11-11:
  O4_Geofabrik, O4_OSM_Extract, prepare_osm_extracts.py; and the open
  items): #102 `fix/geofabrik-robustness` @ 0adf368 + c39d20a (11 new
  unit tests, 10 fail on dev), sim_geofabrik_step1 +28-018 with
  --overlay of the branch: all 5 layers from the extract, 0 Overpass
  calls. #103 `fix/water-smoothing-order` @ 5765e46 (3 new tests;
  measured with a scratch probe on +55+012's raw Triangle4XP output):
  regression FAIL as expected: masks 17/17 and app log identical, DSF
  differs only in altitudes (5,324,697 patch vertices, the same lon/lat
  and order; all 1,379,440 changed vertices outside terrain_Water lie
  at a terrain_Water vertex, i.e. the overlay patches over the water;
  max change 2.17 m). `test` @ d74d672: 535 unit tests, pyflakes 0; new
  baseline test-d74d672_frozen (15 inputs copied from test-4fa5e9f_frozen
  and hash-checked; DSF same hash as the 5765e46 run), repeat run PASS
  (DSF, 17/17 masks, app log identical), sims_in_ws all 15/15.
  regression.py and
  sim_batch_cleaning.py now point at it. #75 `fix/triangle4xp-steiner-
  report` @ 6d270a5 + 7ee9509 (zig installed with the user's OK, see
  #75): 4 new unit tests (2 run the exe on a synthetic 1000 m peak:
  20 points capped -> "left: 0", 49 nodes; uncapped 48 used, 77 nodes;
  both fail with the old exe), meshes identical to the old exe at 9
  option sets. `test` @ fcf243d: 539 unit tests, regression PASS (DSF,
  17/17 masks, app log identical: not capped at the regression cfg,
  986,227 left); probe_mesh --skip-step1 curvature_tol=0.25
  limit_tris=1 in the worktree: "Steiner points left: 0" and the NOTE
  in the log; sims_in_ws all 15/15 (sim_mesh_failure through
  _run_triangle4xp).
- 58-tile batch on `dev` 75ae9dc (the 455-tile batch's leftovers,
  2026-11-13 18:04-23:16, 3 parallel): 46 built, 12 failed only in the
  overlay step (ortho DSFs complete and activated): the user's X-Plane
  Global Scenery lacks +44..+46 / -122..-125 (Oregon, land: an
  incomplete install, the user repairs it; the tiles were built without
  XP12 rasters, rebuild step 3 + overlay afterwards) and +37-025 (Azores,
  open ocean: X-Plane has no DSF there). No Overpass request: all
  layers cached or from Geofabrik (southern-zone 560 MB in 164 s for
  +07+072/+07+073). Median per tile: step 1 0.3 min, 2 0.9, 2.5 2.4,
  3 3.1 (max 62.5, imagery). The #75 NOTE fired on 25 tiles: +69/+70
  018-026 (14), the 8 Oregon tiles with land, +51+004, +51+006,
  +52+004. No cleanup: the user's cfg was saved from the GUI at 17:59
  with cleaning_level 0 (only change, .bak has 3), so all 58 meshes and
  the Triangle4XP intermediates stayed (Tiles: 72 GB of them).
  On 2026-11-14 cleaning_level set back to 3 and osm_cache_max_age=30.0
  added in the user's cfg (the user set 2.0 and limit_tris 40 from the
  GUI at 09:16 the same day) (user's OK; the state before both in
  Ortho4XP.cfg.before-cache-refresh.bak). The 72 GB stay until the
  user deletes them or a batch at level 3 rebuilds those tiles.
- #104 `fix/osm-cache-refresh` @ 656ef6d (from dev dea8931): 9 new unit
  tests (548 pass; 8 fail on dev, the 9th checks an answer older than
  the cache is ignored, as on dev), pyflakes 0, regression PASS (DSF,
  17/17 masks, app log identical), sims_in_ws all 15/15. `test` @
  88fdc66: 548 unit tests.
- #105 `fix/overlay-no-source-dsf` @ 8ec2a50 (from dev dea8931): 3 new
  unit tests (1 fails on dev; unset source and a source without Earth
  nav data stay errors, as on dev), pyflakes 0, regression PASS (DSF,
  17/17 masks, app log identical), sim_overlay 8/8 (new case "no DSF
  for the tile": return 1, overlay untouched; "missing source" with a
  folder that does not exist stays 0). Against the real Global Scenery
  (read only): +37-025 and +46-122 return 1 with the WARNING. `test`
  @ 8f33c4a (#104 + #105): 551 unit tests.
- 440-tile batch on `dev` 8171256 (2026-11-14 10:27 to 11-15 13:03,
  26h36m, 3 parallel, limit_tris 40 in the global cfg and 435 tile
  configs; the user's cfg saved from the GUI 11-14 09:16 with
  osm_cache_max_age=2.0, not 30, so nearly every cache was refreshed
  from Geofabrik): 435 built, 5 failed. +35-006, +53+008, +53+009,
  +69+030: coastline not closed, from #106 (9 more tiles built without
  the dropped land, see #106). +67+017: worker exit 0xC0000005 while
  cleaning the water layer (Akkajaure); the same cleaning on the same
  cache ran twice without error in a probe, so a one-off. No Overpass
  request. 25 NOTE tiles (budget used: southern Norway +58..+61 /
  +005..+009, BC/Washington coast); of the 25 NOTE tiles of 11-13 only
  +45-124 still. New DSFs: 84 GB, median 125 MB, p90 507 MB, max 660
  MB (+59+006, ~44 M triangles). The 12 overlay WARNINGs (#105) are
  the Oregon tiles and +37-025: X-Plane keeps +44..+46 / -122..-125 in
  Global Scenery\X-Plane 12 Demo Areas (Portland demo area), not in
  X-Plane 12 Global Scenery; custom_overlay_src_alternate (empty in the
  user's cfg) is read by step 3 and step 4 when the main source lacks
  a tile, so setting it to that folder fixes them.
- #106 `fix/geofabrik-enclaves` @ 8bff0d3 (from dev 8171256): 2 new
  unit tests and test_containers changed (all 3 fail on dev; fixtures
  of alps and netherlands made realistic: composites cover >= 0.25 of
  their outline), 553 pass, pyflakes 0, regression --overlay PASS (DSF,
  17/17 masks, app log identical), sim_geofabrik_step1 +28-018 0
  failures. World scan (51,001 tiles any country region touches, old
  vs new rule on the real index): 521 change, nearly all adding land
  (NW Russia 170, Ukraine 64, NSW 53, Portugal 40, Nusa Tenggara 39,
  Hebei 37, Morocco 35, Guangdong 29, Niedersachsen 16, PACA 11,
  Brandenburg 11, ...); some only add sea and a bigger read (Azores
  tiles read portugal 428 MB instead of azores 18 MB; Crimea tiles
  ukraine; Svalbard tiles northwestern-fed-district). `test` @ 810fc3a:
  553 unit tests.
  The 13 tiles re-prepared with the fix (dev's prepare_osm_extracts.py,
  the fix's src first on sys.path, --force; 2026-11-15, 850 s;
  downloaded morocco 245 MB, northwestern-fed-district 658 MB): all OK,
  0 left to Overpass; the answers are much larger than the broken caches
  (+35-006 small_roads 0.25 -> 10.5 MB bz2, +53+008 2.0 -> 9.3 MB) and
  newer, so step 1 replaces the caches (#104). Rebuild them from step 1.
  limit_tris 40 was too much: the user killed X-Plane's loading at ENVE
  (Valle, +59+007, 656 MB DSF, next to +59+006 660 MB, +59+008,
  +58+006/7 > 600 MB) after 10 min. On 2026-11-15 limit_tris=10.0 set
  in the global cfg and all 449 tile configs (user's choice; only that
  line changed, checked against the backup with SHA256SUMS in
  G:\Ortho4XP_tests\cfg_backups\2026-11-15_limit_tris, which also
  holds the old .last_batch_tiles.txt). The user's cfg also has
  custom_overlay_src_alternate = ...\X-Plane 12 Demo Areas and
  osm_cache_max_age 30 again (user, 13:57). .last_batch_tiles.txt now
  lists 212 tiles to rebuild from step 1 (cleaning_level 3 removed step
  1's files): the 204 with a DSF over 150 MB (about where limit_tris 10
  caps) plus the 13 #106 tiles, +67+017 and the old leftovers.
- That rebuild (started 2026-11-15 14:29, override with the global cfg:
  the user set road_level=5 there and in 435 tile configs at 14:25)
  showed #107: +53+008, +53+009, +69+030 kept their pre-#106
  small_roads cache (the answers prepared that morning were for level
  4). #107 `fix/road-level-cache` @ 8ee37b5 (from dev 1358d0c): 5 new
  unit tests (all fail on dev), 558 pass, pyflakes 0. Read-only scan of
  the user's 460 small_roads caches at level 5 (71 s, max 2.4 s per
  tile): 347 fit (made at level 5 before), 113 lack tracks; of the
  batch's 229 tiles 33 lack them. `test` @ dc04261: 558 unit tests.
  Not run yet (the batch was running): regression. Rebuild list
  G:\Ortho4XP_tests\batches\rebuild_road_level5.txt: those 33 plus the
  3 tiles above (prepare_osm_extracts.py --force --road-level 5 first:
  their caches fit level 5 but predate #106).
- The 229-tile rebuild ended 2026-11-16 02:43 (12h11m): 229 built, 0
  failed, no ERROR; the 3 "extract answer ... made for other queries"
  WARNINGs were +53+008/+53+009/+69+030 (#107 on test, not yet on dev);
  202 limit_tris NOTE tiles; no overlay WARNING (Demo Areas as
  alternate source); no mesh left, 5 meshes of earlier batches removed.
  `test` @ ac92157 (#107): regression PASS (DSF, 17/17 masks, app log
  identical), sim_geofabrik_step1 +28-018 0 failures. The 3 tiles
  re-prepared (--tiles ... --road-level 5 --force, 240 s, 0 left to
  Overpass). -> `dev` fast-forwarded to ac92157 and pushed (user's OK);
  .last_batch_tiles.txt set to the 36 tiles of rebuild_road_level5.txt.
- Pre-batch review 2026-11-16 (before batches A/B/C, read-only checks of
  the lists G:\Ortho4XP_tests\batches\batch_a_zl16_all.txt (335),
  batch_b_zl15_greenland_arctic.txt (109), batch_c_zl16_south_germany.txt
  (21)): all covered by Geofabrik (0 tiles to Overpass; A needs 66
  extracts not on disk, B 2, C 25), no tile folder or tile config yet,
  B and C have all .hgt, 86 land tiles of A get Viewfinder in step 1,
  15 tiles have no X-Plane DSF (13 in B north of 76 N, +28-179,
  -45+166: overlay WARNING only). Found #108-#111; #112 asked for by the
  user. Each `fix/<name>` from dev ac92157: #108 + #110
  `fix/tile-lists` @ fa43db9, 312dd8d; #109 `fix/mask-zl` @ 71831b9;
  #111 `fix/temp-leftovers` @ 09adf2c; #112 `fix/imagery-gate` @
  7127c49. 31 new unit tests (the #108, #110 ones fail on dev; the old
  prepare tool test now passes --road-level 3 for "nothing to do").
  #109 real check (scratchpad zl15_masks.py, cwd regression worktree,
  its mesh copied, downloads skipped): +55+012 steps 2.5-3 at ZL15,
  mask_zl 16: dev 100 masks at ZL16, 104 terrains, 50 masked (airports
  only); fixed 40 masks at ZL15, 142 terrains, 88 masked. #110: the
  fixed script's dry run of the rebuild list finds the 33 small_roads
  layers (dev: 0). #112 probe against real servers: GO2 +72-040 ZL15,
  GO2 and Arc +55+012 answer in 0.3-0.6 s; a closed port False in 2 s.
  `test` @ 01fccc9: 589 unit tests, pyflakes 0, regression PASS (DSF,
  17/17 masks, app log identical), sims_in_ws all 15/15. Not run:
  gui_smoke, test_parallel_batch, a real imagery outage.
- Batches reordered 2026-11-16 into pilots before the big runs
  (G:\Ortho4XP_tests\batches: pilot_zl16.txt = the 36 road_level 5
  tiles + 16 samples of A and C, pilot_zl15.txt = 6 of B, and
  batch_a_zl16_rest (322), batch_b_zl15_rest (103), batch_c_zl16_rest
  (18) without them). ZL16 pilot on `dev` 7b84bf4 (16:33-19:29, 2h56m):
  51 built, +47+011 failed in step 1 (#113); 36 small_roads refreshes
  (the 33 + the 3 #106 tiles, which also refreshed their other layers),
  no "made for other queries" WARNING, overlay WARNINGs only -45+166 and
  +28-179 (no X-Plane DSF), 31 limit_tris NOTEs, DSFs <= 177 MB. +48+011
  was built with a zero south and east margin (#113): rebuild it with
  +47+011 (its mesh is kept for that).
  #113 `fix/hgt-fine-grid` @ 7852e1c (from dev 7b84bf4): 10 new unit
  tests (9 fail on dev), 599 pass, pyflakes 0, regression PASS (DSF,
  17/17 masks, app log identical), sim_dem_failure 10/10 (case E now
  expects a 1/3" grid to build; new E2: a 5000 grid still raises).
  Real combined raster (read only): +47+011 builds, its centre equals
  N47E011.hgt[::2, ::2]; +48+011's south seam 0.8 m (dev: 604.6 m).
  Batch A, B and the ZL15 pilot touch none of the 33 files; batch C
  has 5 tiles on them and 8 next to them.
- ZL15 pilot on `dev` 0d57def (2026-11-16 20:04-20:51): 6 built, 0
  failed; #109 NOTE on every tile, masks at ZL15 (file names in ZL15
  tile numbers), tile configs mask_zl 15, masked terrains on all
  (+64-052 204 of 338); overlay WARNINGs only +76-069, +82-063 (no
  X-Plane DSF). +82-063's DSF is 2.6 MB: half sea, Viewfinder's land
  there is very smooth (median neighbour step 0 m), not a bug. `dev`
  0d57def (#113) pushed, fix/hgt-fine-grid removed. batch_c_zl16_rest
  now starts with +47+011, +48+011 (20 tiles).
  #114 `fix/geofabrik-failed-once` @ f52f33e (from dev 0d57def): 3 new
  unit tests (2 fail on dev; the third checks the next preparation tries
  again, as on dev), 602 pass, pyflakes 0, regression PASS (DSF, 17/17
  masks, app log identical), sim_geofabrik_step1 +28-018 0 failures.
- Batch A on `dev` 9a9a0b0 (322 tiles, started 2026-11-16 21:30): Geofabrik
  preparation 21:30-23:41, one request at a time, all 322 prepared, no
  failure (#114 never acted); phase 1 done for all by 2026-11-17 07:00.
  ENVE (+59+007) rebuilt at limit_tris 10 loads in X-Plane at ~55 fps (it
  hung at 40). Greenland: batch_d_zl15_greenland_extra.txt (18 tiles with
  OSM airstrips/helipads not in apt.dat) and batch_bd_zl15_greenland.txt
  (B + D + +64-052, 122 tiles) in G:\Ortho4XP_tests\batches.
  Nuuk walls (user's screenshots, ZL15 pilot): X-Plane's apt.dat has
  "1302 flatten 1" for BGGH (282 ft), the DEM (N64W052.hgt, 2020) predates
  the new runway, 18-107 m inside the boundary. Hand patch
  Patches/+64-052/BGGH.patch.osm (apt.dat boundary, cst_alt_abs 85.95;
  in the user's checkout, not committed), then #115. Read-only scan of the
  933 built/queued tiles: 46 flatten airports, ~20 with steps >= 15 m
  (AYPY 100 up, HECA 87 down, BGGH, Western Sydney, EKVG, GCFV,
  Qaqortoq, KEGE, LCEN, GCTS, EBBX, ...).
  #115 `fix/xp-flatten-airports` @ f6c4468 (from dev 9a9a0b0): 10 new unit
  tests (all fail on dev: new module), 612 pass, pyflakes 0. Real apt.dat
  index (scratch Tmp_dir): 647 airports, 2.6 s, 419 KB, all 46 of the
  scan; BGGH 0.891 km2 at 85.95 m. Step 1 of +64-052 in a scratch cwd
  (cached OSM and DEM copied, no network): on: 43 nodes at 85.95 m, OSM
  runway of BGGH not levelled, the log line; off: 0 such nodes, as dev.
  After batch A (2026-11-18): regression PASS (DSF, 17/17 masks, app log
  identical; console "apt.dat not found": the frozen GlobalScenery copy
  has no Global Airports next to it), sims_in_ws all 15/15, gui_smoke
  7/7 against the branch's src (136 tiles on the map; .last_gui_params,
  log, cfg hash-checked), steps 1-2 of +64-052 in the scratch cwd
  (scratchpad step2_flatten.py): on: 79 mesh vertices inside BGGH's
  boundary, all 85.95 m; off: 1,462, 26.9-101.6 m.
- Batch A on `dev` 9a9a0b0 (322 tiles, 2026-11-16 23:41 to 11-18 13:03,
  37h22m): 322 built, 0 failed, no ERROR; 156 limit_tris NOTEs; 3 tiles
  recorded as sea (S11E159, S11E160, N07E133); one WARNING: +23-167's
  neighbour N24W168 (Gardner Pinnacles, flagged land in world_tiles.png)
  has no Viewfinder archive (G03: dem1 404, no dem3), a zone without any
  archive is not recorded as sea (#40), margin 0 m = sea level: fine.
- After batch A: tag `batch-ready-2026-11` on dev b718fc7 (pushed); 44
  tiles with flatten airports rebuilt (2026-11-18 14:49-16:01, 44 built).
- Batch B+D on `dev` b718fc7 (369 tiles: B+D's 122 plus the user's
  additions, GO2 ZL15, started 2026-11-18 16:20): by 2026-11-19 17:30
  363 built, 2 open sea (+72-073, +72-074), +79-069 and +79-071 failed
  after 3 imagery tries, +79-070 and +82-039 held by the #112 pause
  since 15:52 (#116). No other ERROR; 272 limit_tris NOTEs.
  #116 `fix/imagery-no-data` @ edfff84 (from dev b718fc7): 16 new unit
  tests (15 fail on dev, 1 by behaviour), 628 pass, pyflakes 0;
  regression --overlay PASS (DSF, 17/17 masks, app log identical);
  sims_in_ws all 15/15; real downloads of the white textures
  3920_10032 (+79-070), 3920_10000 (+79-071) and 19296_103392_GO218
  (+82-039): complete, cut from ZL9 / ZL9 / ZL12.
  #117 `fix/imagery-fallback` @ d61e178 (from #116): 12 new unit tests,
  640 pass, pyflakes 0; regression --overlay PASS, sims_in_ws all
  15/15; real: +82-039's texture from BI, two +70-076 textures from Arc
  (sharp lakes and river braids where the built GO2 DDS is coarse
  blocks with a faint Google watermark). Sample of 150 built textures
  per ZL (GO2 drop levels at the middle piece): ZL15 (Arctic) 41 drop
  1-5 levels, Arc has the full level for 33; ZL16 4 of 150; ZL18 5 of
  150. `test` @ 5f96c6d (#116 + #117): 640 unit tests, pyflakes 0.
  Not run: gui_smoke (the user's batch GUI was open in G:\Ortho4XP).
- Batch B+D ended 2026-11-19 22:58 (30h38m): 363 built, 2 open sea, 4
  failed in step 3 (imagery: +79-069/070/071, +82-039). `dev`
  fast-forwarded to 92ead0f (#116, #117) and pushed. Step 3 + overlay of
  the 4 on dev (scratchpad script calling build_tile_list, 23:35, 21m35s):
  4 built; the three +79 tiles partly cut from ZL9 (neither Arc nor BI
  has ZL15 there, NOTE), +82-039's 304 textures filled from BI; no
  overlay (no X-Plane DSF north of ~76 N, WARNING); the batch then
  removed the 12 meshes kept next to them.
- Batch C on `dev` 92ead0f (20 tiles, GO2 ZL16, started 2026-11-19
  23:57 from a script, the GUI closed): Geofabrik answered 404 for the
  .md5 of alsace and jihocesky (#118), so 18 tiles went to Overpass
  (DE 429/502/timeouts, FR 403: no answer); 5 built, 10 meshed and held
  by the neighbour barrier (#82) behind 6 held in the Overpass pause.
  Stopped 2026-11-20 ~07:00. #118 `fix/geofabrik-layout` @ 704ce67
  (from dev 92ead0f): 10 new unit tests (9 fail on dev; the 503 one
  passes there too), 651 pass, pyflakes 0; regression --overlay PASS
  (DSF, 17/17 masks, app log identical); sim_geofabrik_step1 +28-018 0
  failures; all 554 regions give the same local path from the old index,
  the new one and dev's rule (152 extracts on disk found); 9 extracts
  downloaded with the fix (alsace 132 MB, jihocesky 97 MB, hessen,
  champagne-ardenne, oberfranken, 4 BW Regierungsbezirke; MD5 of the
  dated files). `test` @ dce73b3: 651 unit tests. Batch C restarted on
  dev 92ead0f with its 15 unfinished tiles (all extracts on disk).
- Batches 2026-11-20/21 on dev 98fddee (GUI): 215 road_level 5 /
  flatten rebuilds (4h52m), 218 ZL15 tiles after deleting the 10,811 GO2
  gap textures (zl15_arc_prepare.py, 130 GB; 11h23m: Arc pieces in 165
  tiles, BI in 59), 10 continent-only island tiles from central-america
  (795 MB, downloaded with the user's OK) and the OSM API: all built, 0
  failed. Full tile audit 2026-11-21 (G:\Ortho4XP_tests\batches\
  evaluation_2026-11-21.md): found #120 and #121; 20 tiles to rebuild
  (rebuild_audit_2026-11-21.txt, answers prepared) plus 14 Canadian
  tiles of the +61/+62 rows raised to ZL16 in their tile configs (user's
  OK; backups in cfg_backups\2026-11-21_canada_zl16; GO2 has real ZL16
  there, 2x the fine detail of ZL15). #120 `fix/geofabrik-continent-gap`
  @ 353446d and #121 `fix/stale-distance-masks` @ 03c3c5d (from dev
  98fddee): 6 new unit tests (all fail on dev), pyflakes 0, regression
  PASS for both (DSF, 17/17 masks, app log identical),
  sim_geofabrik_step1 +28-018 0 failures; #120 against the real index
  and the user's .hgt files: of 1,178 tiles exactly the 19 Caribbean
  ones change (all read central-america). `test` @ 2351a5e: 661 unit
  tests. Nuuk (+64-052) after #119: mesh flat at 85.95 m inside the
  boundary, slopes up to 44 deg within 25 m outside; GO2's imagery is
  from the construction (old runway only), BI has the finished runway,
  Arc has nothing there (2521-byte answers at ZL15-18).
  Nuuk BI zone (user's OK): +64-052's tile config zone_list = BI at ZL15
  over lat 64.145-64.240 / lon -51.772..-51.587 (all 45 ZL18 airport
  cover textures of the last build inside; the cover raises them to BI
  ZL18; BI ZL18 probed 121/121 real images; backup in
  cfg_backups\2026-11-21_nuuk_bi_zone); +64-052 added to the batch list
  (35 tiles). The batch must run without the global-cfg override (the
  zone and the Canadian ZL16 are tile settings). Found #122 on the way:
  `fix/tile-zones-kept` @ 57966d9 (from dev 98fddee): 2 new unit tests
  (both fail on dev), pyflakes 0. `test` @ 5000800: 663 unit tests,
  regression PASS (DSF, 17/17 masks, app log identical).
- The 35-tile rebuild (2026-11-21 14:00-15:35, GUI batch on dev 98fddee):
  35 built, 0 failed, no ERROR or WARNING; all 100 OSM layers of the 20
  audit tiles refreshed from the extracts. DSFs decoded: the islands are
  land again (water / land patch vertices, old -> new: +15-062 9.36 M /
  1.74 M -> 0.52 M / 11.27 M; +21-072 0 / 0.78 M -> 0.80 M / 1.55 M;
  +16-063 and +17-064 had no water, now 0.11 M and 0.09 M). Nuuk: 45
  BI18 + 2 BI15 textures, all used by the DSF; step 3 erased the zone line
  (#122 not yet on dev), put back by hand. The 14 Canadian tiles GO216
  (GO218 at airports; 726 textures with Arc pieces). No unused or missing
  .dds/.ter in the 35 tiles. -> `dev` fast-forwarded to bf6f064 (#120,
  #121, #122) on 2026-11-21 (not pushed); 663 unit tests, pyflakes 0.
- Nuuk walls after the rebuild (user's screenshots, 2026-11-21): the sea
  raised to runway height with straight edges, hills cut by straight walls.
  The DSF has none of it (decoded: no steep or tall triangle within 600 m
  of BGGH's boundary, slope map); the only base mesh for +64-052 is ours
  (the 6 other packs are overlays); no raster-elevated vertex. A pack with
  BGGH's gateway block minus "1302 flatten 1" (the user copied it into
  Custom Scenery, X-Plane put it above *GLOBAL_AIRPORTS*; a first try by
  editing scenery_packs.ini was lost, Log.txt showed it not loaded): the
  walls were gone. So X-Plane's flatten covers far more than the boundary
  and overrides the DSF: #123. `fix/xp-flatten-override` @ 9677a01 (from
  dev b5300b0): 8 new unit tests (all fail on dev), pyflakes 0, real step
  1 of +64-052 writes ["BGGH"] (setting off: no marker). Markers seeded for
  the user's 49 tiles with a flatten airport (all DSFs after #119 reached
  dev, 2026-11-20 13:37:32; marker mtime = DSF mtime - 1 s), pack written:
  52 airports in G:\Ortho4XP\yOrtho4XP_Airports (XED002S left out: reaches
  the unbuilt +50+006). `test` @ a0aafa0: 671 unit tests, regression PASS
  (DSF, 17/17 masks, app log identical: the frozen inputs have no
  apt.dat). The user links the pack into Custom Scenery above Global
  Airports and removes the BGGH_no_flatten test pack. -> `dev`
  fast-forwarded to 5ad0b07 on 2026-11-21 (not pushed): 671 unit tests,
  pyflakes 0. The user linked the pack (yOrtho4XP_Airports.lnk) and
  removed the test pack; X-Plane's Log.txt (17:08) loads it as pack 152,
  right above Global Airports (153), no APT error for its airports.
- The user found Nuuk's airport buildings gone with the pack (2026-11-21):
  Global Airports' +64-052.dsf holds BGGH's 3D (236 objects, 200
  polygons/facades) behind "sim/filter/aptid BGGH", which X-Plane draws
  only while BGGH comes from Global Airports. All 52 pack airports were
  affected: #124. `fix/xp-airport-objects` @ 4f00a6c (from dev 4f24899):
  30 new unit tests (new functions), 701 pass, pyflakes 0. All 7,077
  Global Airports DSFs read and rewritten with every filter kept come out
  byte-identical (the command parser's check). Real pack in a scratch
  folder (user's apt.dat and Tiles read only, 5.7 s): 48 DSFs, 6.9 MB, all
  52 airports with 3D (BGGH 436 commands); 46 decode with DSFTool to
  exactly the source's blocks and exclusions of those airports; the other
  2 (+47-123, +51+006) crash DSFTool 2.4.0 already as sources (also with
  a 64 MB stack), their per-airport command counts match. Regression PASS
  (DSF, 17/17 masks, app log identical). `test` @ 1cbeae0: 701 unit tests.
  -> `dev` fast-forwarded to 9287de3 on 2026-11-21 (not pushed); the
  user's pack rewritten from G:\Ortho4XP (XPAPT.update_override_pack with
  the cfg's two overlay sources; the #123 apt.dat and stamp backed up in
  G:\Ortho4XP_tests\cfg_backups\2026-11-21_airport_pack_123): apt.dat
  unchanged, 48 DSFs byte-identical to the verified scratch pack. After
  an X-Plane restart the user saw Nuuk's buildings back (2026-11-21).
- 296-tile batch on `dev` 20ddc44 (GUI, 2026-11-21 20:52): the PC shut
  down 23:29 in phase 1; the user restarted the 279 leftover tiles
  2026-11-22 09:27 (38h41m): 279 built, 0 failed, no ERROR, only the 60
  "erroneous tag marked aerodrome" WARNINGs; 144 limit_tris NOTEs, 192
  tiles with Arc pieces and 1 with BI (#117); airport pack 69 airports,
  65 DSFs. -10/-09/-08/-07/-03+141 went to Overpass: Geofabrik redirects
  asia/indonesia/papua-latest.osm.pbf to /indonesia/papua/... (no
  "asia/", 404; Geofabrik's error), Overpass then answered. The 8 meshes
  of -55-064..-066, -56-067..-071 (built before the shutdown, 1.9 GB)
  stayed: the restart cleans only next to tiles it built (#45).
  #125 `fix/dsf-backup-setting` @ dc94fa8 and #126
  `fix/earth-preview-message` @ d13dea8 (from dev 20ddc44): 13 new unit
  tests, pyflakes 0, regression --overlay of #125 PASS. `test` @
  54f392e: 714 unit tests, pyflakes 0, regression PASS (DSF, 17/17
  masks, app log identical). Not run: gui_smoke.
  -> `dev` fast-forwarded to test (with these notes) on 2026-11-24
  and pushed; both fix branches removed.
- #127 `fix/geofabrik-url-variants` @ 05e4420 and #128
  `fix/geofabrik-index-refresh` @ efb2238 (from #127), 2026-11-24: 19 new
  unit tests (#127 12, #128 7), 733 pass, pyflakes 0; regression --overlay
  PASS for both (DSF, 17/17 masks, app log identical), sim_geofabrik_step1
  +28-018 0 failures for both. Real: papua's new URL downloaded (36 MB, MD5
  of the dated file); a scratch index 2 days old naming a gone papua URL
  fetched the live index and downloaded the file from the URL it gives.
  Geofabrik's papua redirect was fixed again by then (checked 11-24).
  `test` @ 9664414: 733 unit tests.
- #129 `fix/geofabrik-store` @ adef5de (from #128), 2026-11-24: 20 new
  unit tests (tests/test_geofabrik_store.py), 753 pass, pyflakes 0;
  regression --overlay PASS (DSF, 17/17 masks, app log identical).
  sim_geofabrik_step1.py has --geofabrik-dir <dir> (from #129 on, a
  preparation moves old-layout files: never let the sim use the user's
  folder): +28-018 on a scratch copy of canary-islands in the old layout
  moved it into extracts\ and read all 5 layers from it. `--store
  --dry-run` on the user's folder: 164 files (38.0 GB) would move, 0 left,
  nothing written. Real updates of the scratch extract through its header
  server (80 s, then 1 s with nothing new) recorded in the manifest.
  pyosmium-up-to-date with --server and --ignore-osmosis-headers fetched
  the changes in 3 s and then did not exit in 400 s: not used. Scratch
  folder G:\Ortho4XP_tests\geofabrik_store_scratch. `test` @ 76f67c4: 753
  unit tests, pyflakes 0. The first preparation with #129 moves the
  user's 164 extracts into the store, and older code would then download
  all 38 GB again: do not run code older than #129 from G:\Ortho4XP.
  -> `dev` fast-forwarded to test (#127-#129, with these notes) on
  2026-11-24 and pushed; the three fix branches removed. The same day
  `prepare_osm_extracts.py --store` on dev moved the user's 164 extracts
  (38.0 GB) into OSM_data\Geofabrik\extracts (moved_20261124_073819.csv;
  sizes equal to a listing taken before, manifest 164 regions, 66 with
  the old .checked time); the old folders and their .checked/.lock files
  are gone (an orphan papua .lock from the 404 of 11-21 removed by hand).
  A dry run of 5 tiles plans only files in the store.
- Unattended pass 2026-11-24 (user away, no GUI): log scan (the aerodrome
  WARNING of every batch: #130), a profile of step 2.5 on +55+012 (15 s,
  numpy correlate in blur_mask; 45 % of the mask rows repeat, but no
  speedup keeps the mask bytes: left), a review of the code since 11-21
  (#123-#129: #131, #132). #130 `fix/airstrip-lines` @ 8de0398, #131
  `fix/geofabrik-store-hardening` @ 875fac0, #132 `fix/airport-pack-sweep`
  @ fb9f810 (from dev c9abc9c): 16 new unit tests (6 + 8 + 2; 14 fail
  on dev; the airstrip-area and old-form CSV ones pass there),
  pyflakes 0. #130: airports of the
  cached layers, dev vs fix: -36+174 92 -> 94 airports and 4 -> 0
  WARNINGs, +57-066 0 -> 1, +55+012 unchanged; 27 of the user's 1,474
  tiles hold 81 airstrip lines (-39+175 22, -39+174 8, ...). #131 against
  the user's store (read only): nothing left to move, no orphan side file.
  `test` @ c801b49: 769 unit tests, pyflakes 0, regression PASS (DSF,
  17/17 masks, app log identical), sims_in_ws all 15/15,
  sim_geofabrik_step1 +28-018 --geofabrik-dir (a scratch store with a
  copy of the user's canary-islands) 0 failures, all 5 layers from it.
  -> `dev` fast-forwarded to test (with these notes) on 2026-11-24 and
  pushed; the three fix branches removed.
- Overpass checked again 2026-11-24 (one runway query on Copenhagen,
  plain requests, no health file): DE HTTP 200 in 55 s with data a
  minute old (the IP block of 11-13 is gone; the server is slow), FR
  HTTP 403 "white-listed usages" as since 11-13. `fix/drop-fr-overpass`
  @ 49cc006 removes FR from overpass_servers.txt (user's choice): a
  request now tries DE twice and stops; the GUI's server choice lists
  DE only. `test` @ 114085a: 769 unit tests, pyflakes 0 (the tests and
  sims use their own mock server lists). -> `dev` on 2026-11-24, pushed.
- Fifth review 2026-11-24 (user remote; the code of #104-#132, the repo
  for dead files, and the Overpass request): #133
  `fix/overpass-out-plain` @ 1dd075d, #134 `fix/flatten-ramp-edges` @
  7491702, #135 `fix/extract-answer-leftover` @ 5100866, #136
  `fix/overlay-source-check` @ 3692e9d, #137 `fix/remove-unused` @
  1f73d0c (from dev 6a1669a): 8 new unit tests, pyflakes 0. Overpass
  dependence of the user's tiles (read only, plan_tiles against the
  index and the store): only -08+072 (Diego Garcia) still needs it.
  `test` @ f66f37f: 777 unit tests, regression PASS (DSF, 17/17 masks,
  app log identical: the frozen inputs have no apt.dat, so #134 does
  not act there), sims_in_ws all 15/15.
- Imagery audit 2026-11-24 (user's request: Denmark and the Faroes
  overall, Greenland at every airport, airstrip and helipad; scratch
  comparisons 4 x 4 tiles at ZL16 and ZL18 of GO2, Arc, BI and the
  national sources). Denmark (26 tiles, GO2 ZL16, ZL18 airports): GO2 is
  the sharpest and nearest to true ortho at 9 of 10 sites (Kastrup,
  Copenhagen, Billund, Aalborg, Aarhus, Silkeborg, Rønne, Odense,
  Esbjerg; Skagen hazy); Arc leans and smears in towns, BI is close
  but softer. The better source is Klimadatastyrelsen's own orthophoto
  (Dataforsyningen, orto_foraar, 12.5 cm, yearly): it needs a personal
  token (free account, the user's to create); Providers/Denmark/DK.lay
  still names the closed kortforsyningen.kms.dk; with the user's token
  (orto_foraar of orto_foraar_DAF, 2026 spring flight) it is newer and
  consistent, much better at Skagen, but leafless and cooler than GO2's
  summer look: the user's choice (a token never goes into git); the
  user chose it: #139, 23 tile configs on DFA. Faroes (3 tiles, GO2
  ZL16, Vágar ZL18): #138. Greenland (106 OSM / X-Plane airports,
  airstrips and helipads): Arc is TerraColor 15 m there; GO2 is best at
  most sites, BI at 17 (GO2 spring snow around Disko Bay and Maniitsoq,
  older than a new helipad, or coarse); only the 24 sites at OSM
  aerodromes with runways have ZL18, the other 82 are ZL15. Proposal: 81
  ZL18 zones in 43 tile configs (G:\Ortho4XP_tests\imagery_audit_2026-11-24:
  report, gl_zones.py dry run / --apply with backups, sheets), applied
  2026-11-24 with the user's OK (backup cfg_backups\2026-11-24_gl_zones);
  those tiles then need steps 1-3 (their .apt files are gone at
  cleaning_level 3, so step 3 alone would drop the airport covers).

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
    limit_tris 5: -S 2,515,274, 2,074,524 added, no WARNING ("Maximum
    number of bad triangles: 4,190,967" in the -V statistics is the
    largest the queue ever was, not what was left); uncapped the same tile needs 10.08
    M triangles. An uncapped 1.0 mesh used 78 % of its -S, so the
    vertex count cannot tell capped from not; where the budget goes is
    not found (only 2.42 M circumcenters computed). A fix needs
    Triangle4XP to report steinerleft (rebuild the exe) or another
    signal. Also the "~1.9 M triangles" above was wrong: DSFs hold ~15
    bytes per triangle (+65-019: 60 MB, 4.12 M), so 67 MB is ~4.5 M:
    the user's largest tiles were at the cap.
    **FIXED 2026-11-13** (`6d270a5` exe, `7ee9509`): the budget goes to
    vertices Chew's refinement deletes again: splitencsegs removes free
    vertices from the diametral circle of a segment it splits
    (deletevertex), and their -S budget stays spent (instrumented build,
    +55+012 at -S 200000: 135,761 segment splits + 64,239 circumcenters
    = 200,000 spent, 17,556 deleted, 182,444 added, 0 left).
    Triangle4XP.c now prints "Steiner points left: N" after the
    refinement (also with -Q); build_mesh reads it (_run_triangle4xp,
    parse_steiner_left) and logs, at 0, "NOTE: Triangle4XP used the
    whole limit_tris budget of tile ... coarser than curvature_tol ..."
    (a NOTE: the user's ct 0.25 / limit_tris 10 use the cap as a budget
    on purpose). Exes without the line (Linux, macOS: not rebuilt) keep
    the old count test. Utils\win\Triangle4XP.exe was rebuilt with zig
    cc 0.17.1 (`G:\Ortho4XP_tests\tools\zigenv`, PyPI ziglang, user's
    OK; `zigenv\Scripts\python.exe -m ziglang cc -O2 -target
    x86_64-windows-gnu -mcpu=baseline -ffp-contract=off
    -fno-strict-aliasing -w -Wl,--stack,268435456 -o Triangle4XP.exe
    Triangle4XP.c`, then `pe_stack.py <exe> 256 <out>` for the PE
    checksum). Upstream's exe came from mingw-w64 gcc; on +55+012 at 9
    option sets (min_angle 0-20, curvature_tol 0.25-4, capped or not)
    the old exe, the unchanged source and the patched source built this
    way give identical .1.node/.1.ele (comment lines aside). Note: when
    the budget is exactly enough, the report says 0 too (seen on a test
    tile with 20 points needed).
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
99. **FIXED** (`2794a27`): with overpass-api.de down (2026-11-11 from
    ~17:40), FR answered with ways naming nodes deleted from OSM on
    2026-10-20/21 (main API: HTTP 410) but not the nodes: its database
    was mid catch-up (osm_base 10-19/20). update_dicosm raised KeyError,
    an "unexpected error", so 17 tiles failed for good instead of being
    requeued (#81). _overpass_request now rejects such an answer
    (dangling_node_refs: streams the <nd ref>s against a set of node
    ids; largest cached layer, +47-123 small_roads 261 MB: ~6 s, ~160
    MB) as failure kind BROKEN: next server tried, no skip of the
    server, no per-query fallback; all servers BROKEN = Overpass layer
    failure (overpass_gave_up), so batches retry the tile. Cached and
    custom OSM files are not checked (written by Ortho4XP or the user).
100. **DONE** (`c0f727e`, `9212bb9`, new tool, needs pyosmium): OSM
    layers from local Geofabrik extracts when Overpass blocks the IP
    (2026-11-13, see the 455-tile batch above).
    `prepare_osm_extracts.py FILE.osm.pbf ... --tiles ... | --tile-file
    .last_batch_tiles.txt [--road-level N --force --dry-run --index F
    --no-coverage]` writes, per tile and layer not yet cached, the
    answer Overpass would give ((stmts)(bbox);(._;>>;);out meta;: a way
    with any segment touching the tile, a relation with any member
    there, completed downwards, sorted by id, Overpass's escaping) to
    OSM_data/<10x10>/<tile>/<tile>_<layer>.extract.osm.bz2. Before asking
    Overpass, OSM_queries_to_OSM_layer reads such an answer through the
    same update_dicosm/write_to_file, so the cache is the same bytes a
    download of that data gives (unit test for all 5 layers); the log
    line names the file, the old-data NOTE (#83) applies with source
    "local extract". An answer made for other queries (road_level
    changed), cut or unreadable is not used (WARNING, Overpass as
    before). The #81 gate counts an answer as cached. road_level of
    each tile from its tile config, else the global cfg.
    Coverage: from Geofabrik's index-v1.json; a tile reaching into a
    region whose file is not given is skipped with the regions that
    would fill it; a gap only continents fill (sea beyond a country
    file) is a NOTE, unless the tile then has no data at all (its land
    may be in the gap). A tile whose ways or relations need nodes or
    member ways outside the files gets no answer (FAIL). The files are
    read one at a time in 6 filtered passes (pyosmium KeyFilter/IdFilter
    in C++, sparse_mem_array node locations); memory follows the tiles'
    data. O4_OSM_Extract.py holds the rules.
101. **DONE** (`6bb73cd`, `f2cb7d3`; new app settings): Geofabrik first,
    Overpass as backup. osm_source = geofabrik (default) | overpass;
    geofabrik_dir (empty = OSM_data\Geofabrik, so on F: here);
    geofabrik_max_age 1.0 days. O4_Geofabrik:
    - build_poly_file calls prepare_tile before the sea check: the
      layers step 1 would ask Overpass for (not cached, no answer, no
      custom coastline/water; needed_layers) are prepared from the
      extracts; False only on Stop. build_tile_list (do_osm) runs
      prepare_batch for all its tiles first (road_level from each tile
      config, read into a copy of the GUI's tile) and sets
      batch_prepared, so the batch's step 1 and its workers
      (batch_context.json "geofabrik_prepared") do not try again.
    - Regions: index-v1.json in geofabrik_dir (fetched when missing or
      30 days old; invalid outlines make_valid'ed). choose_regions:
      greedy cover of the part of the tile inside regions that hold no
      other region (mark_containers: netherlands holds its provinces,
      us-northeast the states, alps/dach countries; the index's parent
      field misses composites), by covered area per region area, then
      redundant picks dropped. A container's or continent's extra area
      is sea. No region at all: open sea, empty answers written (the
      #41 check then skips the tile). Only continents: Overpass.
      group_tiles: tiles needing the same files (or a subset) share one
      read.
    - ensure_file: download once (MD5, temp name, file lock against
      other processes) to geofabrik_dir/<server path>; data older than
      geofabrik_max_age -> pyosmium-up-to-date (subprocess, -o temp,
      --size 1024, rerun while exit 1), a .checked marker stops
      re-asking within an hour when Geofabrik has nothing newer. Any
      failure (no index, download, update, extraction gap) is logged
      and the layer goes to Overpass as before.
    - A used extract answer is removed once its cache is written.
    - prepare_osm_extracts.py without files: the same for a tile list
      (--dry-run lists files per tile); --check: compare cached layers
      with the extracts now (way keys by tags and coordinates), the
      caches are never replaced (delete a layer and rebuild).
    Memory: ~3.5 x the largest file read (Norway 1.4 GB: 4.6 GB).
    Overpass: HTTP 401/403 now DOWN (FR's 403 caused per-query
    fallbacks), see the server check above.
102. **FIXED** (`0adf368`, `c39d20a`; the first Windows only in part):
    review of #100/#101.
    - load_index kept any HTTP 200 answer as the index (an HTML error
      page) for 30 days; every step 1 then crashed with JSONDecodeError
      (not a GeofabrikError, so not caught; a batch before its first
      tile). Now a download is parsed (read_index) before it replaces
      the old file, a broken file on disk is fetched again, and parse
      errors are GeofabrikError (layers go to Overpass).
    - An .md5 answer without a checksum raised IndexError (same path);
      now GeofabrikError; the .md5 response is closed.
    - Windows: Stop during pyosmium-up-to-date kills it with exit code
      1 = "more changes to come", so _update kept its temp file (up to
      the extract's size). Removed unless the run completed;
      ensure_file removes leftover temp files of its file under its
      lock.
    - An extract answer update_dicosm cannot read is logged and the
      layer emptied before Overpass fills it.
    - group_tiles also merges groups that share a file (norway read
      twice for the Swedish and the Finnish border) while the merged
      group stays within MAX_MERGED_TILES (16): the extraction holds
      all tiles of a group at once (~2-3 x their uncompressed answers;
      user's caches: median tile 14 MB, p90 80 MB, +52+004 400 MB) and
      borders chain whole continents. 412 Scandinavian tiles: 44 -> 38
      file reads, largest group 115 tiles as before.
    - prepare_tiles writes each group's answers at once (a batch kept
      all of them in memory to the end) and returns their sizes.
103. **FIXED** (`5765e46`, CHANGES OUTPUT, new baseline): build_mesh's
    inland water smoothing (post_process_nodes_altitudes) overwrote one
    triangle's three vertices after another in Python set order, so the
    result depended on the vertex numbering: any small change in a tile
    moved water altitudes all over it (#73's 7,899 far vertices). On
    +55+012 another order moves 161,313 of 267,833 water vertices by
    > 0.5 mm, up to 2.7 m. smooth_water_altitudes (numpy): each sweep
    sets every water vertex to the mean of its water triangles' means
    from the previous sweep; 3 sweeps per water_smoothing pass
    (WATER_SWEEPS_PER_PASS) flatten as one old pass did (mean spread
    within a triangle 1.40 vs 1.44 cm, p99 13.2 vs 15.3 cm, max 2.78 vs
    4.23 m; mean change 0.170 vs 0.174 m), 0.50 s instead of 0.91 s.
    Tiles built before keep the old water altitudes until rebuilt (not
    worth a rebuild: differences of cm, at most ~2 m on rivers).
104. **DONE** (`656ef6d`, new app setting): osm_cache_max_age (days,
    default 0 = off: cached layers are kept for good, as before). When
    step 1 runs (single build, or a batch's preparation before phase 1),
    a cached layer older than that (the cache file's mtime: written when
    the data was fetched) is prepared again from Geofabrik like a missing
    one (GEOFABRIK.needed_layers, cache_is_stale). Step 1 prefers an
    extract answer newer than the cache (OSM._refresh_from_extract) and
    logs "OSM <layer> layer of <tile> was N days old, refreshed from the
    local extract." The old cache stays in use when no answer comes: no
    Overpass request for a refresh ("Geofabrik: OSM data of <tile> not
    refreshed (...); its cached layers are used"), an unusable answer
    ("keeping the cached layer"), an answer older than the cache
    (ignored), and a tile outside every region (no empty sea answer
    replaces a cache). Not done: the #77 road_level gap (a small_roads
    cache made at a lower level): finding it means decompressing the
    cache, ~10 s per tile. OSM_layer.write_to_file now writes under
    FNAMES.temp_path_for and os.replace()s (an interrupted write left a
    cut cache that later builds read). The user asked for 30 days, to
    be set when this is on dev.
105. **FIXED** (`8ec2a50`): build_overlay failed a tile whose overlay
    source has no DSF for it, so a batch counted it failed and kept it
    in .last_batch_tiles.txt for good (58-tile batch: +37-025, open
    ocean, X-Plane has no DSF; the 11 Oregon tiles, missing from the
    user's install). Now, when the source's Earth nav data folder exists
    but lacks the tile: one logged WARNING ("no overlay for tile ...:
    the Global Scenery has no DSF for it (... absent). Fine for open
    ocean; for land, check the X-Plane installation."), step 4 ends
    normally. A source without Earth nav data (wrong setting) and an
    unset custom_overlay_src stay errors. Step 3 warns about the
    missing rasters as before (#50).
106. **FIXED** (`8bff0d3`): mark_containers flagged a region as a
    container (its outline beyond the regions it holds = sea, never
    read) as soon as one region lay 90 % inside it. Geofabrik's outlines
    have enclaves (ceuta/melilla in morocco, bremen in niedersachsen,
    kaliningrad in northwestern-fed-district, berlin in brandenburg, act
    in new-south-wales, crimea in ukraine, monaco in PACA, hong-kong and
    macau in guangdong, beijing/tianjin in hebei, east-timor in
    nusa-tenggara, praha in stredocesky, the azores in portugal), so
    their land was taken for sea: no roads, water, airports there, and a
    coastline that runs into it cannot be closed (the 440-tile batch:
    +35-006, +53+008, +53+009, +69+030 failed; +35-005, +35-007,
    +52+006, +52+007, +53+006, +53+007, +69+028, +69+029, +70+031 built
    without that land; re-prepared with the fix through
    prepare_osm_extracts.py --force, rebuild them from step 1). Now the
    smaller regions at least half inside a region must cover
    CONTAINER_MIN_SHARE 0.25 of its outline (index of 2026-11:
    composites 0.40 australia .. 1.0; enclave holders 0.0003 morocco ..
    0.14 portugal; alps 0.72 by countries half inside, none 90 %).
    Before the fix every tile built from Geofabrik in those regions may
    lack that land: the user's affected tiles are exactly the 13 above
    (scan of all 478 tiles with OSM data).
107. **FIXED** (`8ee37b5`, closes #77's road_level gap): the
    small_roads cache has one name at every road_level and step 1
    recycled any cache, so raising road_level kept the old roads
    silently; an extract answer made at the old level also stopped
    needed_layers from preparing a new one (step 1 then rejected it and
    kept the cache). Caches now carry an <o4xp_cache statements="..."/>
    line (OSM_layer.write_to_file(filename, statements); the reader
    skips it). EXTRACT.cache_fits: a stamped cache must name the asked
    statements; an unstamped small_roads cache must hold exactly the
    asked highway values (a tile without one track counts as not
    fitting at level 5: refreshed once, then stamped); other unstamped
    layers pass. needed_layers prepares a layer whose answer
    (answer_fits) or cache does not fit; step 1 prefers the newer
    answer (#104), else uses the cache with a logged WARNING. No
    Overpass request for it (as #104).
108. **FIXED** (`fa43db9`): .last_batch_tiles.txt
    (read_leftover_tiles) and prepare_osm_extracts.py --tile-file
    matched a whole line against +LL+LLL; the batch lists of 2026-11-15
    note every tile ("+63-152  # Denali"), so the tile window would have
    selected none of their 465 tiles (silently) and the script stopped.
    Both cut a line at "#" first.
109. **FIXED** (`71831b9`): needs_mask / mask_name_for_texture give no
    mask to a texture below mask_zl, and build_dsf then gives its water
    triangles no imagery; with the user's mask_zl 16 the ZL15 batch B
    would have lost every coast blend, silently, after building all
    masks at ZL16. MASK.fit_mask_zl (step 2.5 and step 3) lowers
    tile.mask_zl to min(default_zl, zone zoom levels) with a NOTE. The
    user's 450 tile configs are all ZL16 / mask_zl 16: none affected.
110. **FIXED** (`312dd8d`): prepare_osm_extracts.py counted any cache or
    answer as done, so it skipped stale caches (#104), caches of another
    road_level and answers of other statements (#107); it now uses
    GEOFABRIK.needed_layers and reads osm_cache_max_age. --check
    unchanged. The build was never affected.
111. **FIXED** (`09adf2c`): a config write cut off by closing or
    killing Ortho4XP left its write_text_atomic temp file for good
    (2026-11-16 05:16: empty .tmp..._.last_gui_params.txt).
    FNAMES.remove_stale_temp_files (was TILE._remove_stale_temp_files,
    #49; name filter added) runs at startup for the program folder's
    configs (ROOT_TEXT_FILES) and in step 3 for the tile folder; files
    younger than 1 h stay.
112. **DONE** (`7127c49`): nothing held step 3 back when the imagery
    provider failed: every tile downloaded into the outage and failed.
    build_tile sets TILE.imagery_gave_up when only imagery is missing
    (only_imagery_missing: textures not downloaded or partly white, DSF
    built, all conversions fine); workers exit IMAGERY_EXIT_CODE 5.
    _ImageryGate in the phase with step 3 (sequential and parallel): the
    tile is requeued, not before imagery_retry_wait 600 s, fails after
    imagery_tile_tries 3; after imagery_pause_after 2 such tiles in a
    row no tile starts step 3 until IMG.provider_answers (one 256 px
    image at the first held tile, nothing written; combined provider:
    first layer) gets an image, every imagery_probe_interval 300 s, at
    most imagery_wait_max 6 h; a tile through step 3 reopens it. The
    probe asks the batch's provider (GUI, or tile config at batch
    start). _next_startable takes any number of gates.
113. **FIXED** (`7852e1c`): the user's Elevation_data holds 33 0.5"
    .hgt files (7201 x 7201, 2024; Alps N45-N49 / E005-E017). The
    combined View/SRTM raster takes 1" or 3" grids only, so such a file
    stopped its own tile in step 1 (DEMError, +47+011) and zeroed a
    neighbour's 36-sample margin with a WARNING (+48+011: 600 m cliff at
    its south and east edges, counted as built); master crashed on the
    shape. thin_to_grid: a square grid with (n - 1) % 3600 == 0 is read
    as [::k, ::k], its exact 1" posts (console line names the file).
    custom_dem pointing at the file still uses its full resolution;
    other grids stop / zero as before.
114. **FIXED** (`f52f33e`): tile groups sharing an extract each called
    ensure_file, so a cut or refused download started again in full for
    every group (repeated downloads of one large file, what Geofabrik
    objects to), and a failed update was retried the same way. Both are
    remembered for the rest of the preparation (prepare_tiles clears
    them): the tiles of a failed download go to the fallback at once, a
    file whose update failed is used as it is. Load on Geofabrik
    otherwise: one request at a time, in the batch's parent before phase
    1 (workers never call it), each new extract once (MD5), existing ones
    updated by daily diffs at most once per preparation, the index every
    30 days; User-Agent "Ortho4XP".
115. **DONE** (`f6c4468`, new app setting xp_flatten_airports, default
    True; CHANGES OUTPUT where X-Plane flattens an airport): X-Plane draws
    an airport with "1302 flatten 1" on ground forced flat at the airport
    elevation inside its apt.dat boundary (row 130); where the DEM differs
    (data older than the airport, uneven ground in a large boundary) the
    edge showed as vertical walls (Nuuk BGGH, see the test results). New
    O4_XP_Airports: Global Airports/Earth nav data/apt.dat next to
    custom_overlay_src (or _alternate) is read once into
    tmp/xp_flatten_airports.json (rebuilt when its size or mtime changes;
    file lock for parallel workers); step 1 (include_xp_flatten_areas,
    after include_patches) inserts each boundary reaching into the tile,
    clipped 1e-6 deg inside it, holes kept, as INTERP_ALT rings at the
    airport elevation (as a cst_alt_abs patch), and leaves the OSM
    runways/taxiways/aprons inside it out of the runway levelling. A user
    patch named <ICAO>.patch.osm wins. Log line "Airport X: built flat at
    N m inside X-Plane's airport boundary ...". Bezier boundaries: nodes
    only. Not read: Custom Scenery airports (a custom pack's apt.dat
    replaces the gateway one in X-Plane, maybe without flatten). No
    apt.dat found: console note, build unchanged (regression, sims).
116. **FIXED** (`edfff84`): batch B+D lost +79-069/070/071 and +82-039 in
    step 3 and waited twice for the full 6 h imagery pause (#112). GO2
    answers 404 down to ZL10 in parts of Kane Basin and to ZL13 at +82-039's
    ZL18 airport cover; get_wmts_image went at most 5 levels down (the
    images are at 6), so those textures stayed white. Each tile was
    requeued 3 times as if GO2 were down, and the pause's probe asked the
    middle of +79-070 (404 every 5 min, 6 h). Now: down to MAX_DOWN_SAMPLE
    8 levels (one pixel of the coarse image; only formerly white textures
    change); an ImageryReport through the texture builders tells "no data"
    (404 at every level) from other failures; a tile white only on no data
    is not retried and not an outage (ERROR naming the provider, fails at
    once); provider_answers counts no data as an answer and the probe asks
    at the last tile that got all its imagery; one NOTE per tile for
    textures cut from 6+ levels lower (IMG.coarse_imgs).
117. **DONE** (`d61e178`, new app setting imagery_fallback, default
    ["Arc", "BI"]; CHANGES OUTPUT for textures fetched from now on): on a
    404 at the asked level a piece is asked from each fallback provider at
    that level (webmercator, same piece size, within max_zl, not the
    provider itself) before the provider's own lower levels. In the Arctic
    GO2 drops 2-3 levels for about a quarter of the ZL15 textures and those
    pieces are coarse blocks; Arc has sharp imagery there. Fallback pieces
    can differ in colour and season (Arc: summer, GO2: snow patches). One
    NOTE per tile (IMG.fallback_imgs). The pause's probe asks the provider
    only. Existing JPEG/DDS are reused: built tiles change only when their
    textures are deleted and step 3 runs again.
118. **FIXED** (`704ce67`): Geofabrik moved every region into a folder of
    its own in 2026-11 (europe/france/alsace/alsace-latest.osm.pbf; the old
    URLs redirect there, then 307 to a dated file alsace-261119.osm.pbf)
    and dropped the -latest .md5 files (404). _download asked url + ".md5"
    first, so every extract not yet on disk failed and its tiles went to
    Overpass; existing extracts still updated (the replication URL in the
    file header redirects too). Now: .md5 of the URL the download ended at,
    then of the old name; none at all -> the size must equal Content-Length
    (skipped for a gzip answer); other HTTP errors still stop. local_path
    leaves out a folder named exactly like the region, so a refreshed index
    with the new URLs finds the extracts on disk (us/us-virgin-islands is
    the old form). prepare_tiles: a file that cannot be had fails only the
    tiles that need it (a merged group used to fail whole).
119. **FIXED** (`d6474c7`, CHANGES OUTPUT around airports X-Plane
    flattens): #115 built the inside of the flatten boundary flat, but the
    mesh outside followed the DEM, so the wall moved to the boundary (Nuuk
    BGGH in the built +64-052: 86 m next to 45-53 m within 9-21 m, found
    with DSFTool --dsf2text on 2026-11-20). XPAPT.ramp_dem_around_areas
    sets the DEM inside each area to its elevation and blends linearly back
    to the data within FLATTEN_RAMP_M 100 m, before
    smooth_raster_over_airports writes the alt file step 2 reads; airports
    with a user patch are skipped (areas_without_user_patch). +64-052 steps
    1-2 in a scratch cwd: triangles > 60 deg within ~300 m of BGGH 231 ->
    12 (the rest 107-160 m away: roads, rock), > 45 deg 316 -> 28. 4 new
    unit tests, 655 pass, pyflakes 0, regression --overlay PASS (DSF, 17/17
    masks, app log identical: the frozen Global Scenery has no apt.dat).
    `test` @ 43e1fa6. The user's Patches\+64-052\BGGH.patch.osm was never
    read (patch_dir is Patches\+60-060\+64-052); moved there it would
    skip the ramp. The tiles with flatten airports need steps 1-3 again.
120. **FIXED** (`353446d`): choose_regions took the part of a tile outside
    every country region for sea. Islands in no country extract next to
    one that has a file (Dominica +15-062, Montserrat +16-063, Saba
    +17-064, Grand Turk/South Caicos +21-072, the Caicos +21-073, part of
    the BVI +18-065) lost their good Overpass caches in the refresh of
    2026-11-14 and were built as sea (+21-072 had no water at all).
    plan_tiles checks that part against the tile's .hgt (gap_continents,
    read only; GAP_EDGE 0.002 deg, GAP_LAND_MIN 4 samples): land there
    reads the continent file when it is on disk, else Overpass with the
    file named; a continent-only tile also reads its continent when on
    disk. Without a .hgt the old rule stands. 3,668 tiles worldwide have
    continent-only area, nearly all sea.
121. **FIXED** (`03c3c5d`): delete_old_masks_in_tile removed the .png
    masks but not their _dist.png; step 3 reads a distance mask for the
    bathymetry ratio of any square that has one. 129 tiles hold 483 such
    files; in +65-024 all 2,891 water vertices in those squares had the
    full-depth or coast value, so nothing visible: no rebuild.
122. **FIXED** (`57966d9`): Tile.write_to_config (step 3) wrote the zones
    of the GUI's global zone_list that overlap the tile. A batch reads
    each tile config, zones included, and builds with them, but the
    global list holds only the GUI's zones: step 3 rewrote the config
    without the tile's own zone, so the next rebuild silently lost it.
    Now it writes the tile's own zone_list (in the GUI a Tile is made from
    the globals, so the GUI is unchanged). Found while adding the Nuuk BI
    zone; no tile had a zone before.
123. **DONE** (`9677a01`): #115/#119 assumed X-Plane flattens the airport
    boundary; it flattens far more (BGGH: sea at 86 m, hills cut, straight
    edges), over the DSF. Airports X-Plane flattens are therefore given to
    X-Plane without the flag: step 1 writes xp_flattened_airports.json in
    the tile folder (the airports this mesh has flat; none: no file), and
    after a single step 3 or at the end of a batch (TILE.
    update_airport_override; workers never) XPAPT.update_override_pack
    writes yOrtho4XP_Airports/Earth nav data/apt.dat next to the overlays:
    X-Plane's own block of each flatten airport whose every tile (the
    boundary reaching in) has it recorded and a DSF not older than the
    record, minus "1302 flatten 1" (UTF-8, CRLF), only rewritten when that
    list or apt.dat changed (ortho4xp_pack.json). The pack must be in
    Custom Scenery above Global Airports (a shortcut keeps it current).
    Airports reaching an unbuilt tile stay flattened by X-Plane (without
    the flag X-Plane's own mesh would leave their runways bumpy).
124. **FIXED** (`4f00a6c`): the #123 pack took its airports' 3D away. Global
    Airports' DSF of a tile holds each airport's buildings, hangars, cars
    and lights in a block behind FILTER n (a comment command: uint16 1,
    int32 n; n counts the "sim/filter/aptid <ICAO>" properties, the
    sim/exclude_* after one belong to it), drawn only while the airport
    comes from that pack. update_override_pack now writes per tile a DSF
    with only its airports' blocks and exclusions (XPAPT.filter_dsf, in
    Python: DSFTool crashes on 2 of the 48 sources; definitions and pools
    copied, state commands and the other comment kind (uint16 2, before
    objects, 1,299 files) kept everywhere, MD5 rewritten), for the tiles
    around each airport's boundary; DSFs of tiles that left the pack are
    removed. A failure is a WARNING without stamp (retried next time);
    PACK_VERSION 2 in the stamp redoes #123's pack.
125. **DONE** (`dc94fa8`, new app setting keep_dsf_backup, default True
    = unchanged): step 3 moved the previous DSF to <tile>.dsf.bak before
    writing the new one (110 GB of them deleted by hand on 2026-11-21),
    so a failed step 3 also left the tile without a DSF. Off: the old DSF
    stays active until build_tile replaces it with the complete new one,
    and an older .bak of that tile is removed (DSF.set_aside_old_dsf; an
    unremovable one is a WARNING).
126. **FIXED** (`d13dea8`, log only): the map's Earth preview printed
    "Could not find Earth preview file ..." for any exception while
    drawing a square (9 times since 2026-11-05, all 64 files present;
    the cause went to the console only). GUI.earth_preview_error: a
    missing file keeps the message, tk.TclError (a redraw thread's image
    or the window gone) is quiet as for the other 3 squares, anything
    else is an ERROR with type and text.
127. **FIXED** (`05e4420`): the old URL of papua redirected to
    indonesia/papua/... without "asia/" (404) on 2026-11-21/22, and our
    index of 11-13 still gave the old URLs, so 5 tiles of the 296-tile batch
    went to Overpass. GEOFABRIK.url_variants: a -latest extract that answers
    404 is asked in the other folder layout (flat <-> folder per region);
    both give the same local_path.
128. **FIXED** (`efb2238`): the index (the only list of extract URLs) was
    kept 30 days, so any other change of Geofabrik's layout broke downloads
    until then. A 404 after #127's variants (GeofabrikNotFound) fetches the
    index again unless it is younger than INDEX_RECHECK (1 day), and
    ensure_file retries with the URL it now gives for the same region id;
    a failed index fetch is not repeated in the preparation.
129. **DONE** (`adef5de`): extracts were stored at a path made from the
    download URL, so each layout change of Geofabrik (#118, #127, #128)
    hid files on disk. Now geofabrik_dir\extracts\<region id>.osm.pbf
    (us/georgia -> us__georgia.osm.pbf, EXTRACT.store_name) with
    extracts.json (per region: url, size, downloaded, updated, checked,
    update_failures, broken, moved_from; replaces the .checked files) and
    one .lock. GEOFABRIK.ensure_extract(region) replaces ensure_file. The
    first preparation moves old-layout files there (migrate_store,
    extracts\moved_<time>.csv; prepare_osm_extracts.py --store [--dry-run],
    --undo-store-move FILE.csv; also lists files no longer in the index).
    A file without the PBF start (checked before pyosmium opens it: a
    failed open keeps the handle on Windows) or that pyosmium cannot read
    is set aside as .broken and downloaded again. 3 failed updates in a
    row, data over 30 days old (REFRESH_AGE), or an update server in the
    file other than the index's (old form europe/norway-updates) mean a
    new download; if it fails the old file is used. pyosmium output goes
    to a temp file, each run is killed after UPDATE_TIMEOUT 2 h.
130. **FIXED** (`8de0398`, CHANGES OUTPUT where OSM has such lines):
    discover_airport_names took every way with an "airstrip" value for an
    airport area; LINZ maps New Zealand's bush strips as two-node
    aeroway=airstrip lines with a width, so Polygon() raised and the strip
    was dropped with "A presumably erroneous tag marked aerodrome" (~60
    WARNINGs per batch), never levelled. An open airstrip way is now a
    runway (APT.is_airstrip_line): it joins the aerodrome within 3.5 km or
    makes an airport of its own, like a runway line; closed ones stay
    airport areas. Built tiles change only when step 1 runs again.
131. **FIXED** (`875fac0`, review of #129): migrate_store planned its moves
    before the store lock and called os.replace without a try, so one
    locked file (or one another process had moved) raised OSError out of
    prepare_tiles: every tile to Overpass. Now planned under the lock; a
    file that cannot be moved stays (WARNING, next time again). Also: side
    files left without an extract go; only folders the move emptied are
    removed; moved_*.csv through the csv module (a comma in a path broke
    the undo; the first form still reads); an undo drops the manifest
    records; _update after UPDATE_RUNS runs that all exited 1 ("more to
    come") is a failed update, no longer recorded as up to date.
132. **FIXED** (`fb9f810`, review of #124): write_object_dsfs removed every
    pack DSF it had not written this time, so a tile whose rewrite failed
    (X-Plane holding the file: PermissionError) lost its airports' 3D
    until the next good update. Its last DSF now stays; a stale DSF that
    cannot be removed is a failure in the WARNING (no stamp) instead of an
    OSError that skipped apt.dat.
133. **DONE** (`1dd075d`): Overpass requests end in plain `out;` instead of
    `out meta;`: the reader never kept the meta attributes (ids renumbered,
    tags, refs and coordinates by name), so the cache bytes are the same
    and the answer is smaller (DE is the only server and slow). osm_base
    stays in the header (#83's old-data NOTE).
134. **FIXED** (`7491702`, CHANGES OUTPUT near airports X-Plane flattens,
    review of #119): the ramp took only the flatten airports whose
    boundary reaches into the tile, clipped to it, so a neighbour within
    100 m got no ramp and a boundary across a tile edge was ramped in
    each tile against its own part (different elevations on the shared
    edge). XPAPT.ramp_areas takes every flatten airport within the ramp
    width of the DEM bounds, unclipped, and measures at the area's own
    latitude. A user <ICAO>.patch.osm skips the ramp only when it parses
    (Vector_Map._usable_patch), like include_patches.
135. **FIXED** (`5100866`, review of #104): needed_layers counted any
    extract answer on disk as prepared, also a cut one and one older than
    the cache; step 1 rejected it but left it, so the stale cache was
    never prepared again and every build repeated the WARNING. Step 1 now
    removes an answer it rejects or that is older than the cache, and
    needed_layers counts only an answer not older than the cache.
136. **FIXED** (`3692e9d`, review of #105): build_overlay took a missing
    tile DSF for open ocean as soon as any source had Earth nav data, so
    a misspelt custom_overlay_src next to a valid _alternate passed every
    tile the alternate lacks without overlay. Any set source without
    Earth nav data is now an error naming it.
137. **DONE** (`1f73d0c`): src/Unused removed (48 files of dead upstream
    code; nothing imported or built them; they stay in git history).
138. **DONE** (`c7c7455`, data only): Providers/Faroe/FO.lay named
    kortal.fo's TMS, which now redirects to a web page. FO is now
    Umhvørvisstovan's public ArcGIS WMS (myndakort_fotm, layer 1,
    EPSG:3857, no key). It is transparent beyond the islands and their
    shore (white in a JPEG), so Extents/Faroe holds its coverage from the
    alpha of its own answer (15 m pixels, full from 60 m inside the edge,
    ramp from 15 m) and the combined provider FOA puts FO over it, Arc
    under it. Compared on 6 sites: FO is the sharpest and true-ortho in
    towns and at Vágar (GO2 has a Google watermark at ZL18), but at ZL16
    it is a mosaic of flights with strong colour differences (saturated
    yellow-green village blocks on a brown base). The user's choice
    (2026-11-24): +62-008 stays GO2 ZL16 with one ZL18 FOA zone over the
    54 textures of Vágar's airport cover (62.0318-62.1039 N, 7.1850-7.3609
    W; backup cfg_backups\2026-11-24_vagar_foa_zone); FOA, not FO, so the
    fjord beyond FO's coverage gets Arc, not white. Needs steps 1-3.
139. **DONE** (`fda935a`, data only): Denmark from Klimadatastyrelsen's
    orthophoto. Providers/Denmark/DF.lay.example (WMS
    api.dataforsyningen.dk/orto_foraar_DAF, layer orto_foraar, EPSG:3857,
    token=YOUR_TOKEN); the real DF.lay holds the user's personal token
    and is in .gitignore (never commit it; never use credentials that
    Dataforsyningen's capabilities embed). Extents/Denmark_DF (40 m
    pixels, outline smoothed and faded so the water shows no blocky
    seam) and the combined provider DFA: DF over it, GO2 under it.
    Without DF.lay, DFA does not load (its test is skipped). The user's
    23 Danish tile configs with DF coverage set to DFA on 2026-11-24
    (backup cfg_backups\2026-11-24_dk_dfa); +54+013, +55+013 and +57+012
    (no DF coverage) stay GO2.
140. **FIXED** (`d8e868a`, CHANGES OUTPUT for tiles with zones):
    zone_list_to_ortho_dico gave each texture block (16 mesh_zl tiles,
    one ZL18 texture at mesh_zl 18, ~1.2 km) the zone at its centre pixel
    only, so a zone narrower than a block could take no block and change
    nothing, silently: after the 66-tile rebuild of 2026-11-24, 6 of the
    82 Greenland zones (1 km helipad boxes) took none and 7 sites were not
    on their zone's imagery. DSF.block_zone_index: the topmost zone on any
    pixel a full pixel inside the block (polygon vertices round to whole
    pixels, rings are stored to 4 decimals), so a zone along texture edges
    (Vágar) does not grow. A zone now also gets the blocks it partly
    covers (the user's 45 zone tiles: 605 -> 899 blocks; Nuuk +30).
    5 new unit tests (3 fail on dev), 793 pass, pyflakes 0, regression
    --overlay PASS (DSF, 17/17 masks, app log identical: no zones).
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
22. ~~#99~~ — on `dev` since 2026-11-13.
23. ~~#100~~ — local OSM extracts; on `dev` since 2026-11-13.
24. ~~#101~~ — Geofabrik first; on `dev` since 2026-11-13.
    Not done: `out` instead of `out meta` for Overpass.
25. ~~#102, #103, #75~~ — fourth review; `dev` fast-forwarded to
    8708c90 and pushed on 2026-11-13, the three fix branches and
    worktrees removed. On dev 75ae9dc the same day: gui_smoke 7/7
    (396 tiles on the map, the user's .last_gui_params.txt, log, cfg
    and leftover file unchanged, hash-checked); test_parallel_batch from
    the _test worktree (junctions to the F: caches, a copy of the cfg,
    removed with rmdir afterwards; no OSM or imagery download): compare
    166/166 masks and 3 DSFs identical seq/par (seq 847 s, par 641 s),
    context, fail, stop all ok. Not run: the Linux/macOS Triangle4XP
    (not rebuilt: no "Steiner points left" line, the count test stays
    there).
26. #104 — refresh of old OSM caches; on `test`, to `dev` with the
    user's OK, then osm_cache_max_age=30 in the user's cfg.
27. #105 — overlay without a Global Scenery DSF warns; on `test`, to
    `dev` with the user's OK.
28. #106 — Geofabrik enclaves; on `test`, to `dev` with the user's OK.
    Then rebuild the 13 tiles from step 1 (and +67+017).
29. #107 — caches made for another road_level; on `test`, regression
    after the running batch, then to `dev` with the user's OK and the
    36-tile rebuild (rebuild_road_level5.txt). Done: on `dev` ac92157.
30. #108-#112 — pre-batch review 2026-11-16; on `test` @ 01fccc9, to
    `dev` with the user's OK, then the 36-tile rebuild and batches A
    (ZL16), B (ZL15: set ZL15 in the GUI first) and C. Done (on
    `dev` 7b84bf4); pilots first (see the test results).
31. #113 — 0.5" .hgt files; on `test`, to `dev` with the user's OK
    before batch C, then rebuild +47+011 and +48+011. Done: on `dev`
    0d57def, pushed.
32. #114 — Geofabrik failed files not retried; on `test`, to `dev` with
    the user's OK, then batch A (322), B (103, ZL15), C (20). Done: on
    `dev` 9a9a0b0, pushed; batch A running.
33. #115 — airports X-Plane flattens; after batch A: regression,
    sims_in_ws, step 2 check of +64-052, gui_smoke, then `test`, to `dev`
    with the user's OK before batch B+D (122 tiles, +64-052 first). The
    built tiles with flatten airports (scan list) need steps 1-3 again.
    Batch A done 2026-11-18; all checks passed, `test` @ (this merge).
34. #116, #117 — imagery holes and fallback providers, from batch B+D;
    on `test` @ 5f96c6d, to `dev` with the user's OK once batch B+D has
    ended (the running GUI keeps the old code). Then step 3 again for
    +79-069/070/071 and +82-039; for the Arctic GO2 tiles with coarse
    textures, deleting their textures and running step 3 fetches Arc.
    Done: dev 92ead0f pushed 2026-11-19; the 4 tiles built 2026-11-19.
35. #118 — Geofabrik's new folder layout; on `test` @ dce73b3, to `dev`
    with the user's OK (given) once batch C has ended.
36. ~~#120, #121~~ — from the full tile audit; on `dev` bf6f064 since
    2026-11-21 (with the user's OK, before the cache refresh ~2026-12-14);
    the 34-tile rebuild done. Was: on `test` @ 2351a5e, to `dev`
    with the user's OK, before the 30-day cache refresh (~2026-12-14)
    would empty the Caribbean islands again. Then the 34-tile rebuild
    (20 audit tiles, 14 Canadian ZL16 tiles; afterwards remove their
    ZL15 .dds/.ter).
37. ~~#122~~ — on `dev` bf6f064 since 2026-11-21. Was: on `test` @ 5000800, to
    `dev` with the user's OK (with #120/#121). Until then, put the Nuuk
    zone line back into +64-052's tile config after each build of it.
38. ~~#123~~ — airport override pack without X-Plane's flatten; on `dev`
    5ad0b07 since 2026-11-21, pack linked in Custom Scenery.
39. ~~#124~~ — the pack's airports get their Global Airports 3D; on `dev`
    9287de3 since 2026-11-21 (pushed 22fb48e), the user's pack rewritten;
    Nuuk's buildings back in X-Plane.
40. ~~#125, #126~~ — on `dev` since 2026-11-24, pushed.
41. ~~#127, #128~~ — Geofabrik URLs; on `dev` since 2026-11-24.
42. #129 — extract store by region id; on `dev` since 2026-11-24
    (pushed); the 164 extracts moved into the store the same day.
43. #130-#132 — unattended pass 2026-11-24; on `dev` since 2026-11-24
    (pushed). #130 changes the 27 tiles with airstrip lines
    when their step 1 runs again (no rebuild needed for it). Not run:
    gui_smoke (user away; no GUI code changed).
44. ~~FR Overpass server dropped~~ — on `dev` since 2026-11-24 (pushed).
45. ~~#133-#137~~ — fifth review 2026-11-24; on `dev` since 2026-11-24
    (pushed).
46. ~~#138, #139~~ — Faroe and Denmark providers; on `dev` since
    2026-11-24 (pushed). The 66-tile rebuild (43 Greenland tiles with
    the audit's zones, 23 Danish tiles on DFA; steps 1-3 + overlays,
    tile configs, no override) started 2026-11-24 12:47 from
    G:\Ortho4XP_tests\batches\batch_run.py (log
    run_2026-11-24_gl_dk.log there). +62-008 (Vágar FOA zone) after it.
    Done: 66 built, 0 failed (4h21m); +62-008 built after it (all 54
    airport textures FOA18). 6 helipad zones took no block: #140.
47. ~~#140~~ — small zones; on `dev` dc1e423 since 2026-11-24 (pushed).
    Steps 1-3 + overlay of +60-044, +60-046, +60-047, +61-049 (14m47s)
    and +59-045 (its helipad zone is cut at the tile edge; on dev it took
    only a neighbouring block): 5 built, 0 failed. Imagery recheck of all
    67 tiles rebuilt that day (scratchpad recheck_imagery.py: DSF new,
    base provider used, no missing texture, each zone's site on its
    zone's .ter): 82 zones, 84 site points, 0 problems. The other zone
    tiles get the wider zones whenever rebuilt.
48. ~~Batch E~~ — wilderness tiles on `dev` 4b35907 (batch_run.py,
    G:\Ortho4XP_tests\batches; pre-check precheck_2026-11-24_wild.md).
    batch_e_zl16_wild.txt (121 tiles, GO2 ZL16: Alaska, BC/Yukon,
    Patagonia, Scandes, NZ South Island; 2026-11-24 19:34 to 11-25 15:18,
    19h26m): 120 built, +59-146 open sea, 0 failed; then
    batch_e_zl15_holes.txt (+62-051, +64-053, +79-067, +79-073, GO2 ZL15,
    11 min; started by then_run.ps1 after the first): 4 built. No ERROR;
    4 WARNINGs, all +79-067/+79-073 without X-Plane DSF (rasters,
    overlay); NOTEs: 79 tiles with Arc/BI pieces (#117; GO2 drops 1-2
    levels in interior Alaska, Arc has ZL16 there), 63 limit_tris, 4
    mask_zl at ZL15. Check (scratchpad recheck_batch_e.py): 124 new DSFs,
    base provider used, no missing texture, 0 problems; DSFs median 138
    MB, max 167 MB (-46-075), 14.1 GB. Airport pack 73 airports, 71 DSFs
    (new: PANC, NZRC, XEH000F, XED002S, ...). Small-zone scan of all
    1,474 tiles (83 zones in 45): only +69-052's Qeqertaq zone partly
    off its imagery (built before #140): rebuild it with the next list.
    gui_smoke 7/7 on dev 4b35907 (126 tiles in the map's view, 0
    callback errors; .last_gui_params.txt, cfg and log hash-checked,
    copies in cfg_backups\2026-11-25_gui_smoke).
    OSM refresh dry run 2026-11-25 (prepare_osm_extracts.py --tile-file
    <all 1,598 tiles> --force --dry-run, 40 s, nothing written): no cache
    over osm_cache_max_age 30 yet; the oldest layer of each tile passes
    it 12-08..12-13 (39 tiles), 12-14 (378), 12-15..12-18 (713),
    12-19..12-25 (468). A refresh happens only when a tile's step 1
    runs. 1,596 tiles in 81 groups from 167 extracts, 160 on disk (34.4
    GB); 7 would be downloaded for 15 tiles whose caches came from
    Overpass: spain (+36-006), papua (-03/-07/-08/-09/-10+141),
    karlovarsky, plzensky, stredocesky (+48+013, +49+012, +49+013),
    unterfranken (+49+009, +49+010), franche-comte (+48+006).
    +16-170 (no region) and -08+072 (asia only) keep their caches (#104).
49. ~~+69-052, extracts~~ — 2026-11-25: +69-052 rebuilt for its Qeqertaq
    zone (4m10s, 0 failed; both zones' site and centre on GO218,
    scratchpad check_one.py). The 7 extracts the refresh dry run lacked
    downloaded through GEOFABRIK.ensure_extract (franche-comte 125 MB,
    karlovarsky 31, papua 36, plzensky 72, spain 1506, stredocesky 182,
    unterfranken 105; 7 min): all 167 regions of the plan in the store
    (36.4 GB). CLAUDE.md trimmed from 2,705 to ~220 lines; this file
    holds the rest.
13. ~~#64-#74~~ — second review, 2026-11-08; #73 and #74 were the two
    items left for the user, done the same day (#73 with a new
    baseline). The inline water smoothing's dependence on set order
    (see the #73 result) was fixed later by #103.
