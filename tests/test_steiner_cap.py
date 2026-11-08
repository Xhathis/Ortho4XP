"""#75: a mesh cut short by the limit_tris (-S) cap is noticed."""
import os
import subprocess

import pytest

import O4_Mesh_Utils as MESH


def test_cap_reached_exactly():
    assert MESH.steiner_cap_reached(14, 4, 10)
    assert MESH.steiner_cap_reached(2_700_000, 200_000, 2_500_000.7)


def test_cap_reached_with_a_few_dropped_duplicates():
    assert MESH.steiner_cap_reached(2_698_000, 200_000, 2_500_000.0)


def test_normal_mesh_is_not_capped():
    # The regression tile: 269,909 input, 551,565 final vertices, cap
    # max(5e6 / 1.9 - 269,909, 5e5) with limit_tris 5.
    cap = max(5e6 / 1.9 - 269_909, 5e5)
    assert not MESH.steiner_cap_reached(551_565, 269_909, cap)
    assert not MESH.steiner_cap_reached(13, 4, 10)


# FNAMES.Utils_dir follows the cwd, which conftest moves to a temp folder.
_TRIANGLE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "Utils", "win", "triangle.exe",
)


@pytest.mark.skipif(not os.path.isfile(_TRIANGLE), reason="Windows tool")
@pytest.mark.parametrize("cap", ["10", "10.7"])
def test_triangle_adds_exactly_the_cap(tmp_path, cap):
    # The rule steiner_cap_reached relies on, with the bundled Triangle.
    poly = tmp_path / "sq.poly"
    poly.write_text("4 2 0 0\n1 0 0\n2 100 0\n3 100 100\n4 0 100\n"
                    "4 0\n1 1 2\n2 2 3\n3 3 4\n4 4 1\n0\n")
    subprocess.run([_TRIANGLE, "-pq30a5S" + cap, "-Q", str(poly)],
                   check=True, cwd=tmp_path)
    final = int((tmp_path / "sq.1.node").read_text().split()[0])
    assert final == 4 + 10
    assert MESH.steiner_cap_reached(final, 4, float(cap))
