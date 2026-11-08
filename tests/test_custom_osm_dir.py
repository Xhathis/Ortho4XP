"""#71: a custom coastline/water folder is merged once, and never cached
when one of its files cannot be read."""
import pytest

import O4_OSM_Utils as OSM
import O4_UI_Utils as UI

_HEAD = "<?xml version='1.0' encoding='UTF-8'?>\n<osm version=\"0.6\">\n"


def _osm(way_id, n0, lon0):
    return (
        _HEAD
        + f'  <node id="{n0}" lat="55.1" lon="{lon0}"/>\n'
        + f'  <node id="{n0 + 1}" lat="55.2" lon="{lon0 + 0.1}"/>\n'
        + f'  <way id="{way_id}">\n'
        + f'    <nd ref="{n0}"/>\n    <nd ref="{n0 + 1}"/>\n'
        + '    <tag k="natural" v="coastline"/>\n'
        + "  </way>\n</osm>\n"
    )


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    logged = []
    monkeypatch.setattr(UI, "lvprint", lambda level, *a: logged.append(a))
    monkeypatch.setattr(UI, "vprint", lambda level, *a: None)
    return logged


def test_all_files_read_and_merged_once(tmp_path, monkeypatch):
    src = tmp_path / "coast"
    src.mkdir()
    (src / "a.osm").write_text(_osm(1, 10, 12.1), encoding="utf-8")
    (src / "b.osm").write_text(_osm(2, 20, 12.5), encoding="utf-8")
    merged = tmp_path / "merged.osm"
    writes = []
    real_write = OSM.OSM_layer.write_to_file

    def counting_write(self, filename):
        writes.append(filename)
        return real_write(self, filename)

    monkeypatch.setattr(OSM.OSM_layer, "write_to_file", counting_write)
    layer = OSM.OSM_layer()
    assert OSM.read_custom_osm_dir(layer, str(src), str(merged)) is True
    assert writes == [str(merged)]
    assert len(layer.dicosmw) == 2
    again = OSM.OSM_layer()
    assert again.update_dicosm(str(merged), None, None)
    assert len(again.dicosmw) == 2


def test_broken_file_stops_and_nothing_is_cached(tmp_path, _quiet):
    src = tmp_path / "water"
    src.mkdir()
    (src / "a.osm").write_text(_osm(1, 10, 12.1), encoding="utf-8")
    # Cut file: no </osm>.
    (src / "b.osm").write_text(_osm(2, 20, 12.5)[:-8], encoding="utf-8")
    merged = tmp_path / "merged.osm"
    layer = OSM.OSM_layer()
    assert OSM.read_custom_osm_dir(layer, str(src), str(merged)) is False
    assert not merged.exists()
    assert any("b.osm" in " ".join(map(str, a)) for a in _quiet)
