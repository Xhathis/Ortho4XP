"""#93: the bulk DSF encoders give the same bytes as the old per-value
struct.pack loops (copied below), and float2qquad the same strings."""
import array
import random
import struct

import numpy
import pytest

import O4_DSF_Utils as DSF


def _old_pool(pool, planes, length):
    out = b""
    for l in range(planes):
        out += struct.pack("<B", 0)
        for m in range(length):
            out += struct.pack("<H", pool[planes * m + l])
    return out


def _old_patch(tris):
    out = b""
    blocks = len(tris) // 255
    for j in range(blocks):
        out += struct.pack("<B", 23) + struct.pack("<B", 255)
        for k in range(255):
            out += struct.pack("<H", tris[255 * j + k])
    rem = len(tris) % 255
    if rem:
        out += struct.pack("<B", 23) + struct.pack("<B", rem)
        for k in range(rem):
            out += struct.pack("<H", tris[255 * blocks + k])
    return out


def _old_cross(pairs, new_idx):
    out = b""
    blocks = len(pairs) // 510
    for j in range(blocks):
        out += struct.pack("<B", 24) + struct.pack("<B", 255)
        for k in range(255):
            out += struct.pack("<H", new_idx[pairs[510 * j + 2 * k]])
            out += struct.pack("<H", pairs[510 * j + 2 * k + 1])
    rem = int((len(pairs) % 510) / 2)
    if rem:
        out += struct.pack("<B", 24) + struct.pack("<B", rem)
        for k in range(rem):
            out += struct.pack("<H", new_idx[pairs[510 * blocks + 2 * k]])
            out += struct.pack("<H", pairs[510 * blocks + 2 * k + 1])
    return out


def _arr(n, rnd):
    return array.array("H", (rnd.randrange(65536) for _ in range(n)))


@pytest.mark.parametrize("planes, length", [(5, 0), (5, 1), (5, 1000), (7, 333), (9, 4000)])
def test_pool_planes(planes, length):
    rnd = random.Random(planes * length)
    pool = _arr(planes * length, rnd)
    assert DSF._pool_planes(pool, numpy.int64(planes), numpy.int64(length)) == _old_pool(pool, planes, length)


def test_pool_shorter_than_length_raises():
    with pytest.raises(IndexError):
        DSF._pool_planes(array.array("H", [1, 2, 3]), 2, 2)


@pytest.mark.parametrize("n", [0, 1, 3, 254, 255, 256, 510, 765, 1000, 20000])
def test_patch_triangles(n):
    tris = _arr(n, random.Random(n))
    assert DSF._patch_triangle_cmds(tris) == _old_patch(tris)


@pytest.mark.parametrize("n", [0, 2, 6, 508, 510, 512, 1020, 1021, 3000, 3001])
def test_cross_pool_triangles(n):
    rnd = random.Random(n)
    new_idx = {i: rnd.randrange(65536) for i in range(40)}
    pairs = array.array("H")
    for k in range(n):
        pairs.append(rnd.randrange(40) if k % 2 == 0 else rnd.randrange(65536))
    assert DSF._cross_pool_triangle_cmds(pairs, new_idx) == _old_cross(pairs, new_idx)


def test_float2qquad_same_as_binary_repr():
    rnd = random.Random(1)
    xs = [0.0, 1e-12, -1e-12, -1e-7, -0.25, 0.5, 0.999999999, 1.0, 1.5]
    xs += [rnd.random() for _ in range(20000)]
    for x in xs:
        old = ("111111111111111111111111" if x >= 1
               else numpy.binary_repr(int(16777216 * x)).zfill(24))
        assert DSF.float2qquad(x) == old, x
