"""Every extent= in a provider .lay names an extent that exists."""
import os


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _extents():
    found = set()
    for _, _, files in os.walk(os.path.join(REPO, "Extents")):
        found.update(f[:-4] for f in files if f.endswith(".ext"))
    return found


def _lay_extents():
    for root, _, files in os.walk(os.path.join(REPO, "Providers")):
        for f in files:
            if not f.endswith(".lay"):
                continue
            with open(os.path.join(root, f), encoding="utf-8",
                      errors="replace") as lay:
                for line in lay:
                    if line.startswith("extent="):
                        yield f, line.split("=", 1)[1].strip()


def test_provider_extents_exist():
    known = _extents() | {"global"}
    missing = [(f, e) for (f, e) in _lay_extents() if e not in known]
    assert missing == []


def test_there_are_extents_to_check():
    assert len(_extents()) > 10
    assert any(True for _ in _lay_extents())
