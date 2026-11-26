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
- New issues are numbered on (next: #155). An open one is listed under
  "Open issues" here; once fixed, its entry and test results move to
  `docs/claude-history.md` (Known issues, Test results).

## Testing method

1. **Unit tests:** `venv\Scripts\python.exe -m pytest` (repo root, ~30 s,
   867 tests on test f361e0c). `tests/conftest.py` switches to an empty
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
   `G:\Ortho4XP_baseline\+55+012_Arc_ZL17_test-f361e0c_frozen\` (since
   #151/#152; mesh 879,155 triangles, no WARNING; its OSM caches come
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
   `osm_ab.py` (above), `sim_custom_dem_gap.py`, `sim_batch_cleaning.py`, `check_overpass_slot.py`,
   `check_step3_provider.py`, `probe_mesh.py`, `pe_stack.py`,
   `fetch_osm_api.py`, `fix_dem_folders.py`, `verify_copy.py`,
   `scan_dsf_pools.py <Tiles dir>` (#146 check, read only), the
   data-processing evaluation `eval_*.py`, `trace_lake.py`,
   `probe_point.py` (ws `G:\Ortho4XP_tests\eval\ws`, see the history),
   `profile_steps.py 1|2.5 [src] [--verify-encroach]` (cProfile of
   step 1 or 2.5 in the regression ws, after a regression run).
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
  airports (3 km, apt_smoothing_pix 8), XP12 water, use_decal_on_terrain,
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
- Imagery: GO2 by default (ZL16, ZL15 in the Arctic), Arc/BI fill GO2's
  404s (#117). Denmark: DFA (Dataforsyningen over GO2) in 23 tile configs.
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
- `keep_dsf_backup` is on (default); the old `.dsf.bak` files were
  deleted in the 2026-11-25 cleanup.

## Current state (2026-11-26)

- `test` f361e0c, not on `dev` yet: #144-#149 from the evaluation of
  how data are processed, #150-#154 (867 unit tests, regression PASS,
  sims 15/15). #146 hit 31 built tiles
  (`G:\Ortho4XP_tests\eval\scan146_tiles.txt`), rebuilt in batch r01
  with #146 over dev: 25 built, 6 failed in step 3 (#153/#154; they keep their old DSF:
  +39-108, +43-066, +50-120, +61+008, +60+006, +45-064) and need steps
  1-3 once `test` is on `dev`. After #151/#152 every tile's water and
  big_roads caches are made again from the store at its next step 1.

- `dev` 08036b3, pushed: issues #1-#143 fixed, dead code and unused
  data removed, provider errors logged, step 1 ~17% faster (806 unit
  tests, regression PASS, sims 15/15).
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
  d74d672_frozen, 4ada1bc_frozen, 000880d_frozen (old) and
  f361e0c_frozen (current).

## Open issues

None.

## Coding style

- PEP 8, with comments explaining *why*, not *what*.
- Keep changes minimal and behaviour-preserving unless the change is the fix.
- Prefer `os.path`/`pathlib` over string path concatenation.
- Use the project's own `UI.vprint` / `UI.lvprint` for messages, not `print`.
- Files written by Ortho4XP that another run reads: write to
  `FNAMES.temp_path_for(...)` and `os.replace` (an interrupted write must
  not leave a cut file that is reused).
