"""MESH.classify_triangles: which triangles get altitude post-treatment
(#144: attributes ending in the digit 0 were skipped)."""
import O4_Mesh_Utils as MESH


def lines(*attrs):
    return [f"{i + 1} {3 * i + 1} {3 * i + 2} {3 * i + 3} {a}\n"
            for (i, a) in enumerate(attrs)]


def test_dummy_is_skipped():
    assert MESH.classify_triangles(lines(0)) == (set(), set(), set())


def test_sea_plus_interp_alt_is_levelled():
    # 10 = SEA + INTERP_ALT: an airport or levelled road reaching the sea
    (water, sea, interp) = MESH.classify_triangles(lines(10))
    assert interp == {(0, 1, 2)} and not sea and not water


def test_every_attribute_but_zero_is_treated():
    attrs = [1, 2, 3, 4, 8, 9, 10, 11, 16, 20, 32, 40, 64, 80, 128, 136, 160]
    (water, sea, interp) = MESH.classify_triangles(lines(*attrs))
    assert len(water) + len(sea) + len(interp) == len(attrs)
    assert (0, 1, 2) in water          # 1 WATER
    assert (3, 4, 5) in sea            # 2 SEA
    assert (6, 7, 8) in sea            # 3 WATER + SEA: sea wins
    assert (9, 10, 11) in water        # 4 SEA_EQUIV


def test_trailing_spaces_and_no_newline():
    (water, sea, interp) = MESH.classify_triangles(["1 1 2 3 2", "2 4 5 6 40   \n"])
    assert sea == {(0, 1, 2)} and interp == {(3, 4, 5)}
