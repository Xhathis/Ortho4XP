"""#87: a texture's shared session has a connection per download thread."""
import O4_Imagery_Utils as IMG


def test_pool_holds_one_connection_per_thread():
    s = IMG.texture_session(16)
    try:
        for prefix in ("https://", "http://"):
            assert s.get_adapter(prefix + "x")._pool_maxsize == 16
    finally:
        s.close()


def test_pool_never_below_requests_default():
    s = IMG.texture_session(4)
    try:
        assert s.get_adapter("https://x")._pool_maxsize == 10
    finally:
        s.close()


def test_max_threads_default_and_lay_value():
    assert IMG._max_threads({}) == 16
    assert IMG._max_threads({"max_threads": "8"}) == 8
