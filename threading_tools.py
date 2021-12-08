import contextlib
import logging
import threading

import general


logger = logging.getLogger(__name__)

# From https://stackoverflow.com/a/48741004.
class RepeatTimer(threading.Timer):
    def run(self):
        while not self.finished.wait(self.interval):
            self.function(*self.args, **self.kwargs)

@contextlib.contextmanager
def thread_manager(thread):
    logger.debug(f'starting thread {thread.name}')
    thread.start()
    try:
        yield
    finally:
        logger.debug(f'waiting for thread {thread.name} to join...')
        thread.join()
        logger.debug('thread {thread.name} has joined')

@contextlib.contextmanager
def timer_manager(timer):
    def cleanup():
        logger.debug(f'cancelling timer {timer.name}')
        timer.cancel()

    return general.add_cleanup(thread_manager(timer), cleanup)
