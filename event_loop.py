import contextlib
import dataclasses
import datetime
import logging
import threading

import events
import general
import print_parse
import ssh_tools
import subsuming_queue
import threading_tools
import webhook_listener


@dataclasses.dataclass
class WebhookConfig:
    netloc_listen: print_parse.NetLoc
    '''The local net location to listen at for webhook notifications.'''

    netloc_specify: print_parse.NetLoc
    '''The net location to specify in the webhook configuration.'''

    secret_token: str
    '''
    Secret token to use for webhook authentication.
    The value does not matter, but it should not be guessable.
    '''

logger = logging.getLogger(__name__)

def run(
    courses,
    run_time = None,
    webhook_config = None,
):
    '''
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
        Optional instance of datetime.timedelta.
        If set, the event loop will exit after this period has elapsed.
        This is the only way for this function to return.
    * webhook_config:
        Optional instance of WebhookConfig.
        Configuration for webhook notifications from GitLab Chalmers.
        Set to None to disable the webhook mechanism in the event loop.
    '''
    # Resource management.
    exit_stack = contextlib.ExitStack()
    with exit_stack:

        # The event queue.
        event_queue = subsuming_queue.SubsumingQueue()

        def shutdown():
            event_queue.add((events.TerminateProgram(), None))

        # Context managers for threads we create.
        thread_managers = []

        # Configure SSH multiplexers.
        # Ideally, all courses connect to the same SSH server.
        def f():
            for ssh_netloc in set(c.config.gitlab_ssh.netloc for c in courses):
                multiplexer = ssh_tools.Multiplexer(ssh_netloc)
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
                c.hooks_ensure(netloc = webhook_config.netloc_specify)

            courses_by_groups_path = {c.config.path_course: c for c in courses}

            def add_webhook_event(hook_event):
                for result in webhook_listener.parse_hook_event(
                    courses_by_groups_path = courses_by_groups_path,
                    hook_event = hook_event,
                    strict = False,
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
            webhook_server_thread = threading.Thread(
                target = webhook_server_run,
                name = 'webhook-server-listener',
            )
            thread_managers.append(general.add_cleanup(
                threading_tools.thread_manager(webhook_server_thread),
                webhook_server.shutdown,
            ))

        # Set up program termination timer.
        if run_time is not None:
            shutdown_timer = threading_tools.Timer(
                run_time,
                shutdown,
                name = 'shutdown-timer',
            )
            thread_managers.append(threading_tools.timer_manager(shutdown_timer))

        # Set up lab refresh event timers and add initial lab refreshes.
        def refresh_lab(lab):
            event_queue.add((
                lab.course.program_event(lab.course_event(events.RefreshLab())),
                lab.refresh_lab,
            ))
        delay = datetime.timedelta()
        for c in courses:
            for lab in c.labs.values():
                refresh_lab(lab)
                if lab.config.refresh_period is not None:
                    lab.refresh_timer = threading_tools.Timer(
                        lab.config.refresh_period + delay,
                        refresh_lab,
                        args = [lab],
                        name = f'lab-refresh-timer<{c.config.path_course}, {lab.name}>',
                        repeat = True,
                    )
                    thread_managers.append(threading_tools.timer_manager(lab.refresh_timer))
                    delay += c.config.webhook.first_lab_refresh_delay

        # Start the threads.
        for manager in thread_managers:
            exit_stack.enter_context(manager)

        # The event loop.
        while True:
            logger.info('Waiting for event.')
            (event, callback) = event_queue.remove()
            if isinstance(event, events.TerminateProgram):
                logger.info('Program termination event received, shutting down.')
                return

            logger.info(f'Handling event {event}')
            callback()
