#!/usr/bin/env python3
import sys
import os
import traceback
import json

Ortho4XP_dir = '..' if getattr(sys, 'frozen', False) else '.'

if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    _proj_data_path = os.path.join(sys._MEIPASS, "pyproj", "proj_dir", "share", "proj")
    _lib_path = os.path.join(sys._MEIPASS, "_internal")
    os.environ["PROJ_DATA"] = _proj_data_path
    os.environ["DYLD_LIBRARY_PATH"] = _lib_path + ":" + os.environ.get("DYLD_LIBRARY_PATH", "")

from pyproj import datadir

if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    datadir.set_data_dir(_proj_data_path)

sys.path.append(os.path.join(Ortho4XP_dir, 'src'))

import O4_File_Names as FNAMES
sys.path.append(FNAMES.Provider_dir)
import O4_Imagery_Utils as IMG
import O4_Vector_Map as VMAP
import O4_Mesh_Utils as MESH
import O4_Mask_Utils as MASK
import O4_Tile_Utils as TILE
import O4_GUI_Utils as GUI
import O4_UI_Utils as UI
import O4_Config_Utils as CFG  # CFG imported last because it can modify other modules variables

cmd_line = "USAGE: Ortho4XP.py lat lon imagery zl (won't read a tile config)\n  OR:  Ortho4XP.py lat lon (with existing tile config file)"

if __name__ == '__main__':
    UI.safe_console_streams()
    if not os.path.isdir(FNAMES.Utils_dir):
        print("Missing ", FNAMES.Utils_dir, "directory, check your install. Exiting.")
        sys.exit(1)
    for directory in (FNAMES.Preview_dir, FNAMES.Provider_dir, FNAMES.Extent_dir, FNAMES.Filter_dir, FNAMES.OSM_dir,
                      FNAMES.Mask_dir, FNAMES.Imagery_dir, FNAMES.Elevation_dir, FNAMES.Geotiff_dir, FNAMES.Patch_dir,
                      FNAMES.Tile_dir, FNAMES.Tmp_dir):
        if not os.path.isdir(directory):
            try:
                os.makedirs(directory)
                print("Creating missing directory", directory)
            except OSError as e:
                print("Could not create required directory", directory, f"({e}). Exit.")
                sys.exit(1)
    IMG.initialize_extents_dict()
    IMG.initialize_color_filters_dict()
    IMG.initialize_providers_dict()
    IMG.initialize_combined_providers_dict()
    if len(sys.argv) == 1:  # switch to the graphical interface
        Ortho4XP = GUI.Ortho4XP_GUI()
        Ortho4XP.mainloop()
        print("Bon vol!")
    elif sys.argv[1] == "--batch-worker":
        # One tile of a parallel batch build, started by
        # TILE.build_tile_list: lat lon flags [custom_build_dir [context]]
        try:
            if len(sys.argv) > 6:
                # Provider, zoomlevel and custom zones picked in the GUI
                # (see TILE._build_tile_list_parallel); Tile() copies the
                # CFG globals.
                with open(sys.argv[6], encoding="utf-8") as f:
                    context = json.load(f)
                CFG.default_website = context["default_website"]
                CFG.default_zl = context["default_zl"]
                CFG.zone_list = context["zone_list"]
            tile = CFG.Tile(int(sys.argv[2]), int(sys.argv[3]),
                            sys.argv[5] if len(sys.argv) > 5 else '')
            sys.exit(TILE.batch_worker(tile, sys.argv[4]))
        except SystemExit:
            raise
        except Exception:
            traceback.print_exc()
            print("Crash!")
            sys.exit(2)
    else:  # sequel is only concerned with command line
        # A usage error exits 2 (as argparse does): it used to exit 0, so a
        # script driving builds took a typo for a successful build.
        if len(sys.argv) < 3:
            print(cmd_line); sys.exit(2)
        try:
            lat = int(sys.argv[1])
            lon = int(sys.argv[2])
        except ValueError:
            print(cmd_line); sys.exit(2)
        if len(sys.argv) == 3:
            # This form builds from the tile's own config. Tile() alone only
            # holds the global defaults (no provider, no zoom level), which
            # built a tile without imagery and still exited 0.
            tile = CFG.Tile(lat, lon, '')
            tile_cfg = os.path.join(
                tile.build_dir,
                "Ortho4XP_" + FNAMES.short_latlon(lat, lon) + ".cfg",
            )
            if not os.path.isfile(tile_cfg) or not tile.read_from_config(tile_cfg):
                print("ERROR: could not read tile config file", tile_cfg)
                sys.exit(1)
        else:
            try:
                provider_code = sys.argv[3]
                zoomlevel = int(sys.argv[4])
                tile = CFG.Tile(lat, lon, '')
                tile.default_website = provider_code
                tile.default_zl = zoomlevel
            except (IndexError, ValueError):
                print(cmd_line); sys.exit(2)
        try:
            # Each step raises UI.red_flag when it fails or is interrupted;
            # don't run the next step on top of missing or stale data, and
            # exit non-zero so that scripts driving batch builds can tell.
            # A step that returns 0 failed even when it did not raise the
            # flag (e.g. Triangle4XP giving up): the next step would then run
            # on the files of a previous build.
            for step in (VMAP.build_poly_file, MESH.build_mesh,
                         MASK.build_masks, TILE.build_tile_retrying_white):
                ok = step(tile)
                if UI.red_flag or not ok:
                    print("Build stopped, see Ortho4XP.log.")
                    sys.exit(1)
                if step is VMAP.build_poly_file and ok == VMAP.SEA_ONLY:
                    print("Open sea, nothing to build.")
                    sys.exit(0)
            print("Bon vol!")
        except Exception:
            traceback.print_exc()
            print("Crash!")
            sys.exit(1)