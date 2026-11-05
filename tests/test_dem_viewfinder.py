"""Viewfinder elevation downloads (#38): best resolution, 1" / 3" fallback.

The server is replaced by a fake http_request serving small in-memory
zips, and Elevation_dir is the test sandbox (see conftest.py): no network,
no user data.
"""
import io
import os
import shutil
import zipfile

import pytest

import O4_DEM_Utils as DEM
import O4_File_Names as FNAMES

SIZE_1S = 3601 * 3601 * 2
SIZE_3S = 1201 * 1201 * 2


def old_zone(lat, lon):
    """The zone name as ensure_elevation computed it before #38."""
    deferranti_nbr = 31 + lon // 6
    if deferranti_nbr < 10:
        deferranti_nbr = "0" + str(deferranti_nbr)
    else:
        deferranti_nbr = str(deferranti_nbr)
    alphabet = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    deferranti_letter = (
        alphabet[lat // 4] if lat >= 0 else alphabet[(-1 - lat) // 4]
    )
    if lat < 0:
        deferranti_letter = "S" + deferranti_letter
    return deferranti_letter + deferranti_nbr


def test_zone_same_as_before_everywhere():
    for lat in range(-90, 90):
        for lon in range(-180, 180):
            assert DEM.viewfinder_zone(lat, lon) == old_zone(lat, lon), (lat, lon)


@pytest.mark.parametrize("lat, lon, zone", [
    (61, -50, "P22"), (60, -43, "P23"), (64, -50, "Q22"),
    (55, 12, "N33"), (-42, 174, "SK60"), (0, 0, "A31"), (-1, -1, "SA30"),
])
def test_zone_known_names(lat, lon, zone):
    assert DEM.viewfinder_zone(lat, lon) == zone


def test_resolutions_best_first_except_wellington():
    assert DEM.viewfinder_resolutions(61, -50) == (1, 3)
    assert DEM.viewfinder_resolutions(-42, 174) == (3,)


# --- _ensure_viewfinder against a fake server -------------------------------
class FakeServer:
    """archives: {"dem1/P22": {"N61W050.hgt": size}}; anything else 404."""

    def __init__(self, archives, down=False):
        self.archives, self.down, self.requests = archives, down, []

    def __call__(self, url, source, verbose=False):
        key = url.split("viewfinderpanoramas.org/")[1][:-len(".zip")]
        self.requests.append(key)
        DEM.http_request.not_found = False
        if self.down:
            return 0
        if key not in self.archives:
            DEM.http_request.not_found = True
            return 0
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for name, size in self.archives[key].items():
                z.writestr(f"{key[-3:]}/{name}", bytes(size))
        return type("Response", (), {"content": buf.getvalue()})()


@pytest.fixture
def server(monkeypatch):
    shutil.rmtree(FNAMES.Elevation_dir, ignore_errors=True)
    holder = {}

    def install(archives, down=False):
        fake = FakeServer(archives, down)
        # Keep the attribute on the real function too: the code reads
        # http_request.not_found from whatever http_request is.
        monkeypatch.setattr(DEM, "http_request", fake)
        holder["fake"] = fake
        return fake

    yield install
    shutil.rmtree(FNAMES.Elevation_dir, ignore_errors=True)


def hgt(lat, lon):
    return FNAMES.viewfinderpanorama(lat, lon)


def put(lat, lon, size):
    os.makedirs(os.path.dirname(hgt(lat, lon)), exist_ok=True)
    with open(hgt(lat, lon), "wb") as f:
        f.write(bytes(size))


def no_1s_zones():
    return DEM._no_1s_zones()


def test_downloads_1s_when_only_1s_exists(server):
    # The +61-050 case: P22 is published at 1" only; the old code asked
    # for dem3/P22 and failed.
    fake = server({"dem1/P22": {"n61w050.hgt": SIZE_1S, "n62w050.hgt": SIZE_1S}})
    assert DEM._ensure_viewfinder(61, -50) == 1
    assert fake.requests == ["dem1/P22"]
    assert os.path.getsize(hgt(61, -50)) == SIZE_1S
    assert os.path.getsize(hgt(62, -50)) == SIZE_1S  # the neighbour too


def test_prefers_1s_when_both_exist(server):
    fake = server({"dem1/N33": {"N55E012.hgt": SIZE_1S},
                   "dem3/N33": {"N55E012.hgt": SIZE_3S}})
    assert DEM._ensure_viewfinder(55, 12) == 1
    assert fake.requests == ["dem1/N33"]
    assert os.path.getsize(hgt(55, 12)) == SIZE_1S


def test_falls_back_to_3s_and_remembers(server):
    fake = server({"dem3/E36": {"N17E030.hgt": SIZE_3S}})
    assert DEM._ensure_viewfinder(17, 30) == 1
    assert fake.requests == ["dem1/E36", "dem3/E36"]
    assert os.path.getsize(hgt(17, 30)) == SIZE_3S
    assert no_1s_zones() == {"E36"}
    # Next build: the 3" file is recycled without asking again.
    fake.requests.clear()
    assert DEM._ensure_viewfinder(17, 30) == 1
    assert fake.requests == []


def test_upgrades_existing_3s(server):
    put(55, 12, SIZE_3S)
    fake = server({"dem1/N33": {"N55E012.hgt": SIZE_1S}})
    assert DEM._ensure_viewfinder(55, 12) == 1
    assert fake.requests == ["dem1/N33"]
    assert os.path.getsize(hgt(55, 12)) == SIZE_1S


def test_keeps_existing_3s_when_no_1s(server):
    put(17, 30, SIZE_3S)
    fake = server({})
    assert DEM._ensure_viewfinder(17, 30) == 1
    assert fake.requests == ["dem1/E36"]  # never the 3" archive again
    assert os.path.getsize(hgt(17, 30)) == SIZE_3S
    assert no_1s_zones() == {"E36"}


def test_same_resolution_neighbour_left_untouched(server):
    # P22 also holds N61W049, already in the library at 1": the zone
    # download must not rewrite it (upstream re-extracted equal sizes).
    put(61, -49, SIZE_1S)
    with open(hgt(61, -49), "r+b") as f:
        f.write(b"library")
    server({"dem1/P22": {"n61w050.hgt": SIZE_1S, "n61w049.hgt": SIZE_1S}})
    assert DEM._ensure_viewfinder(61, -50) == 1
    with open(hgt(61, -49), "rb") as f:
        assert f.read(7) == b"library"


@pytest.mark.parametrize("size", [SIZE_1S, 7201 * 7201 * 2])
def test_1s_or_finer_never_downloaded_or_replaced(server, size):
    put(55, 12, size)
    fake = server({"dem1/N33": {"N55E012.hgt": SIZE_1S}})
    assert DEM._ensure_viewfinder(55, 12) == 1
    assert fake.requests == []
    assert os.path.getsize(hgt(55, 12)) == size


def test_finer_file_not_overwritten_by_zone_download(server):
    # A custom 0.5" file of another tile in the same zone stays.
    put(56, 12, 7201 * 7201 * 2)
    server({"dem1/N33": {"N55E012.hgt": SIZE_1S, "N56E012.hgt": SIZE_1S}})
    assert DEM._ensure_viewfinder(55, 12) == 1
    assert os.path.getsize(hgt(56, 12)) == 7201 * 7201 * 2


def test_nothing_published(server):
    fake = server({})
    assert DEM._ensure_viewfinder(17, 30) == 0
    assert fake.requests == ["dem1/E36", "dem3/E36"]
    assert not os.path.exists(hgt(17, 30))


def test_server_down_is_not_remembered_as_no_1s(server):
    put(17, 30, SIZE_3S)
    server({}, down=True)
    assert DEM._ensure_viewfinder(17, 30) == 1  # the 3" file is used
    assert no_1s_zones() == set()  # but 1" is tried again next time


def test_archive_without_the_tile(server):
    server({"dem1/P22": {"n61w049.hgt": SIZE_1S}})
    assert DEM._ensure_viewfinder(61, -50) == 0


def test_wellington_stays_3s(server):
    fake = server({"dem1/SK60": {"S42E174.hgt": SIZE_1S},
                   "dem3/SK60": {"S42E174.hgt": SIZE_3S}})
    assert DEM._ensure_viewfinder(-42, 174) == 1
    assert fake.requests == ["dem3/SK60"]
    assert os.path.getsize(hgt(-42, 174)) == SIZE_3S
    fake.requests.clear()
    assert DEM._ensure_viewfinder(-42, 174) == 1  # recycled, no upgrade
    assert fake.requests == []


def test_ensure_elevation_view_goes_through_new_code(server):
    server({"dem1/P22": {"n61w050.hgt": SIZE_1S}})
    assert DEM.ensure_elevation("View", 61, -50) == 1
