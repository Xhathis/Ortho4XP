"""VECT.surely_not_encroached, the cheap pre-check of insert_edge: whenever
it answers a pair, are_encroached must say False for it too, or the mesh
would change.
"""
import random

import numpy

import O4_Vector_Utils as VECT


def encroached(a, b, c, d):
    vm = VECT.Vector_Map()
    return vm.are_encroached(
        *(numpy.array(p, dtype=float) for p in (a, b, c, d)))


def bboxes_overlap(a, b, c, d):
    return (min(a[0], b[0]) <= max(c[0], d[0])
            and min(c[0], d[0]) <= max(a[0], b[0])
            and min(a[1], b[1]) <= max(c[1], d[1])
            and min(c[1], d[1]) <= max(a[1], b[1]))


def check(a, b, c, d):
    if VECT.surely_not_encroached(a, b, c, d):
        assert not encroached(a, b, c, d), (a, b, c, d)
        return True
    return False


def test_far_apart_and_crossing():
    assert VECT.surely_not_encroached((0, 0), (1, 0), (0, 0.5), (1, 0.6))
    assert not VECT.surely_not_encroached((0, 0), (1, 1), (0, 1), (1, 0))
    # colinear overlap, T junction: left to are_encroached
    assert not VECT.surely_not_encroached((0, 0), (1, 0), (0.5, 0), (2, 0))
    assert not VECT.surely_not_encroached((0, 0), (1, 0), (0.5, 0), (0.5, 1))


def test_near_misses_are_left_to_are_encroached():
    # d 1e-6 from the line ab: inside the margin.
    assert not VECT.surely_not_encroached((0, 0), (1, 0), (0.5, 1), (0.5, 1e-6))


def test_previous_edge_of_the_way():
    # insert_way: the new edge a-b starts where the previous one c-d ends.
    assert VECT.surely_not_encroached((1, 0), (2, 0.5), (0, 0), (1, 0))
    assert VECT.surely_not_encroached((1, 0), (2, 0), (0, 0), (1, 0))
    # folding back onto it: are_encroached must decide (it splits)
    assert not VECT.surely_not_encroached((1, 0), (0.5, 0), (0, 0), (1, 0))
    assert encroached((1, 0), (0.5, 0), (0, 0), (1, 0))
    # same start point, same direction: are_encroached decides
    assert not VECT.surely_not_encroached((0, 0), (1, 0), (0, 0), (0.5, 0))


def _random_pairs(rnd, n):
    # mixed scales, as in a tile: [0, 1] coordinates, edges from 1e-7 (OSM
    # detail) to 1 (tile border)
    for _ in range(n):
        a = (rnd.random(), rnd.random())
        la = 10 ** rnd.uniform(-7, 0)
        b = (a[0] + la * rnd.uniform(-1, 1), a[1] + la * rnd.uniform(-1, 1))
        lc = 10 ** rnd.uniform(-7, 0)
        kind = rnd.randrange(5)
        if kind == 3:  # shared end point
            c = rnd.choice((a, b))
        else:
            c = (a[0] + la * rnd.uniform(-1, 1), a[1] + la * rnd.uniform(-1, 1))
        if kind in (0, 3):  # any direction
            d = (c[0] + lc * rnd.uniform(-1, 1), c[1] + lc * rnd.uniform(-1, 1))
        else:  # (nearly) parallel to ab
            t = lc / la * rnd.choice((-1, 1))
            eps = 10 ** rnd.uniform(-14, -2) if kind in (2, 4) else 0
            d = (c[0] + t * (b[0] - a[0]) + eps * la,
                 c[1] + t * (b[1] - a[1]))
            if kind == 4:  # nearly folded onto a shared end point
                c, d = d, rnd.choice((a, b))
        if rnd.random() < 0.5:
            c, d = d, c
        if bboxes_overlap(a, b, c, d):
            yield (a, b, c, d)


def test_never_answers_what_are_encroached_reports():
    rnd = random.Random(1)
    answered = asked = 0
    for (a, b, c, d) in _random_pairs(rnd, 40000):
        asked += 1
        answered += check(a, b, c, d)
    # the test exercises both outcomes
    assert answered > 2000 and asked - answered > 2000
