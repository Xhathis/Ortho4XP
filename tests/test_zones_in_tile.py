"""#74: which GUI zones are saved in a tile's config."""
import O4_Config_Utils as CFG


def _zone(lat0, lon0, lat1, lon1, zl=18, provider="Arc"):
    # The GUI's format: [lat, lon] pairs, closed ring.
    return [[lat0, lon0, lat0, lon1, lat1, lon1, lat1, lon0, lat0, lon0],
            zl, provider]


def test_zone_inside_the_tile():
    z = _zone(55.2, 12.2, 55.4, 12.5)
    assert CFG.zones_in_tile([z], 55, 12) == [z]


def test_zone_covering_the_tile_with_all_vertices_outside():
    # The old test missed it: no vertex coordinate truncates to 55 or 12.
    z = _zone(54.5, 11.5, 56.5, 13.5)
    assert CFG.zones_in_tile([z], 55, 12) == [z]


def test_lat_and_lon_are_not_mixed_up():
    # Old test: {12, 55} contains both 55 and 12, so tile +55+012 matched.
    z = _zone(12.2, 55.2, 12.4, 55.5)
    assert CFG.zones_in_tile([z], 55, 12) == []
    assert CFG.zones_in_tile([z], 12, 55) == [z]


def test_zone_only_touching_an_edge_is_not_in_the_tile():
    z = _zone(55.2, 13.0, 55.4, 13.5)  # west edge on the tile's east edge
    assert CFG.zones_in_tile([z], 55, 12) == []
    assert CFG.zones_in_tile([z], 55, 13) == [z]


def test_negative_tile():
    # Tile -34+018 spans lat -34..-33, lon 18..19.
    z = _zone(-33.9, 18.3, -33.8, 18.6)
    assert CFG.zones_in_tile([z], -34, 18) == [z]
    assert CFG.zones_in_tile([z], -33, 18) == []


def test_zone_spanning_two_tiles_is_in_both():
    z = _zone(55.4, 12.8, 55.6, 13.2)
    assert CFG.zones_in_tile([z], 55, 12) == [z]
    assert CFG.zones_in_tile([z], 55, 13) == [z]
    assert CFG.zones_in_tile([z], 56, 12) == []


def test_self_crossing_zone():
    # A bow tie drawn in the GUI: invalid polygon, still placed.
    z = [[55.2, 12.2, 55.4, 12.4, 55.4, 12.2, 55.2, 12.4, 55.2, 12.2],
         17, "Arc"]
    assert CFG.zones_in_tile([z], 55, 12) == [z]


def test_order_kept_and_others_dropped():
    a = _zone(55.1, 12.1, 55.2, 12.2)
    b = _zone(40.1, 10.1, 40.2, 10.2)
    c = _zone(55.7, 12.7, 55.8, 12.8, provider="GO2")
    assert CFG.zones_in_tile([a, b, c], 55, 12) == [a, c]
