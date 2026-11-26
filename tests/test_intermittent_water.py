"""Intermittent and seasonal water is built as land (#151)."""
import os

import pytest

import O4_File_Names as FNAMES
import O4_Geofabrik as GEOFABRIK
import O4_OSM_Extract as EXTRACT
import O4_OSM_Utils as OSM
import O4_Vector_Map as VMAP

WATER_TAGS = GEOFABRIK.TAGS_OF_INTEREST["water"]
WATER_ST = EXTRACT.flat_statements(VMAP.WATER_QUERIES)


@pytest.mark.parametrize("tags, dry", [
    ({"natural": "water"}, False),
    ({"natural": "water", "intermittent": "no"}, False),
    ({"natural": "water", "seasonal": "no"}, False),
    ({"natural": "water", "intermittent": "yes"}, True),
    ({"natural": "water", "seasonal": "wet_season"}, True),
    ({"natural": "water", "seasonal": "yes", "salt": "yes"}, True),
])
def test_is_intermittent_water(tags, dry):
    assert VMAP.is_intermittent_water(tags) is dry


def _square(first_id, x0):
    """Four nodes of a closed square way at lon 12+x0, lat 55.1."""
    nodes = [(first_id + i, 55.1 + dy, 12 + x0 + dx, {})
             for (i, (dx, dy)) in enumerate(
                 [(0, 0), (0.01, 0), (0.01, 0.01), (0, 0.01)])]
    return nodes, [n[0] for n in nodes] + [first_id]


def _water_layer(tmp_path):
    (n1, r1) = _square(1, 0.1)
    (n2, r2) = _square(11, 0.3)
    (n3, r3) = _square(21, 0.5)
    # Overpass's layout (one element or tag per line): the reader's input.
    def tags(t):
        return [f'    <tag k="{k}" v="{v}"/>' for (k, v) in t.items()]

    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<osm version="0.6">']
    out += [f'  <node id="{i}" lat="{la}" lon="{lo}"/>'
            for (i, la, lo, _) in n1 + n2 + n3]
    for (i, refs, t) in [(1, r1, {"natural": "water", "name": "Lake"}),
                         (2, r2, {"natural": "water", "intermittent": "yes"}),
                         (3, r3, {})]:
        out += ([f'  <way id="{i}">'] + [f'    <nd ref="{r}"/>' for r in refs]
                + tags(t) + ["  </way>"])
    out += (['  <relation id="9">',
             '    <member type="way" ref="3" role="outer"/>']
            + tags({"type": "multipolygon", "natural": "water",
                    "seasonal": "wet_season"}) + ["  </relation>", "</osm>"])
    path = tmp_path / "water.osm"
    path.write_text("\n".join(out), encoding="utf-8")
    layer = OSM.OSM_layer()
    (input_tags, target_tags) = OSM.layer_tags(VMAP.WATER_QUERIES, WATER_TAGS)
    assert layer.update_dicosm(str(path), input_tags, target_tags)
    return layer


def test_layer_keeps_the_tags(tmp_path):
    layer = _water_layer(tmp_path)
    # (the reader renumbers the ids)
    way_tags = list(layer.dicosmtags["w"].values())
    assert {"natural": "water", "intermittent": "yes"} in way_tags
    assert [t.get("seasonal") for t in layer.dicosmtags["r"].values()] ==         ["wet_season"]


def test_drop_intermittent_water(tmp_path):
    layer = _water_layer(tmp_path)
    assert VMAP.drop_intermittent_water(layer) == 2
    (left,) = layer.dicosmfirst["w"]
    assert layer.dicosmtags["w"][left]["name"] == "Lake"
    assert layer.dicosmfirst["r"] == set()
    water = OSM.OSM_to_MultiPolygon(layer, 55, 12)
    # only the permanent lake is left
    assert len(water.geoms) == 1
    assert water.bounds[0] == pytest.approx(0.1)


def _cache(tmp_path, tags, stamp=True):
    path = os.path.join(tmp_path, "c.osm.bz2")
    assert OSM.OSM_layer().write_to_file(path, WATER_ST if stamp else (), tags)
    return path


def test_cache_stamp_names_the_kept_tags(tmp_path):
    path = _cache(tmp_path, WATER_TAGS)
    assert EXTRACT.cache_fits(path, WATER_ST, WATER_TAGS) is True
    assert EXTRACT.cache_fits(path, WATER_ST, ["name"]) is True
    assert EXTRACT.cache_fits(_cache(tmp_path, ["name"]), WATER_ST,
                              WATER_TAGS) is False


def test_cache_stamped_before_151(tmp_path):
    # A stamp without tags (#107 .. #150): it kept all the tags of that time.
    path = os.path.join(tmp_path, "old.osm.bz2")
    import bz2
    with bz2.open(path, "wt", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<osm version="0.6" '
                'generator="Ortho4XP">\n<o4xp_cache statements="'
                + EXTRACT.xml_escape("\n".join(WATER_ST)) + '"/>\n</osm>')
    assert EXTRACT.cache_fits(path, WATER_ST, ["name"]) is True
    assert EXTRACT.cache_fits(path, WATER_ST, WATER_TAGS) is False
    roads = EXTRACT.flat_statements(VMAP.BIG_ROAD_QUERIES)
    assert EXTRACT.cache_fits(path, roads, ["bridge", "tunnel"]) is False


def test_all_keeps_every_tag(tmp_path):
    path = _cache(tmp_path, ["all"])
    assert EXTRACT.cache_fits(path, WATER_ST, WATER_TAGS) is True


def test_old_water_cache_is_prepared_again(tmp_path, monkeypatch):
    # needed_layers takes a water cache that lacks the tags (no age limit)
    monkeypatch.setattr(GEOFABRIK, "osm_cache_max_age", 0.0)
    path = FNAMES.osm_cached(55, 12, "water")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    assert OSM.OSM_layer().write_to_file(path, WATER_ST, ["name"])
    assert "water" in GEOFABRIK.needed_layers(55, 12, 0)
    assert OSM.OSM_layer().write_to_file(path, WATER_ST, WATER_TAGS)
    assert "water" not in GEOFABRIK.needed_layers(55, 12, 0)
