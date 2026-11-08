"""#66: a runway far from all airports never replaces an existing entry."""
import O4_Airport_Utils as APT


def test_new_name_becomes_the_key():
    dico = {}
    key = APT._add_far_airport(dico, "Skovlunde Airstrip", (12.4, 55.7))
    assert key == "Skovlunde Airstrip"
    assert dico[key]["key_type"] == "name"
    assert dico[key]["name"] == "Skovlunde Airstrip"
    assert dico[key]["repr_node"] == (12.4, 55.7)
    assert dico[key]["runway"] == [] and dico[key]["boundary"] is None


def test_name_already_a_key_keeps_the_old_airport():
    dico = {}
    first = APT._add_far_airport(dico, "Airstrip", (12.1, 55.1))
    dico[first]["runway"].append(101)
    second = APT._add_far_airport(dico, "Airstrip", (12.9, 55.9))
    assert second == (12.9, 55.9)
    assert dico["Airstrip"]["runway"] == [101]
    assert dico[second]["key_type"] == "repr_node"
    assert dico[second]["name"] == "Airstrip"


def test_name_equal_to_an_icao_key_keeps_that_airport():
    dico = {"EKCH": {"key_type": "icao", "runway": [7]}}
    key = APT._add_far_airport(dico, "EKCH", (12.0, 55.0))
    assert key == (12.0, 55.0)
    assert dico["EKCH"] == {"key_type": "icao", "runway": [7]}


def test_no_name_is_keyed_by_point():
    dico = {}
    key = APT._add_far_airport(dico, None, (12.0, 55.0))
    assert key == (12.0, 55.0)
    assert dico[key]["name"] == "****"
    assert dico[key]["key_type"] == "repr_node"
