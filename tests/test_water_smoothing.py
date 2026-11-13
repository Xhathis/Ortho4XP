"""Inland water smoothing (Mesh_Utils.smooth_water_altitudes)."""
import random

import numpy

import O4_Mesh_Utils as MESH


def vertices_with(z):
    v = numpy.zeros(6 * len(z))
    v[2::6] = z
    v[5::6] = 99.0  # other columns untouched
    return v


# A strip of 6 triangles over 8 vertices, plus a land vertex (8).
TRIS = {(0, 1, 2), (1, 3, 2), (2, 3, 4), (3, 5, 4), (4, 5, 6), (5, 7, 6)}
Z = [10.0, 12.0, 11.0, 15.0, 9.0, 14.0, 13.0, 8.0, 500.0]


def test_does_not_depend_on_order_or_numbering():
    a = vertices_with(Z)
    MESH.smooth_water_altitudes(a, TRIS, 10)
    # The same mesh with its vertices renumbered.
    perm = list(range(9))
    random.Random(3).shuffle(perm)
    zp = [0.0] * 9
    for (i, p) in enumerate(perm):
        zp[p] = Z[i]
    b = vertices_with(zp)
    MESH.smooth_water_altitudes(
        b, {tuple(perm[i] for i in t) for t in TRIS}, 10)
    assert numpy.allclose([b[6 * perm[i] + 2] for i in range(9)], a[2::6],
                          rtol=0, atol=1e-12)


def test_smooths_water_only():
    v = vertices_with(Z)
    MESH.smooth_water_altitudes(v, TRIS, 10)
    z = v[2::6]
    assert z[8] == 500.0  # land vertex
    assert (v[5::6] == 99.0).all()
    assert numpy.ptp(z[:8]) < 0.2 * numpy.ptp(Z[:8])
    assert min(Z[:8]) <= z[:8].min() and z[:8].max() <= max(Z[:8])


def test_flat_lake_stays_flat_and_no_water():
    v = vertices_with([7.5] * 8 + [3.0])
    MESH.smooth_water_altitudes(v, TRIS, 10)
    assert (v[2::6] == [7.5] * 8 + [3.0]).all()
    w = vertices_with(Z)
    MESH.smooth_water_altitudes(w, set(), 10)
    MESH.smooth_water_altitudes(w, TRIS, 0)
    assert (w[2::6] == Z).all()
