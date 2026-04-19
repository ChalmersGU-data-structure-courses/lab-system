import contextlib
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from watchdog.observers import Observer
from watchdog.events import FileClosedEvent, FileMovedEvent, FileSystemEventHandler

logger = logging.getLogger(__name__)


@contextlib.contextmanager
def observing_path(
    path: Path,
    handler: FileSystemEventHandler,
    recursive: bool = False,
):
    observer = Observer()
    observer.schedule(handler, path, recursive=recursive)
    observer.start()
    try:
        yield
    finally:
        # Stopping is often slow (~10ms) because of this problem:
        # https://www.spinics.net/lists/linux-fsdevel/msg196221.html
        observer.stop()
        observer.join()


@dataclass(frozen=True)
class CallbackHandler(FileSystemEventHandler):
    callback: Callable[[], None]


@dataclass(frozen=True)
class CallbackOnFileCreated(CallbackHandler):
    path: Path

    def on_created(self, event):
        if Path(event.src_path) == self.path:
            logger.debug(f"received event {event}, triggering event object")
            self.callback()


@contextlib.contextmanager
def callback_on_file_created(path, callback: Callable[[], None]):
    with observing_path(path.parent, CallbackOnFileCreated(callback, path)):
        yield


@dataclass(frozen=True)
class CallbackOnFileChangedPositive(CallbackHandler):
    """Only checks for positive modifications (i.e., not deletion, renaming to other path)."""

    path: Path

    def conditions(self, e):
        yield isinstance(e, FileClosedEvent) and Path(e.src_path) == self.path
        yield isinstance(e, FileMovedEvent) and Path(e.dest_path) == self.path

    def on_any_event(self, event):
        if any(self.conditions(event)):
            self.callback()


@contextlib.contextmanager
def callback_on_file_changed_positive(path, callback: Callable[[], None]):
    with observing_path(path.parent, CallbackOnFileChangedPositive(callback, path)):
        yield


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

    with callback_on_file_created(file, event_object.set):
        # Initial check within file watching.
        if file.exists():
            return True

        # Wait for condition to hold.
        event_object.wait()

    return file.exists()
