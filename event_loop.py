import contextlib
import dataclasses
import datetime
import faulthandler
import logging
import threading
from typing import Optional

import events
import util.general
import util.print_parse
import util.ssh
import util.subsuming_queue
import util.threading
import util.url
import webhook_listener


@dataclasses.dataclass
class CanvasSyncConfig:
    """Configuration for synchronizing teachers, students, and groups from Canvas to GitLab."""

    labs_to_sync: tuple
    """Tuple of lab ids to synchronize."""

    sync_interval: Optional[datetime.timedelta]
    """
    How often to synchronize.
    If not set, don't synchronize except potentially at the start.
    """

    start_with_sync: bool
    """
    Whether to start with a synchronization.
    If false, the first synchronization occurs after sync_interval.
    """


logger = logging.getLogger(__name__)


def run(
    courses,
    enable_webhooks: bool = None,
    run_time: datetime.timedelta | None = None,
    canvas_sync_config: CanvasSyncConfig | None = None,
):
    """
    Run the event loop.

    This method only returns after an event of
    kind TerminateProgram has been processed.

    The event loop starts with processing of all labs.
    So it is unnecessary to prefix it with a call to initial_run.

    Arguments:
    * courses:
        Collection of instances of course.Course.
        The courses to run the event loop for.
        This function takes care of calling setup.
    * enable_webhooks:
        Whether to enable webhooks.
        If set, configured webhooks for courses where they are configured.
    * run_time:
        If set, the event loop will exit after this period has elapsed.
        This is the only way for this function to return.
    * canvas_sync_config:
        Configuration for the mechanism synchronizing graders, students, and groups from Canvas to GitLab.
        Set to None to disable.
    """
    # Resource management.
    exit_stack = contextlib.ExitStack()
    with exit_stack:

        # The event queue.
        event_queue = util.subsuming_queue.SubsumingQueue()

        def shutdown():
            event_queue.add((events.TerminateProgram(), None))

        # Context managers for threads we create.
        thread_managers = []

        # Set up courses.
        for c in courses:
            c.setup()

        # Configure webhooks.
        if enable_webhooks:
            courses_by_netloc = util.general.multidict(
                (c.webhook_netloc_listen, c) for c in courses if c.webhooks_enabled
            )
            for netloc, cs in courses_by_netloc.items():
                netloc_str = util.url.netloc_formatter.print(netloc)
                try:
                    secret = util.general.from_singleton(
                        {c.auth.gitlab_webhook_secret_token for c in cs}
                    )
                except util.general.UniquenessError as e:
                    raise ValueError(
                        f"Courses with webhook_netloc_listen {netloc_str} "
                        "have incompatible gitlab_webhook_secret_token."
                    ) from e

                for c in cs:
                    c.hooks_ensure()

                def add_webhook_event(
                    hook_event,
                    courses_by_groups_path={c.config.path_course: c for c in cs},
                ):
                    for result in webhook_listener.parse_hook_event(
                        courses_by_groups_path=courses_by_groups_path,
                        hook_event=hook_event,
                        strict=False,
                    ):
                        event_queue.add(result)

                webhook_listener_manager = webhook_listener.server_manager(
                    netloc,
                    secret,
                    add_webhook_event,
                )
                webhook_server = exit_stack.enter_context(webhook_listener_manager)

                def webhook_server_run(webhook_server=webhook_server):
                    try:
                        webhook_server.serve_forever()
                    finally:
                        shutdown()

                def webhook_server_shutdown(webhook_server=webhook_server):
                    webhook_server.shutdown()

                webhook_server_thread = threading.Thread(
                    target=webhook_server_run,
                    name=f"webhook-server-listener-{netloc_str}",
                )
                thread_managers.append(
                    util.general.add_cleanup(
                        util.threading.thread_manager(webhook_server_thread),
                        webhook_server_shutdown,
                    )
                )

            # Set up program termination timer.
            if run_time is not None:
                shutdown_timer = util.threading.Timer(
                    run_time,
                    shutdown,
                    name="shutdown-timer",
                )
                thread_managers.append(util.threading.timer_manager(shutdown_timer))

        # Set up Canvas sync event timers and add potential initial sync.
        def sync_from_canvas(course):
            event_queue.add(
                (
                    course.program_event(events.SyncFromCanvas()),
                    lambda: course.sync_teachers_and_lab_projects(
                        canvas_sync_config.labs_to_sync
                    ),
                )
            )

        if canvas_sync_config is not None:
            for course in courses:
                if canvas_sync_config.start_with_sync:
                    sync_from_canvas(course)
                if canvas_sync_config.sync_interval is not None:
                    course.sync_timer = util.threading.Timer(
                        canvas_sync_config.sync_interval,
                        sync_from_canvas,
                        args=[course],
                        name=(
                            "course-sync-from-canvas-timer"
                            f"<{course.config.path_course}>"
                        ),
                        repeat=True,
                    )
                    thread_managers.append(
                        util.threading.timer_manager(course.sync_timer)
                    )

        # Set up lab refresh event timers and add initial lab refreshes.
        def refresh_lab(lab):
            event_queue.add(
                (
                    lab.course.program_event(lab.course_event(events.RefreshLab())),
                    lab.refresh_lab,
                )
            )

        delay = datetime.timedelta()
        for c in courses:
            for lab in c.labs.values():
                refresh_lab(lab)
                if lab.config.refresh_period is not None:
                    refresh_timer = util.threading.Timer(
                        lab.config.refresh_period + delay,
                        refresh_lab,
                        args=[lab],
                        name=f"lab-refresh-timer<{c.config.path_course}, {lab.name}>",
                        repeat=True,
                    )
                    thread_managers.append(util.threading.timer_manager(refresh_timer))
                    delay += c.config.first_lab_refresh_delay

        # Start the threads.
        for manager in thread_managers:
            exit_stack.enter_context(manager)

        @contextlib.contextmanager
        def print_stacks():
            try:
                yield
            finally:
                faulthandler.dump_traceback()

        # Print stacks before cleanup to help debug stalling.
        exit_stack.enter_context(print_stacks())

        # The event loop.
        while True:
            logger.info("Waiting for event.")
            (event, callback) = event_queue.remove()
            if isinstance(event, events.TerminateProgram):
                logger.info("Program termination event received, shutting down.")
                return

            logger.info(f"Handling event {event}")
            callback()
