"""#130: an aeroway=airstrip line is a runway, not an airport area."""
import O4_Airport_Utils as APT
import O4_UI_Utils as UI


class Layer:
    def __init__(self):
        self.dicosmn = {}
        self.dicosmw = {}
        self.dicosmr = {}
        self.dicosmtags = {"n": {}, "w": {}, "r": {}}

    def way(self, wid, coords, tags, closed=False):
        ids = []
        for (i, c) in enumerate(coords):
            nid = wid * 100 + i
            self.dicosmn[nid] = c
            ids.append(nid)
        if closed:
            ids.append(ids[0])
        self.dicosmw[wid] = ids
        self.dicosmtags["w"][wid] = tags


def strip(layer, wid=1, closed=False):
    layer.way(wid, [(174.30, -35.31), (174.31, -35.31)],
              {"aeroway": "airstrip", "surface": "grass", "width": "35"},
              closed=closed)


def test_open_airstrip_is_a_line():
    layer = Layer()
    strip(layer)
    assert APT.is_airstrip_line(layer, 1)


def test_closed_airstrip_is_an_area():
    layer = Layer()
    layer.way(1, [(0, 0), (0.01, 0), (0.01, 0.01)], {"aeroway": "airstrip"},
              closed=True)
    assert not APT.is_airstrip_line(layer, 1)


def test_other_aeroways_and_unknown_ways():
    layer = Layer()
    layer.way(1, [(0, 0), (0.01, 0)], {"aeroway": "runway"})
    assert not APT.is_airstrip_line(layer, 1)
    assert not APT.is_airstrip_line(layer, 2)


def test_airstrip_line_becomes_a_runway_without_warning(monkeypatch):
    lines = []
    monkeypatch.setattr(UI, "lvprint", lambda *a: lines.append(a))
    layer = Layer()
    strip(layer)
    dico = {}
    APT.discover_airport_names(layer, dico)
    assert dico == {} and lines == []  # dev: WARNING, strip dropped
    APT.attach_surfaces_to_airports(layer, dico)
    # Far from any airport: an airport of its own, the line as its runway.
    assert [a["runway"] for a in dico.values()] == [[1]]


def test_airstrip_line_joins_the_aerodrome_nearby():
    layer = Layer()
    strip(layer)
    layer.dicosmn[9] = (174.305, -35.312)
    layer.dicosmtags["n"][9] = {"aeroway": "aerodrome", "name": "Kerikeri"}
    dico = {}
    APT.discover_airport_names(layer, dico)
    APT.attach_surfaces_to_airports(layer, dico)
    assert list(dico) == ["Kerikeri"] and dico["Kerikeri"]["runway"] == [1]


def test_airstrip_area_stays_an_airport():
    layer = Layer()
    layer.way(1, [(0, 0), (0.01, 0), (0.01, 0.002), (0, 0.002)],
              {"aeroway": "airstrip", "name": "Strip"}, closed=True)
    dico = {}
    APT.discover_airport_names(layer, dico)
    assert list(dico) == ["Strip"] and dico["Strip"]["boundary"] is not None
    APT.attach_surfaces_to_airports(layer, dico)
    assert dico["Strip"]["runway"] == []
