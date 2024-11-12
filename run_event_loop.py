#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK

import argcomplete
import argparse
from pathlib import Path
import os


p = argparse.ArgumentParser(
    add_help=False,
    description="""
Manage labs for specified courses in an event loop.
""",
    epilog="""
This Python script supports bash completion.
For this, python-argparse needs to be installed and configured.
See https://github.com/kislyuk/argcomplete for more information.
""",
)


def complete_nothing(**kwargs):
    return list()


g = p.add_argument_group(title="main options")

g.add_argument(
    "action",
    choices=["run", "create_webhooks", "delete_webhooks"],
    type=str,
    help="""
The action to perform.
---
'Run' runs the event loop.
If webhooks are missing or incorrectly configured, they are deleted and recreated.
The program exits on error.
---
'Create_webhooks' creates the necessary webhooks in the relevant projects.
Note that this will create redundant copies of webhooks if called multiple times without deletion.
---
'Delete_webhooks' deletes all webhooks in the relevant projects.
Use this to clean up after you stop running the event loop (unless you plan to restart it soon).
""",
)


def complete_local_dir(prefix, action, parser, parsed_args):
    path = Path(prefix)
    if not prefix.endswith(os.sep):
        path = path.parent

    def options():
        for sub in path.iterdir():
            if sub.is_dir():
                if (sub / "config.py").is_file():
                    yield str(sub)
                yield str(sub) + "/"

    return list(options())


g.add_argument(
    "-d",
    "--dir",
    type=Path,
    dest="local_dir",
    action="append",
    required=True,
    help="""
Specify the local directory for a course.
This option may be specified multiple times with different values.
---
Needs to contain a Python file config.py specifying the course configuration.
This module will be imported by this program.
See gitlab_config.py.template for documentation of the configuration namespace.
---
This directory is where course-related data is stored and managed.
For example, each lab has a the local repository staging
the collection repository on GitLab Chalmers.
""",
).completer = complete_local_dir

g = p.add_argument_group(title="webhooks")

g.add_argument(
    "--disable-webhooks",
    action="store_true",
    dest="disable_webhooks",
    help="When running the event loop, do not configuration and use webhooks.",
)

local_port_default = 4200

g.add_argument(
    "-p",
    "--port",
    type=int,
    default=local_port_default,
    dest="port",
    help=f"""
The local port to listen at for webhook notifications from Chalmers GitLab.
Defaults to {local_port_default}.
""",
).completer = complete_nothing

g.add_argument(
    "-n",
    "--netloc",
    type=str,
    metavar="NETLOC",
    help="""
Network location in format to specify for setting up webhooks on Chalmers GitLab.
The format is <hostname>:<port> where the part :<port> may be omitted.
The hostname defaults to the local interface routing to Chalmers GitLab.
The port defaults to the value for --port.
---
This option is useful if you are behind network address translation (NAT).
In that case, you can specify a public network location on some server you have access to and use SSH port forwarding to forward connections to the specified network location to the computer running this program.
For example, you may specify `--netloc <public address>:<public port>` and run `ssh -R *:<public port>:localhost:4200 <user>@<public address>`.
---
This option is also useful if you have a dynamic IP that changes frequently and no fixed domain name that resolves to it.
In that case, you may want to follow a procedure as outlined above for the case of NAT to avoid frequent changes in webhook configuration.
---
Changes to the webhook network location are expensive.
On program start up, the configuration of each individual project needs to be updated.
(Group-level webhooks are only provided in the paid versions of GitLab.)
This is 1–3 API calls per project.
By default, a limit of 3600 API calls per hour is imposed.
""",
).completer = complete_nothing  # noqa: E501

g = p.add_argument_group(title="Canvas sync")

g.add_argument(
    "-s",
    "--sync-from-canvas",
    action="append",
    default=[],
    metavar="LAB_ID",
    dest="sync_from_canvas",
    help="""
Specify a lab id for which project membership should be synced from Canvas.
Only has an effect with --start-with-sync and/or --sync-period.
""",
).completer = complete_nothing

g.add_argument(
    "--start-with-sync",
    action="store_true",
    dest="start_with_sync",
    help="""
Synchronize user information from Canvas at the start of the event loop.
Teachers and teaching assistants on Canvas will be added or invited the course grader group.
Students will be added or invited to the lab(s) specified by --sync-from-canvas.
""",
).completer = complete_nothing

g.add_argument(
    "--sync-period",
    type=int,
    metavar="SECONDS",
    dest="sync_period",
    help="""
Synchronize user information from Canvas after every interval of this many seconds.
Teachers and teaching assistants on Canvas will be added or invited the course grader group.
Students will be added or invited to the lab(s) specified by --sync-from-canvas.
""",
).completer = complete_nothing

g = p.add_argument_group(title="other options")

g.add_argument(
    "-j",
    "--jobs",
    type=int,
    default=5,
    dest="jobs",
    help="""
Maximum number of parallel jobs to use for git fetches and pushes.
Defaults to 5, which currently (2021-12) seems to be the value of MaxSessions configured for sshd at Chalmers GitLab.
""",
).completer = complete_nothing

g.add_argument(
    "-r",
    "--run-time",
    type=float,
    dest="run_time",
    help="""
Run-time limit of the event loop in hours.
After this period elapses, the event loop terminates and the program exit.
By default, there is no run-time limit.
""",
).completer = complete_nothing

g = p.add_argument_group(title="help and debugging")
g.add_argument(
    "-e",
    "--error-spreadsheet",
    type=str,
    dest="error_spreadsheet",
    help="""
The ID of an optional Google spreadsheet to use for dumping error reports on run failure.
The sheet ID (gid) is assumed 0 for now (by default, this refers to the first sheet).

to be notified on run failure, configure change notifications in this spreadsheet:
* go to https://docs.google.com/spreadsheets/d/<ERROR_SPREADSHEET>,
* click on "tools", then on "notification rules",
* configure notifications (whenever changes are made, right away).
""",
)
g.add_argument(
    "-l",
    "--log-file",
    type=Path,
    dest="log_file",
    help="""
An optional log file to append debug level logging to.
This is in addition to the the logging printed to standard error by the --verbose option.
If this is an existing directory, it will be used for rotating log files.
""",
)
g.add_argument(
    "-h",
    "--help",
    action="help",
    help="""
Show this help message and exit.
""",
)
g.add_argument(
    "-v",
    "--verbose",
    action="count",
    default=0,
    help="""
Print INFO level (once specified) or DEBUG level (twice specified) logging on standard error.
""",
)


# Support for argcomplete.
try:
    argcomplete.autocomplete(p)
except ModuleNotFoundError:
    pass

args = p.parse_args()


# Argument parsing is done: expensive initialization can start now.
import contextlib
import datetime
import importlib
import logging
import logging.handlers
import threading

import more_itertools

import course
import event_loop
import general
import ip_tools
import print_parse


# Configure logging.
def handlers():
    stderr_handler = logging.StreamHandler()
    args.verbose = min(args.verbose, 2)
    stderr_handler.setLevel(
        {
            0: logging.WARNING,
            1: logging.INFO,
            2: logging.DEBUG,
        }[min(args.verbose, 2)]
    )
    yield stderr_handler
    if args.log_file:
        if args.log_file.is_dir():
            yield logging.handlers.RotatingFileHandler(
                args.log_file / "log", maxBytes=1024 * 1024 * 64, backupCount=10
            )
        else:
            yield logging.FileHandler(args.log_file)


logging.basicConfig(
    format="%(asctime)s %(levelname)s %(module)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=handlers(),
    level=logging.NOTSET,
)

logger = logging.getLogger(__name__)


# Build course instances.
def courses():
    for dir in args.local_dir:
        spec = importlib.util.spec_from_file_location(
            f"config: {str(dir)}", dir / "config.py"
        )
        config = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(config)
        c = course.Course(config, dir)
        yield (dir, c)


courses = general.sdict(courses())
course = list(courses.values())[0]


def get_value_from_courses(name, selector):
    values = set(map(selector, courses.values()))
    try:
        (value,) = values
    except ValueError:
        raise ValueError(f"conflicting configurations of {name} in courses: {values}")
    return value


# Parse webhook configuration.
if args.disable_webhooks:
    webhook_config = None
    logger.debug("Webhooks are disabled.")
else:
    gitlab_netloc = get_value_from_courses(
        "GitLab network location",
        lambda c: c.gitlab_netloc,
    )
    netloc_listen = print_parse.NetLoc(
        host=ip_tools.get_local_ip_routing_to(gitlab_netloc),
        port=args.port,
    )
    netloc_specify = (
        netloc_listen if args.netloc is None else print_parse.netloc.parse(args.netloc)
    )
    if netloc_specify is None:
        netloc_specify = netloc_specify._replace(port=netloc_listen.port)
    webhook_config = event_loop.WebhookConfig(
        netloc_listen=netloc_listen,
        netloc_specify=netloc_specify,
        secret_token=get_value_from_courses(
            "webhook.secret_token",
            lambda c: c.config.webhook.secret_token,
        ),
    )
    logger.debug(f"Webhook config: {webhook_config}")

# Parse Canvas sync configuration.
if not args.start_with_sync and args.sync_period is None:
    canvas_sync_config = None
else:
    # We assume all courses share the same labs.
    # TODO: if we want to continue supporting multiple courses in this script, find way of passing lab-specific config.
    canvas_sync_config = event_loop.CanvasSyncConfig(
        labs_to_sync=tuple(map(course.config.lab.id.parse, args.sync_from_canvas)),
        sync_interval=(
            None
            if args.sync_period is None
            else datetime.timedelta(seconds=args.sync_period)
        ),
        start_with_sync=bool(args.start_with_sync),
    )


def create_webhooks():
    for c in courses.values():
        c.hooks_create(netloc=webhook_config.netloc_specify)


def delete_webhooks():
    for c in courses.values():
        c.hooks_delete_all(netloc=webhook_config.netloc_specify)


def run():
    exit_stack = contextlib.ExitStack()
    if args.error_spreadsheet:
        c = next(iter(courses.values()))
        exit_stack.enter_context(c.error_reporter(args.error_spreadsheet))

    with exit_stack:
        event_loop.run(
            courses=courses.values(),
            run_time=general.with_default(
                lambda x: datetime.timedelta(hours=x), args.run_time
            ),
            webhook_config=webhook_config,
            canvas_sync_config=canvas_sync_config,
        )


# Perform selected action.
{
    "create_webhooks": create_webhooks,
    "delete_webhooks": delete_webhooks,
    "run": run,
}[args.action]()
