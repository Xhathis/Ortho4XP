"""#53: reading water triangles for masks: Stop, and meshes under 100 triangles."""
import types

import pytest

import O4_File_Names as FNAMES
import O4_Mask_Utils as MASK
import O4_UI_Utils as UI


def _write_mesh(build_dir, lat, lon, tris):
    nodes = [(lon + 0.10, lat + 0.10), (lon + 0.20, lat + 0.10),
             (lon + 0.15, lat + 0.20), (lon + 0.25, lat + 0.20)]
    lines = ["MeshVersionFormatted 1.3", "Dimension 3", "", "Vertices",
             str(len(nodes))]
    lines += [f"{x} {y} 0 0" for (x, y) in nodes]
    lines += ["", "Normals", str(len(nodes))]
    lines += ["0 0" for _ in nodes]
    lines += ["", "Triangles", str(len(tris))]
    lines += [" ".join(str(v) for v in t) for t in tris]
    path = FNAMES.mesh_file(build_dir, lat, lon)
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


@pytest.fixture
def tile(tmp_path, monkeypatch):
    monkeypatch.setattr(UI, "red_flag", False)
    monkeypatch.setattr(UI, "progress_bar", lambda *a: None)
    return types.SimpleNamespace(
        lat=55, lon=12, build_dir=str(tmp_path), grouped=True, mask_zl=14,
        use_masks_for_inland=False,
    )


def test_small_mesh_is_read(tile):
    # 2 triangles: one sea (2), one land (0). Divided by zero before.
    _write_mesh(tile.build_dir, 55, 12, [(1, 2, 3, 2), (2, 4, 3, 0)])
    (dico_sea, dico_inland) = MASK.record_water_tris(tile)
    assert sum(len(v) for v in dico_sea.values()) >= 1
    assert dico_inland == {}


def test_stop_returns_none(tile, monkeypatch):
    _write_mesh(tile.build_dir, 55, 12, [(1, 2, 3, 2)] * 250)
    monkeypatch.setattr(UI, "exit_message_and_bottom_line", lambda *a: None)
    UI.red_flag = True
    assert MASK.record_water_tris(tile) is None
