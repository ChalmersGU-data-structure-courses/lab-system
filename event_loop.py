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
class WebhookConfig:
    """Configuration for webhooks."""

    netloc_listen: util.url.NetLoc
    """The local net location to listen at for webhook notifications."""

    netloc_specify: util.url.NetLoc
    """The net location to specify in the webhook configuration."""

    secret_token: str
    """
    Secret token to use for webhook authentication.
    The value does not matter, but it should not be guessable.
    """


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
    run_time: Optional[datetime.timedelta] = None,
    webhook_config: Optional[WebhookConfig] = None,
    canvas_sync_config: Optional[CanvasSyncConfig] = None,
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
    * run_time:
        If set, the event loop will exit after this period has elapsed.
        This is the only way for this function to return.
    * webhook_config:
        Configuration for webhook notifications from GitLab Chalmers.
        Set to None to disable the webhook mechanism in the event loop.
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

        # Configure SSH multiplexers.
        # Ideally, all courses connect to the same SSH server.
        def f():
            for ssh_netloc in set(c.config.gitlab_ssh.netloc for c in courses):
                multiplexer = util.ssh.Multiplexer(ssh_netloc)
                exit_stack.enter_context(contextlib.closing(multiplexer))
                yield (ssh_netloc, multiplexer)

        ssh_multiplexers = dict(f())
        for c in courses:
            c.ssh_multiplexer = ssh_multiplexers[c.config.gitlab_ssh.netloc]

        # Set up courses.
        for c in courses:
            c.setup()

        # Configure webhooks.
        if webhook_config is not None:
            for c in courses:
                c.hooks_ensure(netloc=webhook_config.netloc_specify)

            courses_by_groups_path = {c.config.path_course: c for c in courses}

            def add_webhook_event(hook_event):
                for result in webhook_listener.parse_hook_event(
                    courses_by_groups_path=courses_by_groups_path,
                    hook_event=hook_event,
                    strict=False,
                ):
                    event_queue.add(result)

            webhook_listener_manager = webhook_listener.server_manager(
                webhook_config.netloc_listen,
                webhook_config.secret_token,
                add_webhook_event,
            )
            webhook_server = exit_stack.enter_context(webhook_listener_manager)

            def webhook_server_run():
                try:
                    webhook_server.serve_forever()
                finally:
                    shutdown()

            def webhook_server_shutdown():
                webhook_server.shutdown()

            webhook_server_thread = threading.Thread(
                target=webhook_server_run,
                name="webhook-server-listener",
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
                    lab.refresh_timer = util.threading.Timer(
                        lab.config.refresh_period + delay,
                        refresh_lab,
                        args=[lab],
                        name=f"lab-refresh-timer<{c.config.path_course}, {lab.name}>",
                        repeat=True,
                    )
                    thread_managers.append(
                        util.threading.timer_manager(lab.refresh_timer)
                    )
                    delay += c.config.webhook.first_lab_refresh_delay

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
