"""#89: improved_buffer uses quad_segs (shapely 2), not the deprecated
resolution argument, which a future shapely removes."""
import warnings

from shapely import geometry

import O4_Vector_Utils as VECT
import O4_UI_Utils as UI


def test_improved_buffer_no_deprecation_warning(monkeypatch):
    monkeypatch.setattr(UI, "red_flag", False)
    poly = geometry.Polygon([(12.1, 55.1), (12.2, 55.1), (12.2, 55.2)])
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        out = VECT.improved_buffer(poly, 20, 3, 0.5)
    assert out.area > poly.area
