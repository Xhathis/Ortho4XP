# CLAUDE.md — Ortho4XP fork (Xhathis/Ortho4XP)

Guidance for Claude Code working in this repository. The full history
(every test result, batch, issue #1-#140 in detail, performance
measurements, the old planned order) is in `docs/claude-history.md`:
search it by issue number ("#106") or tool name before re-investigating
something.

## Project

- Fork of Ortho4XP (upstream: shred86 / oscarpilote), used to build orthophoto
  scenery tiles for **X-Plane 12**.
- Goal: find and fix bugs, make the code more robust, and make batch builds
  more error-tolerant. Correctness first, refactors second. Fix the code,
  not the symptom (the user's rule: the same problem will come back on
  other tiles).
- Platform: **Windows only.** Development, builds and testing all happen on
  this machine. Linux/macOS code paths are not tested here; don't break them
  on purpose, but they are not a target (their Triangle4XP was not rebuilt
  for #75).
- Python **3.13** venv (matches the bundled wheels in `Utils/win/`:
  `gdal-3.12.2-cp313`, `scikit_fmm-2025.6.23-cp313`); pyosmium 4.3.2,
  pytest 9.2.0, pyflakes installed.
- Commit identity: `Xhathis <262661273+Xhathis@users.noreply.github.com>`.

## Layout (main parts)

- `Ortho4XP.py` — entry point (GUI by default, also CLI; `--batch-worker`
  for parallel batches).
- `src/O4_*.py` — all live code. Largest modules: `O4_Imagery_Utils`,
  `O4_GUI_Utils`, `O4_Tile_Utils` (steps, batches), `O4_Config_Utils`,
  `O4_Airport_Utils`, `O4_DSF_Utils`, `O4_Vector_Utils`, `O4_Mask_Utils`,
  `O4_OSM_Utils` (Overpass), `O4_Geofabrik` + `O4_OSM_Extract` (local
  extracts), `O4_XP_Airports` (apt.dat flatten, override pack).
- `prepare_osm_extracts.py`, `check_osm_cache.py` — command-line tools.
- `Utils/win/` — bundled Windows tools: `Triangle4XP.exe` (rebuilt here,
  256 MB stack, reports "Steiner points left", #32/#75), `DSFTool.exe`,
  `nvcompress`, `7z.exe`, `moulinette.exe`, plus the wheels above.
- `Providers/`, `Filters/`, `Patches/` — data/config, not code. Patches go
  in `Patches\<10x10>\<tile>\`.
- Concurrency inside a process is threads only; parallel batches run
  separate `--batch-worker` processes.

## Safety rules (must follow)

1. **Never write into X-Plane folders** (`E:\X-Plane 12`, in particular
   `Custom Scenery`). Build output goes only to `G:\Ortho4XP\Tiles`,
   `yOrtho4XP_Overlays`, `yOrtho4XP_Airports` or test folders. The user
   links packs into X-Plane. Never trigger the GUI map's link toggle.
2. Ask before installing or upgrading packages, or changing anything outside
   this repo.
3. Builds are heavy (CPU, RAM, disk, network). Say before starting one, and
   don't start a second one in parallel.
4. Don't delete cached imagery/OSM/DEM data without asking — it is slow to
   re-download.
5. `OSM_data`, `Orthophotos`, `Elevation_data` are junctions to
   `F:\Ortho4XP_data\<name>`: never delete one recursively (it empties the
   F: folder); remove only the link (`rmdir`).
6. `Providers\Denmark\DF.lay` holds the user's personal Dataforsyningen
   token and is gitignored: never commit it, never echo the token, never
   use third-party credentials Dataforsyningen's capabilities embed.
7. Never run code older than #129 from `G:\Ortho4XP`: it would download the
   38 GB of extracts again (the store layout changed).
8. Read-only analysis must stay read-only: `DEM.default_source_has_no_land`
   downloads Viewfinder zones (use `DEM.world_tile_has_land`); unit sims
   set `UI.log = False` (lvprint appends to the user's log).

## Git workflow

- `master` — untouched mirror of upstream. Never commit directly to it.
- `fix/<short-name>` — one topic per branch, small focused commits, edited
  in its own worktree `G:\Ortho4XP_wt\<name>` (the user's checkout stays on
  `dev`, Ortho4XP may be open there). Branch from `dev`.
- `test` (worktree `G:\Ortho4XP_wt\_test`) — `--no-ff` merges of fix
  branches ready for testing.
- `dev` — the production version, run from `G:\Ortho4XP`; fast-forwarded
  to `test` after the checks pass and with the user's OK.
- `docs/claude-md` (worktree `G:\Ortho4XP_wt\_docs`) — this file and
  `docs/claude-history.md`; merged into `test` like a fix branch.
- Once a fix branch is on `dev` and pushed, delete it (local and origin)
  and its worktree. Only `master`, `dev`, `test`, `docs/claude-md` and open
  fix branches should exist.
- One logical change per commit so a regression can be bisected. Mark in
  the message commits that touch Windows-only branches (`sys.platform` /
  `os.name`) or the bundled `.exe` tools, and "CHANGES OUTPUT" when a
  normal build's DSF or masks change (needs a new baseline).
- Commit or push only when the user asks.
- New issues are numbered on (next: #158). An open one is listed under
  "Open issues" here; once fixed, its entry and test results move to
  `docs/claude-history.md` (Known issues, Test results).

## Testing method

1. **Unit tests:** `venv\Scripts\python.exe -m pytest` (repo root, ~30 s,
   889 tests on test 97e4229). `tests/conftest.py` switches to an empty
   temp folder before any O4 module is imported, so tests never touch the
   user's data. Run them before every commit; add a test before changing
   a pure function; new tests should fail on dev where testable.
2. **pyflakes:** `venv\Scripts\python.exe -m pyflakes Ortho4XP.py
   check_osm_cache.py prepare_osm_extracts.py src/O4_*.py tests/*.py` must
   stay at 0 findings.
3. **Regression** (any cwd, ~2 min, exit 0 = PASS):
   `venv\Scripts\python.exe G:\Ortho4XP_tests\tools\regression.py run
   <commit> [--label name] [--overlay <src_dir>]` — builds +55+012 (Arc
   ZL17) in the worktree `G:\Ortho4XP_tests\regression\ws` from frozen
   inputs and compares DSF, 17 masks and app log with the baseline
   `G:\Ortho4XP_baseline\+55+012_Arc_ZL17_test-5a22a0f_frozen\` (since
   #155; mesh 879,142 triangles, no WARNING; its OSM caches come
   from Geofabrik extracts, see BASELINE.txt). `--overlay <wt>\src`
   builds a commit with a fix worktree's uncommitted O4_*.py over it
   (give the src folder: with the worktree root it copies nothing and
   prints "overlay: no difference"). Every input
   is re-hashed afterwards (a download fails the run). Results in
   `G:\Ortho4XP_tests\+55+012_Arc_ZL17_<label>-<sha>\`. Explain every
   difference; an unexplained one is a failure. The order of "Created
   ...png" lines in console.log is not a difference. A new baseline needs
   a new folder (copy inputs\ of the current one, check SHA256SUMS, then
   `regression.py baseline`). The frozen inputs have no apt.dat, so the
   flatten code (#115-#134) does not act there. A change to the OSM
   queries or the tags caches keep makes the frozen caches unfit: test
   it with `osm_ab.py run <label> <commit> [--overlay <src>]` (A/B from
   the same extract copies in `G:\Ortho4XP_tests\osm151`), then freeze
   the new side's caches as the next baseline's inputs.
4. **Sims:** `sims_in_ws.py <commit> [--overlay <src_dir>] all` (~20 min):
   10 CLI failure sims and 5 batch sims in the regression worktree; must
   end "FAILURES: 0". Never run the full-build sims (sim_osm_failure,
   sim_water_geometry_failure, sim_mask_dem_failure, sim_mesh_failure,
   sim_step3_failures, sim_dem_cli, sim_batch) with cwd `G:\Ortho4XP`:
   they would build into the user's +55+012 and use their config and log.
5. **Other tools** in `G:\Ortho4XP_tests\tools\` (details and expected
   results in `docs/claude-history.md`, "Testing method"):
   `sim_overlay.py` (8 cases), `sim_overpass_fallback.py`,
   `sim_dem_failure.py`, `sim_geofabrik_step1.py <commit> 28 -18 --overlay
   <src> --geofabrik-dir <scratch>` (never the user's Geofabrik folder),
   `osm_ab.py` (above), `refresh_pre117_imagery.py` (below),
   `sim_custom_dem_gap.py`, `sim_batch_cleaning.py`, `check_overpass_slot.py`,
   `check_step3_provider.py`, `probe_mesh.py`, `pe_stack.py`,
   `fetch_osm_api.py`, `fix_dem_folders.py`, `verify_copy.py`,
   `scan_dsf_pools.py <Tiles dir>` (#146 check, read only), the
   data-processing evaluation `eval_*.py`, `trace_lake.py`,
   `probe_point.py` (ws `G:\Ortho4XP_tests\eval\ws`, see the history),
   `profile_steps.py 1|2.5 [src] [--verify-encroach]` (cProfile of
   step 1 or 2.5 in the regression ws, after a regression run).
   `tile_lint.py <Tiles dir> [tiles] [--list F] [--json OUT]` (read
   only, reads DSF binaries, ~10 s per 10 M tile; `--dsf F`, `--mesh
   Data<tile>.mesh`): fan hubs (#155), triangle density per 0.001 deg
   cell (#154/#155), slivers, land edges > 2 km, texture UV vs Web
   Mercator (#146; XP12 `_sea` terrains have the UV in planes 7-8; masks
   repeat the texture UV), pools (#153), missing .ter/textures, NaN.
   Run it on every chunk of a batch. Pilot of 2026-11-27 on the built
   DSFs: 4 tiles with #155-class hotspots (+60+006 hub 64,930, +47+011
   3,360, +64-052 728, +82-039 7,040), all clean when meshed with test
   5a22a0f (hubs 86/61/29/156); everything else within the limits.
6. **In `G:\Ortho4XP`** (the user's folder, other tiles): `gui_smoke.py
   [src_dir]` (7 checks; hash-check `.last_gui_params.txt`, `Ortho4XP.cfg`
   and `Ortho4XP.log` before and after, the GUI must be closed),
   `gui_leftover.py`, `test_batch_order.py` and `test_parallel_batch.py`
   (run the latter from the `_test` worktree with junctions to the F:
   caches, see the history).
7. Test builds of real tiles go to `G:\Ortho4XP_tests\<tile>_...` or are
   batches of the user's tiles (below).

## The user's data and settings

- Drives: G: 13 TB USB disk (repo, Tiles, overlays, test folders), F:
  NVMe (`F:\Ortho4XP_data`: OSM_data, Orthophotos, Elevation_data via the
  junctions). X-Plane 12 at `E:\X-Plane 12`.
- `Ortho4XP.cfg` (gitignored, the user's): curvature_tol 0.25,
  limit_tris 10 (40 made X-Plane hang loading 650 MB DSFs), mesh_zl 18,
  min_angle 10, mask_zl 16, road_level 5, airport cover ZL18 for all
  airports (3 km, apt_smoothing_pix 8), XP12 water with
  imprint_masks_to_dds (since 2026-11-26), use_decal_on_terrain,
  distance_masks_too, batch_parallel_tiles 3, cleaning_level 3,
  max_download_slots 2, osm_source geofabrik, osm_cache_max_age 30,
  imagery_fallback Arc, BI (default), custom_overlay_src = X-Plane 12
  Global Scenery, custom_overlay_src_alternate = X-Plane 12 Demo Areas,
  overpass_server_choice DE. Never leave a test config in place; backups of
  changed configs go to `G:\Ortho4XP_tests\cfg_backups\<date>_<name>`
  with SHA256SUMS.
- **Tile configs win over the global cfg** (provider, ZL, zones and every
  tile setting). A changed global setting reaches an existing tile only
  when its tile config changes too. A zone or provider change needs steps
  1-3 (the .apt files are gone at cleaning_level 3; step 3 alone would
  drop the airport covers).
- ~1,600 built tiles (Denmark, Faroes, Iceland, Greenland, Norway, Alps,
  Canada, Alaska, Patagonia, islands worldwide). The 9 Danish tiles
  +54..+56 / +010..+012 (GO2 ZL16) are the user's own; the regression
  never touches them.
- Imagery: GO2 by default at ZL16 (1,464 tile configs; 110 mostly ice
  or water tiles stay ZL15), Arc/BI fill GO2's 404s (#117). ZL check
  2026-11-27 (`G:\Ortho4XP_tests\zl_eval_2026-11-27.jsonl`, 12 points
  per tile, z16 against its z15 parent stretched, FFT, cut-off 3;
  stretched+JPEG controls 0.6-1.9): GO2's z16 is real detail wherever it
  exists (8,664 of 8,671 samples on ZL16 tiles, Alaska included; 1,987
  of 1,993 on ZL15 tiles). 252 ZL15 tiles with >= 3 detailed points were
  raised to default_zl/mask_zl 16 in their tile configs (user's OK;
  backup `cfg_backups\2026-11-27_zl16_raise`, list
  `batches\zl16_candidates_2026-11-27.txt`); they get ZL16 when step 3
  runs, and their old *_GO215.dds (~315 GB) then become unused. Denmark: DFA (Dataforsyningen over GO2) in 23 tile configs.
  Faroes: +62-008 GO2 with a FOA ZL18 zone at Vágar. Greenland: 81 ZL18
  zones in 43 tile configs (+ the Nuuk BI zone).
- OSM: Geofabrik extracts in `OSM_data\Geofabrik\extracts\<region
  id>.osm.pbf` (+ extracts.json, index-v1.json); Overpass is the backup
  (DE only, slow; FR answers 403). Only -08+072 (Diego Garcia) still
  needs Overpass; +16-170 is outside every region.
  `prepare_osm_extracts.py --tile-file F [--force] [--dry-run]` plans or
  prepares layers; `--store` manages the store.
- Airports X-Plane flattens: built flat with a 100 m ramp (#115-#134);
  their gateway entries minus "1302 flatten 1", with their Global Airports
  3D, are in the pack `G:\Ortho4XP\yOrtho4XP_Airports` (73 airports on
  2026-11-25), rewritten at the end of each batch; linked in Custom
  Scenery above Global Airports.
- Batches: `G:\Ortho4XP_tests\batches\batch_run.py <list> <zl>` (cwd
  `G:\Ortho4XP`; steps 1-3 + overlays with the tile configs, GO2 at <zl>
  for fresh tiles), `then_run.ps1` chains one after another; lists, logs
  and pre-check reports in that folder. `.last_batch_tiles.txt` holds a
  running batch's unfinished tiles (the GUI's tile window selects them).
  Full rebuild: `batches\run_chunks.ps1 -Lists <p00>,<f01>,...` runs per
  chunk refresh_pre117_imagery.py --apply, batch_run.py, tile_lint.py
  and `tools\unused_textures.py` (dry run: textures and .ter files the
  tile's current DSF no longer uses; --apply only with the user's OK);
  it stops before the next chunk on a failed tile, a flagged tile or an
  abnormal end. Summary: `batches\run_chunks.summary.log`.
- `keep_dsf_backup` is on (default); the old `.dsf.bak` files were
  deleted in the 2026-11-25 cleanup.

## Current state (2026-11-27)

- `dev` 26aeb23 (2026-11-26), not pushed: issues #1-#154 fixed (867
  unit tests, regression PASS, sims 15/15). After #151/#152 every
  tile's water and big_roads caches are made again from the store at
  its next step 1.
- `test` 97e4229 (+ the docs merge after it) = dev + #155, #156, #157
  (889 tests, regression PASS on 5a22a0f_frozen). dev waits for the
  user's X-Plane look at +60+006 and the limit_tris 10/15 decision.
- XP12 water switched on 2026-11-26 (the user viewed test tile
  +18-065): `imprint_masks_to_dds=True` in Ortho4XP.cfg and all 1,597
  tile configs (only that line; backup
  `cfg_backups\2026-11-26_imprint_masks`). A tile gets it when step 3
  runs: every masked texture under 20 MB (DXT1) is downloaded again and
  written as DXT5 (`O4_DSF_Utils`, "Maybe target_tex was a DXT1"), ~1 TB
  in all. Tiles not rebuilt yet keep overlay water.
- Full rebuild: batch r01 (the 31 #146 tiles, 2026-11-26): 25 built, 6
  failed in step 3 (#153/#154), rebuilt in r01b
  (`batches\rebuild_2026-11-26_r01b.txt`) on dev fdf7628 with XP12
  water: 6 built, 0 failed, 19 min; largest pool 37,817 (+39-108) and
  46,030 (+43-066), no overflow pool needed; 54-89 DXT5 textures on
  the 4 coastal tiles. The 25 tiles r01 built (before #151-#154 and XP12
  water) are list r10. Lists r02-r10 are superseded (2026-11-27): #155
  changes every tile, so `batches\full_2026-11-27_p00.txt` (28 pilot
  tiles chosen for diversity, the reason on each line) and f01-f08 (200
  each, by 10x10 block) cover all 1,597 tiles once. Not started: the
  user wants the full run only when confident; proposed a pilot plus an
  automated output check (fan hubs, UVs, pools, sea/lake levels,
  density) on every chunk.
- Readiness review 2026-11-26 for the full rebuild: no code change left
  open; every tile setting equals the global cfg except provider/ZL
  (GO2 ZL16, GO2 ZL15 on 362 tiles with mask_zl 15 - 252 raised to
  ZL16 on 2026-11-27 - DFA on 23).
  **Imagery:** 798 tiles have GO2 textures (ZL >= 16) from before #117,
  whose GO2 404s were filled with GO2's own lower levels (blurry
  patches, seen in +66+015; after #117, 8% of ZL16 textures needed
  Arc/BI). The user chose to fetch them all again: before each chunk
  run `G:\Ortho4XP_tests\tools\refresh_pre117_imagery.py <list>
  --apply` (cwd G:\Ortho4XP; deletes those DDS made before 2026-11-20
  and their JPGs; dry run without --apply): 195,531 DDS, ~2.2 TB to
  download again. **Mesh:** 874 tiles used the whole limit_tris budget
  (10 M). Test +60+006 at 15 M (`G:\Ortho4XP_tests\xp12water\ws`,
  dev 26aeb23, textures copied from the user's tile): still capped at
  15.1 M, DSF 177 -> 244 MB, land RMSE vs DEM 1.56 -> 1.15 m, p99 5.31
  -> 3.90 m. The user's first X-Plane check (6 min load, streaked lake)
  found #155; that tile is rebuilt with #155 (235 MB) for a second
  check before any limit_tris change. Also seen there: max_levelled_segs (200000)
  reached, 1,048 roads not levelled (#150 NOTE).
- Last batches: E (121 wilderness tiles, ZL16) and 4 ZL15 holes, 124
  built, 0 failed (2026-11-25); then +69-052 for the Qeqertaq zone (#140):
  both zones on GO218, so every zone tile is on its zone's imagery.
- OSM caches pass 30 days from 2026-12-08 (most 12-14..12-24); a refresh
  happens only when a tile's step 1 runs. All 167 extracts a refresh of
  every tile needs are in the store (36.4 GB).
- Full audit and cleanup 2026-11-25 (log
  `G:\Ortho4XP_tests\cleanup_2026-11-25.log`): 1,358.9 GB freed (JPGs of
  built tiles, all masks, .dsf.bak/.cfg.bak, old sims and baselines).
  All 1,598 tiles complete (one DSF, all textures). Baselines:
  d74d672_frozen, 4ada1bc_frozen, 000880d_frozen, f361e0c_frozen
  (old) and 5a22a0f_frozen (current, #155).

## Open issues

- **#155 near-coincident vertices (CHANGES OUTPUT)**, branch
  `fix/near-vertex-snap` (worktree `G:\Ortho4XP_wt\near-vertex-snap`,
  from dev 26aeb23), commit a180391, merged into `test` 5a22a0f (not dev; 874 passed, regression PASS
  on the new baseline 5a22a0f_frozen, sims 15/15). Seen by the user in test tile
  +60+006 (15 M): black lake with white radial streaks at 60.6393 N,
  6.6525 E, 6 min load. Cause: a lake way and a water multipolygon have
  their own nodes 1e-7 deg apart (one OSM unit); both edges leave the
  same vertex, a 52 m sliver with a 0.0001 deg angle, which Triangle4XP
  filled with 265,000 points (one vertex shared by 65,000 water
  triangles). In the 10 M DSF too, so in the user's own tile. #154
  snaps a vertex near the middle of a segment but not one near an end.
  Fix: `Vector_Map.insert_node` returns an existing vertex within
  SNAP_TOL (2e-7 deg, a grid of that cell size, 3x3 lookup); points
  within SNAP_TOL of the tile edge go onto it, and a border point never
  merges with an inner one; the grid is rebuilt in `snap_to_grid`.
  7 tests in `tests/test_near_vertex_snap.py` (5 fail on dev). Results:
  874 passed, pyflakes 0; +60+006 at 15 M rebuilt in the xp12water ws:
  53 vertices merged, water fan hubs (>= 40 triangles) 3,624 -> 3
  (largest 87), DSF 244 -> 235 MB, 10 input angles < 0.5 deg left in the
  tile, no edge > 2 km, UVs fine. Regression: 9 vertices merged,
  879,155 -> 879,142 triangles, masks and log identical (a new baseline
  after the commit). Every tile changes at its next step 2.
- **#156 extract update killed: temp file locked (Windows only)**, branch
  `fix/update-temp-file` (worktree `G:\Ortho4XP_wt\update-temp-file`,
  from dev 26aeb23), commit 3b0b848, merged into `test` 97e4229 (not
  dev). Found from the user's 3 stop tests
  (2026-11-27 05:11-05:13): a 0-byte `.tmp..._isole.osm.pbf` stayed in
  the extract store. `GEOFABRIK._update` ran pyosmium with
  sys.executable = the venv's python.exe, a launcher that runs the
  interpreter as its own child; on Stop or UPDATE_TIMEOUT proc.kill()
  ended the launcher, the interpreter released the -o file a moment
  later, so os.remove raised PermissionError (WinError 32, 30 of 30
  tries) and replaced Stopped; on a timeout prepare_tiles took the
  usable extract for missing (its tiles to Overpass). Fix: `_kill_tree`
  (taskkill /T /F, then the file is free at once, 30 of 30) and
  `_remove_temp` (never raises; a file that cannot go is removed by the
  next ensure_extract), also in `_download`'s cleanup. 3 tests (fail on
  dev with the PermissionError), 870 passed, pyflakes 0. Output
  unchanged. Regression on test + overlay PASS (DSF, masks, log
  identical), sim_geofabrik_step1 +28-018 (scratch store with a copy of
  canary-islands) 0 failures. Other two leftovers: `.tmp…_bourgogne` (4 MB) from closing
  Ortho4XP mid-download; both go at the next use of the region.
- **#157 tile check built into step 3**, branch `fix/tile-check`
  (worktree `G:\Ortho4XP_wt\tile-check`, from dev 26aeb23), commit
  a634d72, merged into `test` 97e4229 (not dev). The user: Ortho4XP should be a one-stop shop, other users
  have no Claude Code during batches. New `src/O4_Tile_Check.py` (the
  checks of `tools/tile_lint.py` minus slivers and pool stats): after
  the DSF is activated and the cleaning, step 3 reads it back and logs
  `WARNING: tile check <tile>: ...` with the place for hubs > 400,
  > 6000 triangles per 0.001 deg cell, texture/mask
  UV > 4 texels off or outside 0-1, missing .ter/textures, NaN, or an
  unreadable DSF; the tile stays built. Never raises. Result file
  `Ortho4XP_<tile>_check.txt` in the tile folder ("ok" or the warnings,
  temp + os.replace); `_batch_summary` lists "Tile check warnings: N
  tile(s)" / "CHECK: <tile>: ..." for this batch's results (mtime >=
  batch start; workers' too). App setting `tile_check` (UI, default
  True). Clean tile: console "Tile check: ok (x s)", app log unchanged.
  12 tests (`tests/test_tile_check.py`, synthetic DSF writer; fail on
  dev), 879 passed, pyflakes 0. Same numbers as tile_lint on +60+006
  (both 15 M and 10 M flagged: hub 64,930), +18-065, +46-054, +82-039
  (hub 7,040 flagged); 12 s and 1.8 GB peak on the 15 M tile, 1 s and
  140 MB on 1.3 M. Regression on test 7453c3d + overlay (scratch src =
  this worktree + test's O4_Vector_Utils): PASS, DSF byte-identical,
  log identical, check 1.8 s; sims 15/15. `test` 97e4229: 889 passed,
  pyflakes 0, regression PASS. `batches/run_chunks.ps1` also stops on
  the batch log's "Tile check warnings" line. Long-edge check removed
  (commit 0c3110b, on test b2d228c: 890 passed, regression PASS): the
  census's 20 "long" tiles were all flat ground (Cairo and Fuerteventura
  airports built flat, Grays/Mud Lake, Potholes, sea-level deltas and
  flats at 0.0 m) where Triangle4XP, refining by curvature only, makes
  texture-square triangles (2.0-2.8 km); a triangle past its texture
  shows as uv_range anyway. tile_lint reports `long` as information only.

## Coding style

- PEP 8, with comments explaining *why*, not *what*.
- Keep changes minimal and behaviour-preserving unless the change is the fix.
- Prefer `os.path`/`pathlib` over string path concatenation.
- Use the project's own `UI.vprint` / `UI.lvprint` for messages, not `print`.
- Files written by Ortho4XP that another run reads: write to
  `FNAMES.temp_path_for(...)` and `os.replace` (an interrupted write must
  not leave a cut file that is reused).
