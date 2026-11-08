"""alt_vec_nostrict with fancy indexing equals the old per-point lookup."""
import types

import numpy
import pytest

import O4_DEM_Utils as DEM


def _old_alt_vec_nostrict(self, way):
    # The implementation before the speedup, kept verbatim as the reference.
    Nx = self.nxdem - 1
    Ny = self.nydem - 1
    x, y = way[:, 0], way[:, 1]
    x = numpy.maximum.reduce([x, self.x0 * numpy.ones(x.shape)])
    x = numpy.minimum.reduce([x, self.x1 * numpy.ones(x.shape)])
    y = numpy.maximum.reduce([y, self.y0 * numpy.ones(y.shape)])
    y = numpy.minimum.reduce([y, self.y1 * numpy.ones(y.shape)])
    px = (x - self.x0) / (self.x1 - self.x0) * Nx
    py = (y - self.y0) / (self.y1 - self.y0) * Ny
    nx = px.astype(numpy.uint16)
    Nminusny = Ny - py.astype(numpy.uint16)
    rx = px - nx
    ry = py + Nminusny - Ny
    t1 = [self.alt_dem[i][j] for i, j in zip(Nminusny, nx)]
    t2 = [
        self.alt_dem[i][j]
        for i, j in zip(
            (Nminusny - 1) * (Nminusny >= 1),
            (nx + 1) * (nx < Nx) + Nx * (nx == Nx),
        )
    ]
    t3 = [
        self.alt_dem[i][j]
        for i, j in zip(Nminusny, (nx + 1) * (nx < Nx) + Nx * (nx == Nx))
    ]
    t4 = [
        self.alt_dem[i][j]
        for i, j in zip((Nminusny - 1) * (Nminusny >= 1), nx)
    ]
    return ((1 - rx) * t1 + ry * t2 + (rx - ry) * t3) * (rx >= ry) + (
        (1 - ry) * t1 + rx * t2 + (ry - rx) * t4
    ) * (rx < ry)


@pytest.fixture(params=[(3601, 3601), (1201, 1201), (97, 53)])
def dem(request):
    ny, nx = request.param
    rng = numpy.random.default_rng(nx * ny)
    return types.SimpleNamespace(
        nxdem=nx, nydem=ny, x0=0.0, x1=1.0, y0=0.0, y1=1.0,
        alt_dem=(rng.random((ny, nx)) * 3000 - 100).astype(numpy.float32),
    )


def test_same_bytes_as_before(dem):
    rng = numpy.random.default_rng(1)
    way = rng.random((20000, 2)) * 1.2 - 0.1  # also outside the tile
    edges = numpy.array([[0, 0], [1, 1], [0, 1], [1, 0], [0.5, 1], [1, 0.5],
                         [-5, 7], [1 - 1e-12, 1e-12]])
    way = numpy.vstack([way, edges])
    new = DEM.DEM.alt_vec_nostrict(dem, way)
    old = _old_alt_vec_nostrict(dem, way)
    assert new.dtype == old.dtype
    assert new.tobytes() == old.tobytes()


def test_empty_way(dem):
    way = numpy.zeros((0, 2))
    assert DEM.DEM.alt_vec_nostrict(dem, way).shape == (0,)
