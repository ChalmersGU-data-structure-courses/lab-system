import contextlib
import logging
from pathlib import Path, PurePath
import threading

import watchdog


logger = logging.getLogger(__name__)

@contextlib.contextmanager
def observing_path(path, handler, recursive = False):
    observer = watchdog.observers.Observer()
    observer.schedule(handler, path, recursive)
    observer.start()
    try:
        yield
    finally:
        # Stopping is often slow (~10ms) because of this problem:
        # https://www.spinics.net/lists/linux-fsdevel/msg196221.html
        observer.stop()

        # This is  slow (~1s) before watchdog-2.1.7.
        # Comment out for now.
        #observer.join()

class NotifyOnFileCreated(watchdog.events.FileSystemEventHandler):
    def __init__(self, path, condition):
        self.path = PurePath(path)
        self.condition = condition

    def on_created(self, event):
        if PurePath(event.src_path) == self.path:
            logger.debug(f'received event {event}, triggering condition')
            with self.condition:
                self.condition.notify()

def notify_on_file_created(file, condition):
    '''
    Return a context manager within which the given condition
    is triggered if the given filename is created.
    '''
    file = Path(file)
    return observing_path(
        file.parent,
        NotifyOnFileCreated(file, condition)
    )

def wait_for_file_created(file, condition = None, initial_check = True):
    '''
    Wait until a file is created.

    Arguments:
    file:
        A path-like object.
        The path of the file to wait for.
    condition:
        An optional condition object (instance of threading.Condition).
        If given, it is used to wait for the file.
        This allows the caller to trigger the condition in other ways.
        This is useful for error recovery.
    initial_check:
        Whether to perform an initial check for the file
        to short-cut the notification machinery.

    Returns a boolean indicating if the file has been created.
    '''
    # Initial check (to avoid unnecessary creation of notification machinery).
    if initial_check:
        file = Path(file)
        if file.exists():
            return True

    # Create condition object if not given.
    if condition is None:
        condition = threading.Condition()

    with notify_on_file_created(file, condition):
        # Initial check within file watching.
        file = Path(file)
        if file.exists():
            return True

        # Wait for condition to hold.
        with condition:
            condition.wait()

    return file.exists()
