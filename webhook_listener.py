import contextlib
import http.server
import json
import logging
import ssl
import threading
import traceback
from pathlib import PurePosixPath

import openssl_tools
import path_tools
import print_parse

logger = logging.getLogger(__name__)


class Handler(http.server.BaseHTTPRequestHandler):
    def handle(self):
        self.connection.settimeout(15)
        super().handle()

    def send_response(self, code, message=None):
        logger.info(
            f"send_response: start, code {code}, message {message}, thread {threading.get_ident()}"
        )
        logger.info(traceback.print_stack())
        super().send_response(code, message=message)
        logger.info("send_response: end")

    def do_POST(self):
        logger.info("do_POST: start")

        token = self.headers.get("X-Gitlab-Token")
        if token != self.server.secret_token:
            self.server.logger.warning(
                f"Given secret token {token} does not match "
                f"stored secret token {self.server.secret_token}. "
                "Ignoring request."
            )
            self.send_error(403)
            return

        # Read data and conclude request.
        data_raw = self.rfile.read(int(self.headers["Content-Length"]))
        self.send_response(200)
        self.end_headers()

        # Parse data and call callback.
        info = json.loads(data_raw)
        self.server.logger.debug("received hook callback with data:\n" + str(info))
        self.server.callback(info)

        logger.info("do_POST: end")


@contextlib.contextmanager
def server_manager(netloc, secret_token, callback, logger=logger):
    """
    Context manager for an HTTP server that processes webhook notifications from GitLab.
    Only notifications with the correct secret token are considered.

    Arguments:
    * netloc:
        Local network location to bind to.
        Only the host and port fields are used.
    * secret_token:
        Secret token to check for incoming webhook notifications.
        Only notifications with the correct secret token are processed.
    * callback:
        Function to call for incoming webhook notifications
        with the correct secret token.
        The argumented passed is the JSON-decoded body of the notification.
    * logger:
        Logger to use in the handler.

    This method does not return.
    """
    netloc = print_parse.netloc_normalize(netloc)
    address = (netloc.host, netloc.port)

    with path_tools.temp_dir() as dir:
        # Generate an SSL certificate.
        # This is needed for GitLab to connect to our webhook listener.
        # (Only HTTPS listener addresses are allowed, not HTTP.).
        file_cert = dir / "cert.pem"
        file_key = dir / "key.pem"
        openssl_tools.generate_cert(file_cert, file_key)

        # Create the server.
        with http.server.HTTPServer(address, Handler) as server:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(file_cert, file_key)
            server.socket = context.wrap_socket(
                server.socket,
                server_side=True,
            )

            # Set the server attributes used by the handler.
            server.secret_token = secret_token
            server.callback = callback
            server.logger = logger

            yield server


class ParsingError(Exception):
    def __init__(self, msg, event):
        self.msg = msg
        self.event = event

    def __str__(self):
        return f"{self.msg}\nevent: {self.event}"


@contextlib.contextmanager
def parsing_error_manager(event):
    try:
        yield
    except Exception as e:
        raise ParsingError(msg=str(e), event=event) from e


def map_with_callback(f, xs):
    for e, callback in xs:
        yield (f(e), callback)


def parse_hook_event(courses_by_groups_path, hook_event, strict=False):
    """
    Parses an event received from a webhook.

    This function completes fast.
    Further processing that may involve expensive computation or IO
    is deferred to the callback function of the generated events.

    Triggered exceptions are raised as instances of ParsingError.

    We currently only handle events in group projects.
    The parsing in this function reflects that.

    Arguments:
    * courses_by_groups_path:
        Dictionary sending student group namespace paths (instances of
        pathlib.PurePosixPath) on Chalmers GitLab to instances of course.Course.
        For example, a key may look like PurePosixPath('courses/my_course/groups').
    * hook_event:
        Dictionary (decoded JSON).
        Event received from a webhook.
    * strict:
        Whether to fail on unknown events.
        Not all assumptions are currently checked,
        So even with strict set to False,
        we might end up raising an instance of ParsingError.

    Returns an iterable of pairs of:
    - a program event (instance of events.ProgramEvent),
    - a nullary callback function to handle the event.

    if 'strict' is set, raises an exception if
    the event is not one of the types we can handle.

    Uses Course.graders for each supplied course.
    See Course.parse_hook_event for a note on precaching.
    """
    with parsing_error_manager(hook_event):
        # Find the relevant lab and group project.
        project_path = PurePosixPath(hook_event["project"]["path_with_namespace"])
        (project_slug, lab_full_id, *path_groups_parts_rev) = reversed(
            project_path.parts
        )
        path_groups = PurePosixPath(*reversed(path_groups_parts_rev))

        course = courses_by_groups_path.get(path_groups)
        if course:
            yield from map_with_callback(
                course.program_event,
                course.parse_hook_event(
                    hook_event=hook_event,
                    lab_full_id=lab_full_id,
                    project_slug=project_slug,
                    strict=strict,
                ),
            )
        else:
            msg = (
                "unknown course with student"
                "groups path {shlex.quote(str(path_groups))}"
            )
            if strict:
                raise ValueError(msg)

            logger.warning(f"Received webhook event for {msg}")
            logger.debug(f"Webhook event:\n{hook_event}")
