import contextlib
import datetime
import logging
import threading

import util.general


logger = logging.getLogger(__name__)


# From https://stackoverflow.com/a/48741004.
class RepeatTimer(threading.Timer):
    def run(self):
        while not self.finished.wait(self.interval):
            self.function(*self.args, **self.kwargs)


def Timer(
    interval,
    callback,
    args=None,
    kwargs=None,
    name=None,
    repeat=False,
):
    """
    Wrapper around the constructors of threading.Timer and RepeatTimer.

    Arguments:
    * interval:
        The timer interval specified as either:
        - an instance of datetime.timedelta,
        - an integer or floating-point number.
    * callback:
        As for the constructor of threading.Timer.
    * args, kwargs:
        The positional and keyword arguments for the constructor of threading.Timer.
    * name:
        An optional thread name for the timer thread.
    * repeat:
        Whether the timer should trigger repeatedly after each interval instead of just one.
    """
    if args is None:
        args = []
    if kwargs is None:
        kwargs = {}

    interval = (
        interval.total_seconds()
        if isinstance(interval, datetime.timedelta)
        else interval
    )
    cls = RepeatTimer if repeat else threading.Timer
    timer = cls(interval, callback, args=args, kwargs=kwargs)
    timer.name = name
    return timer


@contextlib.contextmanager
def thread_manager(thread):
    logger.debug(f"starting thread {thread.name}")
    thread.start()
    try:
        yield
    finally:
        logger.debug(f"waiting for thread {thread.name} to join...")
        thread.join()
        logger.debug(f"thread {thread.name} has joined")


def timer_manager(timer):
    def cleanup():
        logger.debug(f"cancelling timer {timer.name}")
        timer.cancel()

    return util.general.add_cleanup(thread_manager(timer), cleanup)


class FunctionThread(threading.Thread):
    def __init__(self, function):
        def runner(*args, **kwargs):
            self.result = function(*args, **kwargs)

        super().__init__(target=runner)
        self.start()

    def get_result(self):
        self.join()
        return self.result


class FileReader(FunctionThread):
    def __init__(self, file):
        def reader():
            return file.read()

        super().__init__(function=reader)
