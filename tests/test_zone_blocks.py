"""Which zone a texture block takes in step 3 (DSF.zone_list_to_ortho_dico).

A block took the zone found at its centre pixel only, so a zone narrower
than a block (a 1 km helipad zone against ~1.2 km ZL18 textures) could take
no block at all: 8 of the 82 Greenland zones of 2026-11-24 changed nothing.
"""
import types

import numpy
import pytest


@pytest.fixture
def DSF():
    import O4_DSF_Utils
    return O4_DSF_Utils


@pytest.fixture
def GEO():
    import O4_Geo_Utils
    return O4_Geo_Utils


def ring(la0, lo0, la1, lo1):
    return [la0, lo0, la0, lo1, la1, lo1, la1, lo0, la0, lo0]


def make_tile(lat, lon, zones, default_zl=15, mesh_zl=18):
    return types.SimpleNamespace(
        lat=lat, lon=lon, zone_list=zones, default_zl=default_zl,
        default_website="GO2", mesh_zl=mesh_zl,
        cover_airports_with_highres="False", cover_extent=1, cover_zl=18)


def blocks_with(dico, zl, provider):
    return {k for k, v in dico.items() if v[2] == zl and v[3] == provider}


# Nanortalik Heliport's zone of +60-046 (tile config of 2026-11-24): its
# 1.0 x 1.0 km box holds no ZL18 texture centre.
NANORTALIK = ring(60.1374, -45.2424, 60.1464, -45.2243)


def test_small_zone_takes_the_blocks_it_covers(DSF, GEO):
    tile = make_tile(60, -46, [(NANORTALIK, 18, "BI")])
    dico = DSF.zone_list_to_ortho_dico(tile)
    got = blocks_with(dico, 18, "BI")
    assert got, "the helipad zone took no block"
    # every block of the zone touches the box; the heliport itself is in one
    (tx, ty) = GEO.wgs84_to_orthogrid(60.1419, -45.2333, 18)
    assert (16 * (tx // 16), 16 * (ty // 16)) in got
    for (bx, by) in got:
        (la0, lo0) = GEO.gtile_to_wgs84(bx, by, 18)
        (la1, lo1) = GEO.gtile_to_wgs84(bx + 16, by + 16, 18)
        assert la1 < 60.1464 and la0 > 60.1374
        assert lo0 < -45.2243 and lo1 > -45.2424
    assert len(got) <= 4


def test_zone_on_texture_edges_takes_only_its_textures(DSF, GEO):
    # a zone drawn exactly along 2 x 2 ZL18 textures (as the Vagar zone is,
    # rounded to 4 decimals) must not grow into the neighbours
    (tx, ty) = GEO.wgs84_to_orthogrid(62.06, -7.27, 18)
    (tx, ty) = (16 * (tx // 16), 16 * (ty // 16))
    (la1, lo0) = GEO.gtile_to_wgs84(tx, ty, 18)
    (la0, lo1) = GEO.gtile_to_wgs84(tx + 32, ty + 32, 18)
    zone = ring(round(la0, 4), round(lo0, 4), round(la1, 4), round(lo1, 4))
    tile = make_tile(62, -8, [(zone, 18, "FOA")], default_zl=16)
    dico = DSF.zone_list_to_ortho_dico(tile)
    assert blocks_with(dico, 18, "FOA") == {
        (tx, ty), (tx + 16, ty), (tx, ty + 16), (tx + 16, ty + 16)}


def test_no_zone_gives_the_default_everywhere(DSF):
    dico = DSF.zone_list_to_ortho_dico(make_tile(55, 12, [], default_zl=16))
    assert dico and {(v[2], v[3]) for v in dico.values()} == {(16, "GO2")}


def test_first_zone_of_the_list_wins_where_both_lie(DSF, GEO):
    big = ring(60.10, -45.30, 60.20, -45.15)
    tile = make_tile(60, -46, [(NANORTALIK, 18, "BI"), (big, 17, "GO2")])
    dico = DSF.zone_list_to_ortho_dico(tile)
    bi = blocks_with(dico, 18, "BI")
    assert bi
    assert blocks_with(dico, 17, "GO2")
    (tx, ty) = GEO.wgs84_to_orthogrid(60.1419, -45.2333, 18)
    assert dico[(16 * (tx // 16), 16 * (ty // 16))][2:] == (18, "BI")


def test_block_zone_index_inner_pixels_only(DSF):
    mask = numpy.ones((100, 100), dtype=numpy.uint8)
    mask[40:60, 40:60] = 2
    # zone inside the block, off its centre pixel
    assert DSF.block_zone_index(mask, 30.0, 50.0, 30.0, 50.0, 30, 30) == 2
    # zone only on the block's edge column (col 40 = right edge 40.0)
    assert DSF.block_zone_index(mask, 20.0, 40.0, 40.0, 60.0, 30, 50) == 1
    # block outside the mask: centre pixel
    assert DSF.block_zone_index(mask, 100.0, 120.0, 0.0, 20.0, 50, 50) == 2
