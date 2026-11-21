"""Old masks of a tile are deleted before step 2.5 builds new ones (#121)."""
from types import SimpleNamespace

import O4_File_Names as FNAMES
import O4_Geo_Utils as GEO
import O4_Mask_Utils as MASK


def test_old_distance_masks_go_too(tmp_path):
    t = SimpleNamespace(lat=65, lon=-24, mask_zl=16)
    (x0, y0) = GEO.wgs84_to_orthogrid(66, -24, 16)
    (x1, y1) = GEO.wgs84_to_orthogrid(65.5, -23.5, 16)
    names = [FNAMES.legacy_mask(x0, y0), FNAMES.distance_mask(x0, y0),
             FNAMES.distance_mask(x1, y1)]  # a _dist.png without its mask
    other = FNAMES.distance_mask(x0, y0 - 16)  # north of the tile: kept
    for n in names + [other, "notes.txt"]:
        (tmp_path / n).write_bytes(b"x")
    MASK.delete_old_masks_in_tile(t, str(tmp_path))
    # Step 3 reads a _dist.png for the bathymetry of any square that has
    # one; an old one stayed when the new build made no mask there.
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        [other, "notes.txt"])
