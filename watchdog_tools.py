import contextlib
import logging
from pathlib import Path, PurePath
import threading

import watchdog
import watchdog.events
import watchdog.observers


logger = logging.getLogger(__name__)


@contextlib.contextmanager
def observing_path(path, handler, recursive=False):
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
        # observer.join()


class NotifyOnFileCreated(watchdog.events.FileSystemEventHandler):
    def __init__(self, path, event_object):
        self.path = PurePath(path)
        self.event_object = event_object

    def on_created(self, event):
        if PurePath(event.src_path) == self.path:
            logger.debug(f"received event {event}, triggering event object")
            self.event_object.set()


def notify_on_file_created(file, event_object):
    """
    Return a context manager within which the given event object
    is triggered if the given filename is created.
    """
    file = Path(file)
    return observing_path(file.parent, NotifyOnFileCreated(file, event_object))


def wait_for_file_created(file, event_object=None, initial_check=True):
    """
    Wait until a file is created.

    Arguments:
    file:
        A path-like object.
        The path of the file to wait for.
    event_object:
        An optional event object (instance of threading.Event).
        If given, it is used to wait for the file.
        This allows the caller to trigger the event in other ways.
        This is useful for error recovery.
    initial_check:
        Whether to perform an initial check for the file
        to short-cut the notification machinery.

    Returns a boolean indicating if the file has been created.
    """
    # Initial check (to avoid unnecessary creation of notification machinery).
    file = Path(file)
    if initial_check:
        if file.exists():
            return True

    # Create condition object if not given.
    if event_object is None:
        event_object = threading.Event()

    with notify_on_file_created(file, event_object):
        # Initial check within file watching.
        if file.exists():
            return True

        # Wait for condition to hold.
        event_object.wait()

    return file.exists()
