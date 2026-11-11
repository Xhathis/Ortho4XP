"""#47: an exception in a thread pool task fails that item, not the worker."""
import queue
import threading

import pytest

import O4_Parallel_Utils as PAR
import O4_UI_Utils as UI


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(UI, "red_flag", False)
    logged = []
    monkeypatch.setattr(UI, "lvprint", lambda level, *a: logged.append(a))
    return logged


def _run(task, items, workers=4):
    q = queue.Queue()
    for item in items:
        q.put(item)
    return PAR.parallel_execute(task, q, workers)


def test_all_items_done_and_success_when_nothing_fails():
    done = []
    lock = threading.Lock()

    def task(i):
        with lock:
            done.append(i)
        return 1

    assert _run(task, [(i,) for i in range(50)]) == 1
    assert sorted(done) == list(range(50))


def test_one_failing_item_fails_the_run_but_not_the_others(_quiet):
    done = []
    lock = threading.Lock()

    def task(i):
        if i == 7:
            raise OSError("image file is truncated")
        with lock:
            done.append(i)
        return 1

    assert not _run(task, [(i,) for i in range(50)])
    assert sorted(done) == [i for i in range(50) if i != 7]
    assert len(_quiet) == 1
    line = " ".join(str(x) for x in _quiet[0])
    assert "task(7)" in line and "OSError" in line and "truncated" in line


def test_every_item_is_tried_even_when_all_of_them_fail():
    # Before #47 the 4 workers died on their first item and 46 items were
    # never tried, while the run reported success.
    tried = []
    lock = threading.Lock()

    def task(i):
        with lock:
            tried.append(i)
        raise MemoryError()

    assert not _run(task, [(i,) for i in range(50)])
    assert sorted(tried) == list(range(50))


def test_log_line_leaves_out_big_arguments(_quiet):
    def get_and_paste(zl, x, y, provider, image, session):
        raise ValueError("bad")

    _run(get_and_paste, [(17, 70000, 40000, {"code": "Arc"}, object(),
                          object())], workers=1)
    line = " ".join(str(x) for x in _quiet[0])
    assert "get_and_paste(17, 70000, 40000)" in line


def test_launched_workers_survive_a_failing_item():
    done = []
    q = queue.Queue()

    def task(i):
        if i == 0:
            raise RuntimeError("boom")
        done.append(i)

    workers = PAR.parallel_launch(task, q, 1)
    for i in range(5):
        q.put((i,))
    q.put("quit")
    PAR.parallel_join(workers)
    assert done == [1, 2, 3, 4]


def test_convert_task_records_an_exception_as_failed_conversion(monkeypatch):
    import O4_Imagery_Utils as IMG
    import O4_Tile_Utils as TILE

    def broken(tile, *attrs):
        raise OSError("cannot identify image file")

    monkeypatch.setattr(IMG, "convert_texture", broken)
    monkeypatch.setattr(IMG, "failed_conversions", [])
    TILE._convert_task(None, 69952, 40576, 17, "Arc")
    import O4_File_Names as FNAMES
    assert IMG.failed_conversions == [
        FNAMES.dds_file_name_from_attributes(69952, 40576, 17, "Arc")
    ]


class _WriteLog(list):
    """success list that records every write."""

    def __init__(self):
        super().__init__([1])
        self.writes = []

    def __setitem__(self, i, v):
        self.writes.append(v)
        super().__setitem__(i, v)


def test_successful_items_never_write_the_shared_result():
    # #85: a write by a successful item could overwrite a failure stored
    # by another thread in between its read and its write.
    q = queue.Queue()
    for item in [(1,), (0,), (1,), (1,)]:
        q.put(item)
    q.put("quit")
    success = _WriteLog()
    PAR.parallel_worker(lambda r: r, q, None, success).run()
    assert success.writes == [0]
    assert success[0] == 0
