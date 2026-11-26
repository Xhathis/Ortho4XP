"""#152: link roads, living streets and light rail levelled; taxilanes too."""
import pytest

import O4_Airport_Utils as APT
import O4_Vector_Map as VMAP
from test_airstrip_lines import Layer


def _values(queries):
    return [q.split('"')[3] for q in queries]


@pytest.mark.parametrize("road", ["motorway", "trunk", "primary", "secondary"])
def test_big_road_links(road):
    values = _values(VMAP.BIG_ROAD_QUERIES)
    assert road + "_link" in values
    # right after its road class
    assert values.index(road + "_link") == values.index(road) + 1


def test_light_rail_but_not_trams():
    values = _values(VMAP.BIG_ROAD_QUERIES)
    assert "light_rail" in values
    assert "tram" not in values and "subway" not in values


def test_small_road_levels():
    assert _values(VMAP.small_road_queries(2)) == ["tertiary", "tertiary_link"]
    assert "living_street" not in _values(VMAP.small_road_queries(2))
    assert "living_street" in _values(VMAP.small_road_queries(3))
    assert _values(VMAP.small_road_queries(5))[-1] == "track"


def test_taxilane_is_a_taxiway():
    layer = Layer()
    layer.dicosmn[9] = (12.65, 55.62)
    layer.dicosmtags["n"][9] = {"aeroway": "aerodrome", "name": "Kastrup"}
    layer.way(1, [(12.650, 55.621), (12.651, 55.621)], {"aeroway": "taxiway"})
    layer.way(2, [(12.650, 55.622), (12.651, 55.622)], {"aeroway": "taxilane"})
    layer.way(3, [(12.650, 55.623), (12.651, 55.623)],
              {"aeroway": "parking_position"})
    dico = {}
    APT.discover_airport_names(layer, dico)
    APT.attach_surfaces_to_airports(layer, dico)
    assert sorted(dico["Kastrup"]["taxiway"]) == [1, 2]
