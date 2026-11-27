"""A new vertex within SNAP_TOL of an existing one is that vertex (#155)."""
import O4_Vector_Utils as VECT

# +60+006 (60.6392 N, 6.6526 E, east of Voss): a lake way and a water
# multipolygon have their own nodes one OSM unit (1e-7 degree) apart. Both
# boundaries leave the same vertex towards them: a 52 m sliver with an
# angle of 0.0001 degree, which Triangle4XP filled with 265,000 points.
HUB = (0.6521766, 0.6395817)
LAKE = (0.6525941, 0.6391622)
MPOLY = (0.6525942, 0.6391621)


def _edges(vm):
    return {frozenset((vm.nodes_dico[a], vm.nodes_dico[b]))
            for (a, b) in vm.edges_dico.values()}


def test_one_osm_unit_apart_is_one_vertex():
    vm = VECT.Vector_Map()
    vm.insert_way([(*HUB, 0.0), (*LAKE, 0.0)], "WATER")
    vm.insert_way([(*HUB, 0.0), (*MPOLY, 0.0)], "WATER")
    assert len(vm.nodes_dico) == 2
    assert _edges(vm) == {frozenset((HUB, LAKE))}


def test_vertex_one_metre_away_stays():
    far = (LAKE[0] + 1e-5, LAKE[1])
    vm = VECT.Vector_Map()
    vm.insert_way([(*HUB, 0.0), (*LAKE, 0.0)], "WATER")
    vm.insert_way([(*HUB, 0.0), (*far, 0.0)], "WATER")
    assert len(vm.nodes_dico) == 3


def test_way_with_two_nodes_one_unit_apart():
    vm = VECT.Vector_Map()
    vm.insert_way([(*HUB, 0.0), (*LAKE, 0.0), (*MPOLY, 0.0)], "WATER")
    assert _edges(vm) == {frozenset((HUB, LAKE))}


def test_existing_vertex_keeps_its_altitude():
    vm = VECT.Vector_Map()
    a = vm.insert_node(*LAKE, 12.5)
    assert vm.insert_node(*MPOLY, 99.0) == a
    assert vm.data_nodes[a] == 12.5


def test_interior_vertex_next_to_the_tile_edge_goes_onto_it():
    # the tile border (gluing network) is inserted last: its vertex then
    # finds the one already there, on the border line
    vm = VECT.Vector_Map()
    a = vm.insert_node(1e-7, 0.5, 0.0)
    assert vm.nodes_dico[a] == (0.0, 0.5)
    assert vm.insert_node(0.0, 0.5 + 1e-7, 0.0) == a
    b = vm.insert_node(0.3, 1 - 5e-8, 0.0)
    assert vm.nodes_dico[b] == (0.3, 1.0)
    c = vm.insert_node(1e-8, 1e-8, 0.0)
    assert vm.nodes_dico[c] == (0.0, 0.0)


def test_border_vertex_is_never_moved_inwards():
    vm = VECT.Vector_Map()
    a = vm.insert_node(2.5e-7, 0.5, 0.0)   # inside, beyond the tolerance
    b = vm.insert_node(0.0, 0.5, 0.0)      # border: its own vertex
    assert a != b and vm.nodes_dico[b] == (0.0, 0.5)


def test_grid_follows_snap_to_grid():
    vm = VECT.Vector_Map()
    vm.insert_way([(*HUB, 0.0), (*LAKE, 0.0)], "WATER")
    vm.snap_to_grid(9)
    n = len(vm.nodes_dico)
    assert vm.nodes_dico[vm.insert_node(*MPOLY, 0.0)] == LAKE
    assert len(vm.nodes_dico) == n
