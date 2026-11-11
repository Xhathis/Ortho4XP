import time
import sys
import os
import pickle
import subprocess
import numpy
import requests
from math import sqrt, cos, pi
import O4_DEM_Utils as DEM
import O4_UI_Utils as UI
import O4_File_Names as FNAMES
import O4_Geo_Utils as GEO
import O4_Vector_Utils as VECT
import O4_OSM_Utils as OSM

if "dar" in sys.platform:
    Triangle4XP_cmd = os.path.join(FNAMES.Utils_dir, "mac", "Triangle4XP ")
    triangle_cmd = os.path.join(FNAMES.Utils_dir, "mac", "triangle ")
    sort_mesh_cmd = os.path.join(FNAMES.Utils_dir, "mac", "moulinette ")
    unzip_cmd = os.path.join(FNAMES.Utils_dir, "mac", "7zz")
    if not os.path.exists(unzip_cmd):
        unzip_cmd = "7z"
elif "win" in sys.platform:
    Triangle4XP_cmd = os.path.join(FNAMES.Utils_dir, "win", "Triangle4XP.exe ")
    triangle_cmd = os.path.join(FNAMES.Utils_dir, "win", "triangle.exe ")
    sort_mesh_cmd = os.path.join(FNAMES.Utils_dir, "win", "moulinette.exe ")
    unzip_cmd = os.path.join(FNAMES.Utils_dir, "win", "7z.exe")
else:
    Triangle4XP_cmd = os.path.join(FNAMES.Utils_dir, "lin", "Triangle4XP ")
    triangle_cmd = os.path.join(FNAMES.Utils_dir, "lin", "triangle ")
    sort_mesh_cmd = os.path.join(FNAMES.Utils_dir, "lin", "moulinette ")
    unzip_cmd = "7z "


community_server = False
if os.path.exists(FNAMES.resource_path("community_server.txt")):
    try:
        # with: a module-level f stayed open as long as Ortho4XP ran.
        with open(FNAMES.resource_path("community_server.txt"), "r") as f:
            lines = f.readlines()
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if "#" in line:
                if line[0] == "#":
                    continue
                else:
                    line = line.split("#")[0].strip()
            if not line:
                continue
            community_server = True
            community_prefix = line
            break
    except (OSError, UnicodeDecodeError):
        pass


def community_mesh(tile):
    if not community_server:
        UI.exit_message_and_bottom_line(
            "\nERROR: No community server defined in community_server.txt"
        )
        return 0
    url = (
        community_prefix
        + os.path.basename(FNAMES.mesh_file(tile.build_dir, tile.lat, tile.lon))
        + ".7z"
    )
    timer = time.time()
    UI.vprint(0, "Querying", url, "...")
    try:
        r = requests.get(url, timeout=30)
        if r.status_code == 200:
            UI.vprint(0, "We've got something !")
            with open(
                FNAMES.mesh_file(tile.build_dir, tile.lat, tile.lon) + ".7z",
                "wb",
            ) as f:
                f.write(r.content)
            if subprocess.call(
                [
                    unzip_cmd.strip(),
                    "e",
                    "-y",
                    "-o" + tile.build_dir,
                    FNAMES.mesh_file(tile.build_dir, tile.lat, tile.lon)
                    + ".7z",
                ],
                env=UI.subprocess_env(),
            ):
                UI.exit_message_and_bottom_line(
                    "\nERROR: Could not extract community_mesh from archive."
                )
                return 0
            os.remove(
                FNAMES.mesh_file(tile.build_dir, tile.lat, tile.lon) + ".7z"
            )
            UI.timings_and_bottom_line(timer)
            return 1
        elif 400 <= r.status_code < 500:
            UI.exit_message_and_bottom_line(
                "\nSORRY: Community server does not propose that mesh: "
                + str(r)
            )
            return 0
        elif r.status_code >= 500:
            UI.exit_message_and_bottom_line(
                "\nSORRY: Community server seems to be down or struggling: "
                + str(r)
            )
            return 0
        else:
            UI.exit_message_and_bottom_line(
                "\nSORRY: Community server seems to be down or struggling: "
                + str(r)
            )
            return 0
    except Exception as e:
        UI.exit_message_and_bottom_line(
            "\nERROR: Network or server unreachable:\n" + str(e)
        )
        return 0


##############################################################################
def is_in_region(lat, lon, latmin, latmax, lonmin, lonmax):
    return lat >= latmin and lat <= latmax and lon >= lonmin and lon <= lonmax


##############################################################################


##############################################################################
def build_curv_tol_weight_map(tile, weight_array):
    if tile.apt_curv_tol != tile.curvature_tol and tile.apt_curv_tol > 0:
        UI.vprint(
            1, "-> Modifying curv_tol weight map according to runway locations."
        )
        try:
            with open(FNAMES.apt_file(tile), "rb") as f:
                dico_airports = pickle.load(f)
        except (OSError, EOFError, pickle.UnpicklingError):
            UI.lvprint(
                1,
                "   WARNING: File",
                FNAMES.apt_file(tile),
                "is missing (erased after Step 1?), cannot check airport info ",
                "for upgraded zoomlevel.",
            )
            dico_airports = {}
        for airport in dico_airports:
            (xmin, ymin, xmax, ymax) = dico_airports[airport]["boundary"].bounds
            x_shift = 1000 * tile.apt_curv_ext * GEO.m_to_lon(tile.lat)
            y_shift = 1000 * tile.apt_curv_ext * GEO.m_to_lat
            colmin = max(round((xmin - x_shift) * 1000), 0)
            colmax = min(round((xmax + x_shift) * 1000), 1000)
            rowmax = min(round(((1 - ymin) + y_shift) * 1000), 1000)
            rowmin = max(round(((1 - ymax) - y_shift) * 1000), 0)
            weight_array[rowmin : rowmax + 1, colmin : colmax + 1] = (
                tile.curvature_tol / tile.apt_curv_tol
            )
    # The coastline can only change the map where its ratio is above the
    # current weight (numpy.maximum below). With a coast_curv_tol at or
    # above curvature_tol it usually changes nothing, and loading (or
    # downloading) the coastline in every step 2 was wasted (#55).
    if (
        tile.coast_curv_tol > 0
        and tile.curvature_tol / tile.coast_curv_tol > weight_array.min()
    ):
        UI.vprint(
            1,
            "-> Modifying curv_tol weight map according to coastline location.",
        )
        sea_layer = OSM.OSM_layer()
        custom_coastline = FNAMES.custom_coastline(tile.lat, tile.lon)
        custom_coastline_dir = FNAMES.custom_coastline_dir(tile.lat, tile.lon)
        if os.path.isfile(custom_coastline):
            UI.vprint(1, "    * User defined custom coastline data detected.")
            sea_layer.update_dicosm(
                custom_coastline, input_tags=None, target_tags=None
            )
        elif os.path.isdir(custom_coastline_dir):
            UI.vprint(
                1,
                "    * User defined custom coastline data detected ",
                "(multiple files).",
            )
            if not OSM.read_custom_osm_dir(
                sea_layer, custom_coastline_dir, custom_coastline
            ):
                return 0
        else:
            queries = ['way["natural"="coastline"]']
            tags_of_interest = []
            if not OSM.OSM_queries_to_OSM_layer(
                queries,
                sea_layer,
                tile.lat,
                tile.lon,
                tags_of_interest,
                cached_suffix="coastline",
            ):
                UI.lvprint(
                    0, "   ERROR: Could not get the coastline for the",
                    "coast_curv_tol weight map, stopping.",
                )
                return 0
        for nodeid in sea_layer.dicosmn:
            (lonp, latp) = [float(x) for x in sea_layer.dicosmn[nodeid]]
            if (
                lonp < tile.lon
                or lonp > tile.lon + 1
                or latp < tile.lat
                or latp > tile.lat + 1
            ):
                continue
            x_shift = 1000 * tile.coast_curv_ext * GEO.m_to_lon(tile.lat)
            y_shift = tile.coast_curv_ext / (111.12)
            colmin = max(round((lonp - tile.lon - x_shift) * 1000), 0)
            colmax = min(round((lonp - tile.lon + x_shift) * 1000), 1000)
            rowmax = min(round((tile.lat + 1 - latp + y_shift) * 1000), 1000)
            rowmin = max(round((tile.lat + 1 - latp - y_shift) * 1000), 0)
            weight_array[
                rowmin : rowmax + 1, colmin : colmax + 1
            ] = numpy.maximum(
                weight_array[rowmin : rowmax + 1, colmin : colmax + 1],
                tile.curvature_tol / tile.coast_curv_tol,
            )
        del sea_layer
    # It could be of interest to write the weight file as a png for user
    # editing from PIL import Image
    # Image.fromarray((weight_array!=1).astype(numpy.uint8)*255).save(
    # 'weight.png')
    return 1


################################################################################
def post_process_nodes_altitudes(tile):
    dico_attributes = VECT.Vector_Map.dico_attributes
    with open(FNAMES.output_node_file(tile), "r") as f_node:
        init_line_f_node = f_node.readline()
        nbr_pt = int(init_line_f_node.split()[0])
        vertices = numpy.zeros(6 * nbr_pt)
        UI.vprint(1, "-> Loading of the mesh computed by Triangle4XP.")
        for i in range(0, nbr_pt):
            vertices[6 * i : 6 * i + 6] = [
                float(x) for x in f_node.readline().split()[1:7]
            ]
        end_line_f_node = f_node.readline()
    UI.vprint(1, "-> Post processing of altitudes according to vector data")
    f_ele = open(FNAMES.output_ele_file(tile), "r")
    nbr_tri = int(f_ele.readline().split()[0])
    water_tris = set()
    sea_tris = set()
    interp_alt_tris = set()
    for i in range(nbr_tri):
        line = f_ele.readline()
        # triangle attributes are powers of 2, except for the dummy attributed
        # which doesn't require post-treatment
        if line[-2] == "0":
            continue
        (v1, v2, v3, attr) = [int(x) - 1 for x in line.split()[1:5]]
        attr += 1
        if attr >= dico_attributes["INTERP_ALT"]:
            interp_alt_tris.add((v1, v2, v3))
        elif attr & dico_attributes["SEA"]:
            sea_tris.add((v1, v2, v3))
        elif (
            attr & dico_attributes["WATER"]
            or attr & dico_attributes["SEA_EQUIV"]
        ):
            water_tris.add((v1, v2, v3))
    f_ele.close()  # was never closed
    if tile.water_smoothing:
        UI.vprint(1, "   Smoothing inland water.")
        for j in range(tile.water_smoothing):
            for v1, v2, v3 in water_tris:
                zmean = (
                    vertices[6 * v1 + 2]
                    + vertices[6 * v2 + 2]
                    + vertices[6 * v3 + 2]
                ) / 3
                vertices[6 * v1 + 2] = zmean
                vertices[6 * v2 + 2] = zmean
                vertices[6 * v3 + 2] = zmean
    UI.vprint(1, "   Smoothing of sea water.")
    for v1, v2, v3 in sea_tris:
        if tile.sea_smoothing_mode == "zero":
            vertices[6 * v1 + 2] = 0
            vertices[6 * v2 + 2] = 0
            vertices[6 * v3 + 2] = 0
        elif tile.sea_smoothing_mode == "mean":
            zmean = (
                vertices[6 * v1 + 2]
                + vertices[6 * v2 + 2]
                + vertices[6 * v3 + 2]
            ) / 3
            vertices[6 * v1 + 2] = zmean
            vertices[6 * v2 + 2] = zmean
            vertices[6 * v3 + 2] = zmean
        else:
            vertices[6 * v1 + 2] = max(vertices[6 * v1 + 2], 0)
            vertices[6 * v2 + 2] = max(vertices[6 * v2 + 2], 0)
            vertices[6 * v3 + 2] = max(vertices[6 * v3 + 2], 0)
    UI.vprint(1, "   Treatment of airports, roads and patches.")
    for v1, v2, v3 in interp_alt_tris:
        vertices[6 * v1 + 2] = vertices[6 * v1 + 5]
        vertices[6 * v2 + 2] = vertices[6 * v2 + 5]
        vertices[6 * v3 + 2] = vertices[6 * v3 + 5]
        vertices[6 * v1 + 3] = 0
        vertices[6 * v2 + 3] = 0
        vertices[6 * v3 + 3] = 0
        vertices[6 * v1 + 4] = 0
        vertices[6 * v2 + 4] = 0
        vertices[6 * v3 + 4] = 0
    UI.vprint(1, "-> Writing output nodes file.")
    with open(FNAMES.output_node_file(tile), "w") as f_node:
        f_node.write(init_line_f_node)
        for i in range(0, nbr_pt):
            f_node.write(
                str(i + 1)
                + " "
                + " ".join(
                    ("{:.15f}".format(x) for x in vertices[6 * i : 6 * i + 6])
                )
                + "\n"
            )
        f_node.write(end_line_f_node)
    return vertices


################################################################################
def write_mesh_file(tile, vertices):
    UI.vprint(
        1,
        "-> Writing final mesh to the file "
        + FNAMES.mesh_file(tile.build_dir, tile.lat, tile.lon),
    )
    with open(FNAMES.output_ele_file(tile), "r") as f_ele:
        nbr_vert = len(vertices) // 6
        nbr_tri = int(f_ele.readline().split()[0])
        f = open(FNAMES.mesh_file(tile.build_dir, tile.lat, tile.lon), "w")
        f.write("MeshVersionFormatted 2\n")
        f.write("Dimension 3\n\n")
        f.write("Vertices\n")
        f.write(str(nbr_vert) + "\n")
        for i in range(0, nbr_vert):
            f.write(
                "{:.15f}".format(vertices[6 * i] + tile.lon)
                + " "
                + "{:.15f}".format(vertices[6 * i + 1] + tile.lat)
                + " "
                + "{:.15f}".format(vertices[6 * i + 2] / 100000)
                + " 0\n"
            )
        f.write("\n")
        f.write("Normals\n")
        f.write(str(nbr_vert) + "\n")
        for i in range(0, nbr_vert):
            f.write(
                "{:.2f}".format(vertices[6 * i + 3])
                + " "
                + "{:.2f}".format(vertices[6 * i + 4])
                + " 0\n"
            )
        f.write("\n")
        f.write("Triangles\n")
        f.write(str(nbr_tri) + "\n")
        for i in range(0, nbr_tri):
            f.write(" ".join(f_ele.readline().split()[1:]) + "\n")
    f.close()
    return


################################################################################
# Build a textured .obj wavefront over the extent of an orthogrid cell
################################################################################
def extract_mesh_to_obj(
    mesh_file, til_x_left, til_y_top, zoomlevel, provider_code
):
    UI.red_flag = False
    timer = time.time()
    (latmax, lonmin) = GEO.gtile_to_wgs84(til_x_left, til_y_top, zoomlevel)
    (latmin, lonmax) = GEO.gtile_to_wgs84(
        til_x_left + 16, til_y_top + 16, zoomlevel
    )
    obj_file_name = FNAMES.obj_file(
        til_x_left, til_y_top, zoomlevel, provider_code
    )
    mtl_file_name = FNAMES.mtl_file(
        til_x_left, til_y_top, zoomlevel, provider_code
    )
    f_mesh = open(mesh_file, "r")
    for i in range(4):
        f_mesh.readline()
    nbr_pt_in = int(f_mesh.readline())
    UI.vprint(1, "    Reading nodes...")
    pt_in = numpy.zeros(5 * nbr_pt_in, "float")
    for i in range(nbr_pt_in):
        pt_in[5 * i : 5 * i + 3] = [
            float(x) for x in f_mesh.readline().split()[:3]
        ]
    for i in range(3):
        f_mesh.readline()
    for i in range(nbr_pt_in):
        pt_in[5 * i + 3 : 5 * i + 5] = [
            float(x) for x in f_mesh.readline().split()[:2]
        ]
    for i in range(0, 2):  # skip 2 lines
        f_mesh.readline()
    if UI.red_flag:
        UI.exit_message_and_bottom_line()
        return 0
    UI.vprint(1, "    Reading triangles...")
    nbr_tri_in = int(f_mesh.readline())  # read nbr of tris
    textured_nodes = {}
    textured_nodes_inv = {}
    nodes_st_coord = {}
    len_textured_nodes = 0
    dico_new_tri = {}
    len_dico_new_tri = 0
    for i in range(0, nbr_tri_in):
        (n1, n2, n3) = [int(x) - 1 for x in f_mesh.readline().split()[:3]]
        (lon1, lat1, z1, u1, v1) = pt_in[5 * n1 : 5 * n1 + 5]
        (lon2, lat2, z2, u2, v2) = pt_in[5 * n2 : 5 * n2 + 5]
        (lon3, lat3, z3, u3, v3) = pt_in[5 * n3 : 5 * n3 + 5]
        if is_in_region(
            (lat1 + lat2 + lat3) / 3.0,
            (lon1 + lon2 + lon3) / 3.0,
            latmin,
            latmax,
            lonmin,
            lonmax,
        ):
            if n1 not in textured_nodes_inv:
                len_textured_nodes += 1
                textured_nodes_inv[n1] = len_textured_nodes
                textured_nodes[len_textured_nodes] = n1
                nodes_st_coord[len_textured_nodes] = GEO.st_coord(
                    lat1, lon1, til_x_left, til_y_top, zoomlevel, provider_code
                )
            n1new = textured_nodes_inv[n1]
            if n2 not in textured_nodes_inv:
                len_textured_nodes += 1
                textured_nodes_inv[n2] = len_textured_nodes
                textured_nodes[len_textured_nodes] = n2
                nodes_st_coord[len_textured_nodes] = GEO.st_coord(
                    lat2, lon2, til_x_left, til_y_top, zoomlevel, provider_code
                )
            n2new = textured_nodes_inv[n2]
            if n3 not in textured_nodes_inv:
                len_textured_nodes += 1
                textured_nodes_inv[n3] = len_textured_nodes
                textured_nodes[len_textured_nodes] = n3
                nodes_st_coord[len_textured_nodes] = GEO.st_coord(
                    lat3, lon3, til_x_left, til_y_top, zoomlevel, provider_code
                )
            n3new = textured_nodes_inv[n3]
            dico_new_tri[len_dico_new_tri] = (n1new, n2new, n3new)
            len_dico_new_tri += 1
    nbr_vert = len_textured_nodes
    nbr_tri = len_dico_new_tri
    if UI.red_flag:
        UI.exit_message_and_bottom_line()
        return 0
    UI.vprint(1, "    Writing the obj file.")
    # first the obj file
    f = open(obj_file_name, "w")
    for i in range(1, nbr_vert + 1):
        j = textured_nodes[i]
        f.write(
            "v "
            + "{:.9f}".format(pt_in[5 * j] - lonmin)
            + " "
            + "{:.9f}".format(pt_in[5 * j + 1] - latmin)
            + " "
            + "{:.9f}".format(pt_in[5 * j + 2])
            + "\n"
        )
    f.write("\n")
    for i in range(1, nbr_vert + 1):
        j = textured_nodes[i]
        f.write(
            "vn "
            + "{:.9f}".format(pt_in[5 * j + 3])
            + " "
            + "{:.9f}".format(pt_in[5 * j + 4])
            + " "
            + "{:.9f}".format(
                sqrt(max(1 - pt_in[5 * j + 3] ** 2 - pt_in[5 * j + 4] ** 2, 0))
            )
            + "\n"
        )
    f.write("\n")
    for i in range(1, nbr_vert + 1):
        j = textured_nodes[i]
        f.write(
            "vt "
            + "{:.9f}".format(nodes_st_coord[i][0])
            + " "
            + "{:.9f}".format(nodes_st_coord[i][1])
            + "\n"
        )
    f.write("\n")
    f.write("usemtl orthophoto\n\n")
    for i in range(0, nbr_tri):
        (one, two, three) = dico_new_tri[i]
        f.write(
            "f "
            + str(one)
            + "/"
            + str(one)
            + "/"
            + str(one)
            + " "
            + str(two)
            + "/"
            + str(two)
            + "/"
            + str(two)
            + " "
            + str(three)
+ "/"
            + str(three)
            + "/"
            + str(three)
            + "\n"
        )
    f_mesh.close()
    f.close()
    # then the mtl file
    with open(mtl_file_name, "w") as f:
        f.write(
            "newmtl orthophoto\nmap_Kd "
            + FNAMES.geotiff_file_name_from_attributes(
                til_x_left, til_y_top, zoomlevel, provider_code
            )
            + "\n"
        )
    UI.timings_and_bottom_line(timer)
    return


################################################################################
def build_mesh(tile):
    if UI.is_working:
        return 0
    UI.is_working = 1
    UI.red_flag = False
    VECT.scalx = cos((tile.lat + 0.5) * pi / 180)
    UI.logprint(
        "Step 2 for tile lat=", tile.lat, ", lon=", tile.lon, ": starting."
    )
    UI.vprint(
        0,
        "\nStep 2 : Building mesh for tile "
        + FNAMES.short_latlon(tile.lat, tile.lon)
        + " : \n--------\n",
    )
    UI.progress_bar(1, 0)
    poly_file = FNAMES.input_poly_file(tile)
    node_file = FNAMES.input_node_file(tile)
    alt_file = FNAMES.alt_file(tile)
    weight_file = FNAMES.weight_file(tile)
    if not os.path.isfile(node_file):
        UI.exit_message_and_bottom_line("\nERROR: Could not find ", node_file)
        return 0
    if not tile.iterate and not os.path.isfile(poly_file):
        UI.exit_message_and_bottom_line("\nERROR: Could not find ", poly_file)
        return 0
    if not tile.iterate:
        if not os.path.isfile(alt_file):
            UI.exit_message_and_bottom_line(
                "\nERROR: Could not find",
                alt_file,
                ". You must run Step 1 first.",
            )
            return 0
        try:
            fill_nodata = tile.fill_nodata or "to zero"
            source = (
                (";" in tile.custom_dem) and tile.custom_dem.split(";")[0]
            ) or tile.custom_dem
            tile.dem = DEM.DEM(
                tile.lat, tile.lon, source, fill_nodata, info_only=True
            )
            if (
                not os.path.getsize(alt_file)
                == 4 * tile.dem.nxdem * tile.dem.nydem
            ):
                UI.exit_message_and_bottom_line(
                    "\nERROR: Cached raster elevation does not match the ",
                    "current custom DEM specs.\n       You must run Step 1 ",
                    "and Step 2 with the same elevation base.",
                )
                return 0
        except Exception as e:
            # The cause used to go to the console only (print), not to
            # Ortho4XP.log: a parallel batch deletes a worker's console log.
            UI.exit_message_and_bottom_line(
                "\nERROR: Could not determine the appropriate source. Please ",
                "check your custom_dem entry.",
                f"({type(e).__name__}: {e})",
            )
            return 0
    else:
        try:
            source = (
                (";" in tile.custom_dem)
                and tile.custom_dem.split(";")[tile.iterate]
            ) or tile.custom_dem
            tile.dem = DEM.DEM(
                tile.lat, tile.lon, source, fill_nodata=False, info_only=True
            )
            if (
                not os.path.isfile(alt_file)
                or not os.path.getsize(alt_file)
                == 4 * tile.dem.nxdem * tile.dem.nydem
            ):
                tile.dem = DEM.DEM(
                    tile.lat,
                    tile.lon,
                    source,
                    fill_nodata=False,
                    info_only=False,
                )
                tile.dem.write_to_file(FNAMES.alt_file(tile))
        except Exception as e:
            # The cause used to go to the console only (print), not to
            # Ortho4XP.log: a parallel batch deletes a worker's console log.
            UI.exit_message_and_bottom_line(
                "\nERROR: Could not determine the appropriate source. Please ",
                "check your custom_dem entry.",
                f"({type(e).__name__}: {e})",
            )
            return 0
    try:
        with open(node_file, "r") as f:
            input_nodes = int(f.readline().split()[0])
    except (OSError, ValueError, IndexError):
        UI.exit_message_and_bottom_line("\nERROR: In reading ", node_file)
        return 0

    timer = time.time()
    tri_verbosity = "Q" if UI.verbosity <= 1 else "V"
    output_poly = "P" if UI.cleaning_level else ""
    do_refine = "r" if tile.iterate else "A"
    try:
        max_tris = float(tile.limit_tris) * 1e6
    except (TypeError, ValueError):
        UI.lvprint(1, "   WARNING: limit_tris wrongly set, defaults to 5M.")
        max_tris = 5e6
    if max_tris <= 0 or max_tris >= 5e7:
        max_tris = 5e6
    max_steiner = max_tris / 1.9 - input_nodes
    max_steiner = max(max_steiner, 5e5)

    limit_tris = "S" + str(max_steiner)
    Tri_option = (
        "-pq" + "{:.9g}".format(tile.min_angle) + do_refine + 
        "uYB" + tri_verbosity + output_poly + limit_tris
    )

    weight_array = numpy.ones((1001, 1001), dtype=numpy.float32)
    if not build_curv_tol_weight_map(tile, weight_array):
        # Meshing on without it ignored coast_curv_tol silently (#55).
        UI.exit_message_and_bottom_line("")
        UI.red_flag = True
        return 0
    weight_array.tofile(weight_file)
    del weight_array

    # Hack
    # Better meshes by not modifying curv_tol but having limit_tris set
    # tu a reasonable value.
    # curv_tol_scaling = sqrt(tile.dem.nxdem / (3601 * (tile.dem.x1 - tile.dem.x0))
    # )

    mesh_cmd = [
        Triangle4XP_cmd.strip(),
        Tri_option.strip(),
        "{:.9g}".format(GEO.lon_to_m(tile.lat)),
        "{:.9g}".format(GEO.lat_to_m),
        "{:n}".format(tile.dem.nxdem),
        "{:n}".format(tile.dem.nydem),
        "{:.9g}".format(tile.dem.x0),
        "{:.9g}".format(tile.dem.y0),
        "{:.9g}".format(tile.dem.x1),
        "{:.9g}".format(tile.dem.y1),
        "{:.9g}".format(tile.dem.nodata),
        "{:.9g}".format(tile.curvature_tol),
        alt_file,
        weight_file,
        poly_file,
    ]

    del tile.dem  # for machines with not much RAM, we do not need it anymore
    tile.dem = None
    UI.vprint(1, "-> Start of the mesh algorithm Triangle4XP.")
    UI.vprint(2, "   Mesh command:", " ".join(mesh_cmd))
    fingers_crossed = subprocess.Popen(
        mesh_cmd, stdout=subprocess.PIPE, bufsize=0, env=UI.subprocess_env()
    )
    while True:
        line = fingers_crossed.stdout.readline()
        if not line:
            break
        else:
            try:
                print(line.decode("utf-8")[:-1])
            except (UnicodeDecodeError, OSError):
                pass
    # wait(), not poll(): an exit code of None (process not finished yet)
    # would count as success and the mesh would be read half-written.
    fingers_crossed.wait()
    if fingers_crossed.returncode:
        min_angles = [8, 6, 4, 2, 0]
        for min_angle in min_angles:
            if tile.min_angle <= min_angle:
                continue
            # Logged as well: in a parallel batch the console is the
            # worker's tmp log, deleted when the tile succeeds, and a mesh
            # with a lower min_angle than configured should not go unseen.
            UI.lvprint(
                0,
                "WARNING: Triangle4XP failed for tile",
                FNAMES.short_latlon(tile.lat, tile.lon), "(",
                _tool_failure(fingers_crossed.returncode), ").",
                f"Reattempting with a lower angle constraint (min_angle={min_angle}).",
            )
            Tri_option = (
                "-pq"
                + "{:.9g}".format(min_angle)
                + do_refine
                + "uYB"
                + tri_verbosity
                + output_poly
                + limit_tris
            )
            mesh_cmd[1] = Tri_option
            fingers_crossed = subprocess.Popen(
                mesh_cmd, stdout=subprocess.PIPE, bufsize=0, env=UI.subprocess_env()
            )
            while True:
                line = fingers_crossed.stdout.readline()
                if not line:
                    break
                else:
                    try:
                        print(line.decode("utf-8")[:-1])
                    except (UnicodeDecodeError, OSError):
                        pass
            fingers_crossed.wait()
            if fingers_crossed.returncode == 0:
                break
        else:
            UI.exit_message_and_bottom_line(
                "\nERROR: Triangle4XP really couldn't make it !\n\n",
                "If the reason is not due to the limited amount of ",
                "RAM please\n",
                "file a bug including the .node and .poly files that you\n",
                "will find in ",
                str(tile.build_dir),
                ".\n",
            )
            return 0

    if UI.red_flag:
        UI.exit_message_and_bottom_line()
        return 0

    vertices = post_process_nodes_altitudes(tile)

    if UI.red_flag:
        UI.exit_message_and_bottom_line()
        return 0

    if steiner_cap_reached(len(vertices) // 6, input_nodes, max_steiner):
        # Triangle4XP stops inserting points at the -S cap without a word:
        # the refinement is then cut short wherever it had not got to yet,
        # so parts of the tile are coarser than curvature_tol asks.
        UI.lvprint(
            0, "WARNING: Triangle4XP stopped refining tile",
            FNAMES.short_latlon(tile.lat, tile.lon),
            f"at the limit_tris cap ({tile.limit_tris} M triangles):",
            "parts of the mesh are coarser than curvature_tol asks.",
            "Raise limit_tris or curvature_tol for this tile.",
        )

    write_mesh_file(tile, vertices)
    #
    to_delete = []
    if UI.cleaning_level:
        to_delete += [
            FNAMES.weight_file(tile),
            FNAMES.output_node_file(tile),
            FNAMES.output_ele_file(tile),
        ]
    if UI.cleaning_level > 2:
        to_delete += [
            FNAMES.alt_file(tile),
            FNAMES.input_node_file(tile),
            FNAMES.input_poly_file(tile),
        ]
    for file_name in to_delete:
        # Cleanup only: a missing file is fine, other failures (file locked,
        # no permission) are reported but don't fail the mesh step.
        try:
            os.remove(file_name)
        except FileNotFoundError:
            pass
        except OSError as e:
            UI.lvprint(
                1, "WARNING: could not delete", file_name, f"({e.strerror})."
            )

    UI.timings_and_bottom_line(timer)
    UI.logprint(
        "Step 2 for tile lat=", tile.lat, ", lon=", tile.lon, ": normal exit."
    )
    return 1


################################################################################
def sort_mesh(tile):
    if UI.is_working:
        return 0
    UI.is_working = 1
    UI.red_flag = False
    mesh_file = FNAMES.mesh_file(tile.build_dir, tile.lat, tile.lon)
    if not os.path.isfile(mesh_file):
        UI.exit_message_and_bottom_line("\nERROR: Could not find ", mesh_file)
        return 0
    sort_mesh_cmd_list = [
        sort_mesh_cmd.strip(),
        str(tile.default_zl),
        mesh_file,
    ]
    UI.vprint(1, "-> Reorganizing mesh triangles.")
    timer = time.time()
    try:
        moulinette = subprocess.Popen(
            sort_mesh_cmd_list, stdout=subprocess.PIPE, bufsize=0,
            env=UI.subprocess_env(),
        )
    except OSError as e:
        UI.exit_message_and_bottom_line(
            "\nERROR: Could not start moulinette:", e
        )
        return 0
    while True:
        line = moulinette.stdout.readline()
        if not line:
            break
        else:
            print(line.decode("utf-8", errors="replace")[:-1])
    # The pipe closes when the tool ends, but its exit code is only known
    # after wait(); a crash used to be reported as "Moulinette applied".
    if moulinette.wait() != 0:
        UI.exit_message_and_bottom_line(
            "\nERROR: moulinette failed for tile",
            FNAMES.short_latlon(tile.lat, tile.lon),
            f"(exit code {moulinette.returncode & 0xFFFFFFFF:#x}).",
        )
        return 0
    UI.timings_and_bottom_line(timer)
    UI.logprint(
        "Moulinette applied for tile lat=",
        tile.lat,
        ", lon=",
        tile.lon,
        " and ZL",
        tile.default_zl,
    )
    return 1


################################################################################
def _tool_failure(returncode):
    """Describe a failed tool's exit code for the log."""
    code = returncode & 0xFFFFFFFF
    if code == 0xC00000FD:
        # Windows STATUS_STACK_OVERFLOW: the bundled Triangle4XP.exe had a
        # 2 MB stack and crashed in quality refinement on detailed tiles;
        # it now reserves 256 MB. Seen here again, the stack is too small.
        return "exit code 0xC00000FD, stack overflow"
    if code >= 0xC0000000:
        return f"exit code {code:#X}, crashed"
    return f"exit code {returncode}, most likely an uncaught OSM error"


################################################################################
def triangulate(name, path_to_Ortho4XP_dir):
    Tri_option = " -pAYPQ "
    mesh_cmd = [
        os.path.join(path_to_Ortho4XP_dir, triangle_cmd).strip(),
        Tri_option.strip(),
        name + ".poly",
    ]
    fingers_crossed = subprocess.Popen(
        mesh_cmd, stdout=subprocess.PIPE, bufsize=0, env=UI.subprocess_env()
    )
    while True:
        line = fingers_crossed.stdout.readline()
        if not line:
            break
        else:
            print(line.decode("utf-8")[:-1])
    fingers_crossed.wait()
    if fingers_crossed.returncode:
        print("\nERROR: triangle crashed, check osm mask data.\n")
        return 0
    return 1


##############################################################################
def steiner_cap_reached(final_vertices, input_vertices, max_steiner):
    """True when Triangle4XP used up its -S budget of Steiner points.

    Triangle adds exactly int(S) points when the cap stops it (checked with
    the bundled triangle.exe); duplicate input vertices it drops make the
    count a little lower, hence the 0.1 % slack.
    """
    return final_vertices - input_vertices >= 0.999 * int(max_steiner)


##############################################################################
def read_mesh_file(mesh_file):
    
    with open(mesh_file,"r") as f:
        mesh_version = float(f.readline().strip().split()[-1])
    
        # skip 3 lines 
        for i in range(3):
            f.readline()
    
        nbr_nodes = int(f.readline())
        node_coords = numpy.zeros(5 * nbr_nodes)
    
        # read positions
        for i in range(nbr_nodes):
            node_coords[5 * i : 5 * i + 3] = [
                float(x) for x in f.readline().split()[:3]
            ]
        # altitutes are encoded in .mesh files with a 100000 scaling factor
        node_coords[2::5] *= 100000
    
        # skip 3 lines
        for i in range(3):
            f.readline()
    
        # read normals
        for i in range(nbr_nodes):
            node_coords[5 * i + 3 : 5 * i + 5] = [
                float(x) for x in f.readline().split()[:2]
            ]
    
        # skip 2 lines
        for i in range(0, 2): 
            f.readline()

        # read nbr of tris
        nbr_tris = int(f.readline())      

        tri_idx  = numpy.zeros(3 * nbr_tris, dtype = numpy.uint32)
        tri_types = numpy.zeros(nbr_tris, dtype = numpy.uint32)
        for i in range(nbr_tris):
            (n1, n2, n3, t) = [
                int(x) - 1 for x in f.readline().split()[:4]
            ]
            tri_idx[3 * i: 3 * i + 3] = (n1, n2, n3)
            tri_types[i] = t + 1

    return (mesh_version, nbr_nodes, node_coords, nbr_tris, tri_idx, tri_types)
##############################################################################
