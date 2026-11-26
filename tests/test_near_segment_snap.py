"""A vertex within SNAP_TOL of another segment's inside joins it (#154)."""
import pytest

import O4_Vector_Utils as VECT

# +43-066: a lagoon's ring follows the coast with one vertex 0.03 mm off
# the coast segment (2.7e-10 degree); +39-108: 0.013 mm.
A = (0.10, 0.20)
B = (0.10012, 0.20005)
OFF = 2.7e-10


def _between(t, off):
    """A point at t along A-B, off (degrees) to its left."""
    (dx, dy) = (B[0] - A[0], B[1] - A[1])
    n = (dx * dx + dy * dy) ** 0.5
    return (A[0] + t * dx - off * dy / n, A[1] + t * dy + off * dx / n)


V = _between(0.93, OFF)


def _edges(vm):
    """{frozenset of two points: marker} of the map."""
    return {frozenset((vm.nodes_dico[a], vm.nodes_dico[b])): vm.data_edges[e]
            for (e, (a, b)) in vm.edges_dico.items()}


def test_near_inside():
    assert VECT.near_inside(V, A, B) == pytest.approx(0.93)
    assert VECT.near_inside(_between(0.5, 1.9e-7), A, B) is not None
    assert VECT.near_inside(_between(0.5, 2.1e-7), A, B) is None
    assert VECT.near_inside(_between(0, 0), A, B) is None   # an end
    assert VECT.near_inside(_between(1.2, 0), A, B) is None  # beyond it
    assert VECT.near_inside(_between(0.999999, 0), A, B) is None  # < tol


@pytest.mark.parametrize("coast_first", [True, False])
def test_lagoon_along_the_coast_shares_the_vertex(coast_first):
    vm = VECT.Vector_Map()
    ways = [([A, B], "SEA"), ([A, V, B], "WATER")]
    for (way, marker) in (ways if coast_first else ways[::-1]):
        vm.insert_way([(x, y, 0.0) for (x, y) in way], marker)
    edges = _edges(vm)
    # no sliver: A-B is gone, both boundaries run A-V-B
    assert edges == {frozenset((A, V)): 3, frozenset((V, B)): 3}


def test_vertex_one_metre_off_is_left_alone():
    vm = VECT.Vector_Map()
    far = _between(0.5, 1e-5)
    vm.insert_way([(*A, 0.0), (*B, 0.0)], "SEA")
    vm.insert_way([(*A, 0.0), (*far, 0.0), (*B, 0.0)], "WATER")
    assert _edges(vm) == {frozenset((A, B)): 2, frozenset((A, far)): 1,
                          frozenset((far, B)): 1}


def test_nearly_parallel_overlap():
    # two segments 0.01 mm apart overlapping halfway: one chain of three
    p0, p1 = _between(0.0, 0), _between(0.6, 0)
    q0, q1 = _between(0.4, 1e-10), _between(1.0, 1e-10)
    vm = VECT.Vector_Map()
    vm.insert_way([(*p0, 0.0), (*p1, 0.0)], "WATER")
    vm.insert_way([(*q0, 0.0), (*q1, 0.0)], "SEA")
    assert _edges(vm) == {frozenset((p0, q0)): 1, frozenset((q0, p1)): 3,
                          frozenset((p1, q1)): 2}
