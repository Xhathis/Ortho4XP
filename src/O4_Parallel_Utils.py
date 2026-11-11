import threading
import traceback
import O4_UI_Utils as UI


################################################################################
def _describe_args(args):
    # Only the simple arguments (tile coordinates, zoom level, provider code):
    # images, sessions and tiles would flood the log line.
    return ", ".join(
        repr(a) for a in args
        if isinstance(a, (int, float, str)) and not isinstance(a, bool)
    )

################################################################################
class parallel_worker(threading.Thread):
    def __init__(self, task, queue, progress=None, success=None):
        threading.Thread.__init__(self)
        self._task = task
        self._queue = queue
        self._progress = progress
        # A shared default list ([1]) was reused by every worker started
        # without one, so one falsy task result stuck for the whole run.
        self._success = success if success is not None else [1]

    def run(self):
        while True:
            args = self._queue.get()
            if isinstance(args, str) and args == "quit":
                try:
                    UI.progress_bar(self._progress["bar"], 100)
                except Exception:  # cosmetic: no progress dict, GUI closed
                    pass
                return 1
            try:
                result = self._task(*args)
            except Exception as e:
                # An exception used to end this thread: its item was lost,
                # the remaining items went to the other workers (or to none
                # once all of them had died), and the run still counted as
                # a success. That gave silently missing masks (#1), DDS
                # textures and black squares in downloaded imagery. Now the
                # item fails, the caller sees it, and the worker goes on.
                UI.lvprint(
                    0,
                    "ERROR:",
                    getattr(self._task, "__name__", "task")
                    + "(" + _describe_args(args) + ")",
                    f"failed: {type(e).__name__}: {e}",
                )
                UI.vprint(1, traceback.format_exc())
                result = 0
            if not result:
                # Only a failure writes. The old "s[0] = result and s[0]"
                # was a read-modify-write: a worker that had read 1 could
                # store it after another stored 0, and a failed item (a
                # white imagery piece, a missing mask) was lost (#85).
                self._success[0] = 0
            if self._progress:
                self._progress["done"] += 1
                UI.progress_bar(
                    self._progress["bar"],
                    int(
                        100
                        * self._progress["done"]
                        / (self._progress["done"] + self._queue.qsize())
                    ),
                )
            if UI.red_flag:
                return 0

################################################################################
def parallel_execute(task, queue, nbr_workers, progress=None):
    workers = []
    success = [1]
    for _ in range(nbr_workers):
        queue.put("quit")
        worker = parallel_worker(task, queue, progress, success)
        worker.start()
        workers.append(worker)
    for worker in workers:
        worker.join()
    if UI.red_flag:
        return 0
    return success[0]


################################################################################
def parallel_launch(task, queue, nbr_workers, progress=None):
    workers = []
    for _ in range(nbr_workers):
        worker = parallel_worker(task, queue, progress)
        worker.start()
        workers.append(worker)
    return workers

################################################################################
def parallel_join(workers):
    for worker in workers:
        worker.join()