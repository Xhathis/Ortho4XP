"""Turn Ortho4XP orthophoto JPEGs into georeferenced GeoTIFFs (EPSG:4326).

Standalone helper, not used by the application. For every
<til_y>_<til_x>_<provider><zl>.jpg in a folder (default: the current
one) it writes <name>.tif next to it.
Usage: python O4_Geotag.py [folder]
"""
import os
import sys
from math import pi, exp, atan

from osgeo import gdal
from pyproj import Transformer

gdal.UseExceptions()
# always_xy: coordinates are passed as (lon, lat) below.
geo_to_webm = Transformer.from_crs("epsg:4326", "epsg:3857", always_xy=True)


def gtile_to_wgs84(til_x, til_y, zoomlevel):
    rat_x = til_x / (2 ** (zoomlevel - 1)) - 1
    rat_y = 1 - til_y / (2 ** (zoomlevel - 1))
    lon = rat_x * 180
    lat = 360 / pi * atan(exp(pi * rat_y)) - 90
    return (lat, lon)


def geotag(jpg_file):
    """Write jpg_file as a GeoTIFF in EPSG:4326; return the .tif path."""
    items = os.path.basename(jpg_file).split("_")
    til_y_top = int(items[0])
    til_x_left = int(items[1])
    zoomlevel = int(items[-1][-6:-4])
    (latmax, lonmin) = gtile_to_wgs84(til_x_left, til_y_top, zoomlevel)
    (latmin, lonmax) = gtile_to_wgs84(
        til_x_left + 16, til_y_top + 16, zoomlevel
    )
    (xmin, ymin) = geo_to_webm.transform(lonmin, latmin)
    (xmax, ymax) = geo_to_webm.transform(lonmax, latmax)
    tmp_tif = jpg_file[:-4] + "_tmp.tif"
    tif = jpg_file[:-4] + ".tif"
    # Same operations as the former gdal_translate / gdalwarp command lines,
    # through the GDAL API: no shell, no dependency on GDAL tools in PATH,
    # and failures raise instead of being ignored.
    gdal.Translate(
        tmp_tif, jpg_file, format="GTiff", creationOptions=["COMPRESS=JPEG"],
        outputBounds=[xmin, ymax, xmax, ymin], outputSRS="EPSG:3857",
    )
    try:
        gdal.Warp(
            tif, tmp_tif, format="GTiff", creationOptions=["COMPRESS=JPEG"],
            srcSRS="EPSG:3857", dstSRS="EPSG:4326", width=4096, height=4096,
            resampleAlg="bilinear",
        )
    finally:
        os.remove(tmp_tif)
    return tif


def main(folder="."):
    failures = 0
    for f in sorted(os.listdir(folder)):
        if not f.endswith(".jpg"):
            continue
        try:
            print("Geotagged", geotag(os.path.join(folder, f)))
        except (ValueError, IndexError, RuntimeError, OSError) as e:
            # Unexpected file name (ValueError/IndexError) or GDAL error.
            print("Skipped", f, f"({type(e).__name__}: {e})")
            failures += 1
    return failures


if __name__ == "__main__":
    sys.exit(1 if main(sys.argv[1] if len(sys.argv) > 1 else ".") else 0)
