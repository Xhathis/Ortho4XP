"""#75: a mesh cut short by the limit_tris (-S) cap is noticed."""
import os
import subprocess

import pytest

import O4_Mesh_Utils as MESH


def test_report_of_triangle4xp_decides():
    # 0 left: capped, whatever the vertex count (deleted vertices keep
    # their budget spent: +55+012 at -S 200000 added 182,444 points).
    assert MESH.steiner_cap_reached(0, 452_353, 269_909, 200_000)
    assert not MESH.steiner_cap_reached(1, 14, 4, 10)


def test_parse_steiner_left():
    assert MESH.parse_steiner_left("Steiner points left: 0") == 0
    assert MESH.parse_steiner_left("  Steiner points left: 986227 ") == 986227
    assert MESH.parse_steiner_left("Steiner points left: x") is None
    assert MESH.parse_steiner_left("   Mesh vertices: 2,190,828") is None


def test_cap_reached_exactly():
    assert MESH.steiner_cap_reached(None, 14, 4, 10)
    assert MESH.steiner_cap_reached(None, 2_700_000, 200_000, 2_500_000.7)


def test_cap_reached_with_a_few_dropped_duplicates():
    assert MESH.steiner_cap_reached(None, 2_698_000, 200_000, 2_500_000.0)


def test_normal_mesh_is_not_capped():
    # The regression tile: 269,909 input, 551,565 final vertices, cap
    # max(5e6 / 1.9 - 269,909, 5e5) with limit_tris 5.
    cap = max(5e6 / 1.9 - 269_909, 5e5)
    assert not MESH.steiner_cap_reached(None, 551_565, 269_909, cap)
    assert not MESH.steiner_cap_reached(None, 13, 4, 10)


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
    assert MESH.steiner_cap_reached(None, final, 4, float(cap))


_TRIANGLE4XP = os.path.join(os.path.dirname(_TRIANGLE), "Triangle4XP.exe")


def _hill_tile(tmp_path):
    """A 1 x 1 tile (Ortho4XP's .node/.poly/.alt/.weight): a 1000 m peak,
    5 x 5 interior nodes (with -Y a bare square cannot be refined: every
    circumcenter would encroach on its boundary)."""
    import numpy
    n = 401
    (y, x) = numpy.mgrid[0:n, 0:n] / (n - 1)
    alt = 1000 * numpy.exp(-((x - 0.5) ** 2 + (y - 0.5) ** 2) / 0.0005)
    alt.astype(numpy.float32).tofile(tmp_path / "t.alt")
    numpy.ones((1001, 1001), dtype=numpy.float32).tofile(tmp_path / "t.weight")
    pts = [(0, 0), (1, 0), (1, 1), (0, 1)] + [
        (i / 6, j / 6) for i in range(1, 6) for j in range(1, 6)]
    lines = [f"{len(pts)} 2 1 0"] + [
        f"{k + 1} {a} {b} 0" for (k, (a, b)) in enumerate(pts)]
    (tmp_path / "t.node").write_text("\n".join(lines) + "\n")
    (tmp_path / "t.poly").write_text("\n".join(
        ["0 2 1 0", "4 1", "1 1 2 0", "2 2 3 0", "3 3 4 0", "4 4 1 0",
         "0", "0"]) + "\n")
    return n


@pytest.mark.skipif(not os.path.isfile(_TRIANGLE4XP), reason="Windows tool")
@pytest.mark.parametrize("budget,capped", [("20", True), ("1000000", False)])
def test_triangle4xp_reports_steiner_left(tmp_path, budget, capped):
    n = _hill_tile(tmp_path)
    cmd = [_TRIANGLE4XP, "-pq10AuYBQS" + budget, "63850", "111319",
           str(n), str(n), "0", "0", "1", "1", "-32768", "1",
           str(tmp_path / "t.alt"), str(tmp_path / "t.weight"),
           str(tmp_path / "t.poly")]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True)
    left = [MESH.parse_steiner_left(line) for line in out.stdout.splitlines()]
    left = [v for v in left if v is not None]
    assert len(left) == 1
    assert (left[0] == 0) == capped
    final = int((tmp_path / "t.1.node").read_text().split()[0])
    assert MESH.steiner_cap_reached(left[0], final, 29, float(budget)) == capped
    # Uncapped it needs 48 points: the old count test missed nothing here,
    # the report is what tells the two apart on real tiles.
    assert final == (29 + 20 if capped else 77)
