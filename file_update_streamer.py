#!/usr/bin/env python3
"""Server-sent events streamer for updated files."""

import abc
import argparse
import contextlib
import http.server
import logging
import logging.handlers
import select
import socket
import socketserver
import sys
import threading
import tomllib
from collections.abc import Generator
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path, PurePosixPath

import util.http
import util.openssl
import util.path
import util.print_parse
import util.sse
import util.threading
import util.url
import util.watchdog


def socket_remote(s: socket.socket) -> util.url.NetLoc:
    return util.url.NetLoc(*s.getpeername())


def format_exception_short(e: Exception) -> str:
    return f"{type(e).__name__}: {e}"


@dataclass
class PathMatchResult:
    path: Path
    password: str | None


class PathMatcher(abc.ABC):
    @abc.abstractmethod
    def match(self, path: PurePosixPath) -> PathMatchResult | None:
        return None


@dataclass
class PathMatcherTOML(PathMatcher):
    path: Path

    def generator(self) -> Generator[tuple[PurePosixPath, PathMatchResult]]:
        with self.path.open("rb") as file:
            config = tomllib.load(file)
        for entry in config["entry"]:
            path_source = PurePosixPath(entry["source"])
            path_target = Path(entry["target"])
            assert path_source.is_absolute()
            assert util.path.is_normal(path_source)
            result = PathMatchResult(path=path_target, password=entry.get("password"))
            yield (path_source, result)

    @cached_property
    def mapping(self) -> dict[PurePosixPath, PathMatchResult]:
        return util.general.sdict(self.generator())

    def match(self, path):
        return self.mapping.get(path)

    def __post_init__(self):
        # Generate the mapping.
        # pylint: disable-next=pointless-statement
        self.mapping


class Handler(http.server.SimpleHTTPRequestHandler):
    wbufsize = 65536

    result: PathMatcher

    @cached_property
    def log_prefix(self):
        return util.url.netloc_formatter.print(socket_remote(self.connection)) + ": "

    def log(self, level, message):
        self.server.logger.log(level, self.log_prefix + message)

    def debug(self, message):
        return self.log(logging.DEBUG, message)

    def info(self, message):
        return self.log(logging.INFO, message)

    def warning(self, message):
        return self.log(logging.WARNING, message)

    def error(self, message):
        return self.log(logging.ERROR, message)

    @cached_property
    def sse(self) -> util.sse.ServerSideEvents:
        return util.sse.ServerSideEvents(self.wfile)

    @cached_property
    def event_any(self) -> threading.Event:
        return threading.Event()

    def set_event(self, event: threading.Event) -> None:
        event.set()
        self.event_any.set()

    @cached_property
    def event_close_requested(self) -> threading.Event:
        return threading.Event()

    @cached_property
    def event_heartbeat_requested(self) -> threading.Event:
        return threading.Event()

    @cached_property
    def event_file_changed(self) -> threading.Event:
        return threading.Event()

    def handle(self):
        self.connection.settimeout(15)
        self.connection.do_handshake()
        super().handle()

    def handle_event(self) -> bool:
        """Returns True if termination is desired."""
        if self.event_close_requested.is_set():
            return True

        if self.event_heartbeat_requested.is_set():
            self.debug("write heartbeat")
            self.event_heartbeat_requested.clear()
            self.sse.write_heartbeat()

        if self.event_file_changed.is_set():
            self.debug("file changed")
            self.event_file_changed.clear()
            try:
                data = self.result.path.read_bytes()
            except OSError as e:
                error_msg = format_exception_short(e)
                self.error(error_msg)
                self.sse.write_message(b"error", error_msg.encode())
                self.set_event(self.event_close_requested)
            else:
                self.sse.write_message(b"update", data)

        return False

    def event_loop(self):
        while True:
            self.debug("waiting")
            self.event_any.wait()
            self.event_any.clear()
            if self.handle_event():
                return

    def translate_path(self, path):
        """Overrides function of SimpleHTTPRequestHandler."""
        return str(self.result.path)

    def do_GET(self):
        self.debug("open connection")

        try:
            url: util.url.URL = util.url.url_formatter.parse(self.path)
        except ValueError:
            self.warning(f"malformed url {self.path}")
            self.send_error(400, "URL malformed")
            return

        if not util.path.is_normal(url.path):
            self.warning(f"malformed path {self.path}")
            self.send_error(400, "path malformed")
            return

        path = PurePosixPath(url.path)
        fetch = "fetch" in url.query
        initial = "initial" in url.query
        try:
            password = url.query["password"][0]
        except LookupError:
            password = None

        self.info(f"path {path}, fetch {fetch}, initial {initial}, password {password}")

        self.result = self.server.path_matcher.match(url.path)
        self.debug(f"match result {self.result}")

        if self.result is None:
            self.warning("forbidden")
            self.send_error(403, "forbidden")
            return

        if self.result.password is not None and not password == self.result.password:
            self.warning("incorrect password")
            self.send_error(401, "incorrect password")
            return

        if fetch:
            super().do_GET()
            return

        if not self.result.path.parent.is_dir():
            self.warning("parent directory does not exist")
            self.send_error(404, "parent directory does not exist")
            return

        if initial and not self.result.path.is_file():
            self.warning("file does not exist")
            self.send_error(404, "file does not exist")
            return

        self.connection.settimeout(None)

        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.debug("sent headers")

        with contextlib.ExitStack() as stack:
            stop_reading_r, stop_reading_w = util.general.pipe()
            stack.enter_context(stop_reading_r)
            stack.enter_context(stop_reading_w)

            def reader():
                try:
                    while True:
                        self.debug("selecting...")
                        to_read = [self.connection, stop_reading_r]
                        xs, _, _ = select.select(to_read, [], [])
                        if xs:
                            break
                except OSError as e:
                    self.warning(f"read error: {format_exception_short(e)}")

                self.debug("requesting close")
                self.set_event(self.event_close_requested)

            def managers():
                thread = threading.Thread(target=reader)
                yield util.threading.thread_manager(thread)

                if self.server.heartbeat is not None:
                    timer = util.threading.RepeatTimer(
                        self.server.heartbeat,
                        lambda: self.set_event(self.event_heartbeat_requested),
                    )
                    yield util.threading.timer_manager(timer)

                yield util.watchdog.callback_on_file_changed_positive(
                    self.result.path,
                    lambda: self.set_event(self.event_file_changed),
                )

            try:
                for manager in managers():
                    stack.enter_context(manager)
                if initial:
                    self.set_event(self.event_file_changed)
                self.event_loop()
            # pylint: disable-next=broad-exception-caught
            except Exception as e:
                self.error(format_exception_short(e))
                raise
            finally:
                self.debug("close connection")
                self.close_connection = True
                stop_reading_w.close()


class Server(socketserver.ThreadingMixIn, util.http.HTTPSServer):
    daemon_threads = True

    def __init__(
        self,
        netloc: util.url.NetLoc,
        path_matcher: PathMatcher,
        dir_cert: Path | None = None,
        heartbeat: float | None = 60,
        logger=logging.getLogger(__name__),
    ):
        super().__init__(netloc, Handler, dir_cert=dir_cert)
        self.path_matcher = path_matcher
        self.logger = logger
        self.heartbeat = heartbeat
        self.socket.setblocking(True)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="""
        Server-sent events streamer for updated files.
        Binds an HTTPs server to the given address.
        Streams content of files on updates.
        The request path selects the file according to the configured matcher.
        Supported query parameters:
        * password: password if required by the matcher,
        * initial: if set, serve initial file content,
        * fetch: if set, serve file as usual instead of using server-side events.
        """,
    )
    p.add_argument(
        "--matcher",
        type=Path,
        required=True,
        help="""
        TOML file specifying path matching.
        Must contain an array "entry" of tables with the following fields:
        * source: the request path,
        * target: the corresponding file path to watch,
        * password (optional): require this password (as query parameter with key "password").
        """,
    )
    p.add_argument(
        "--bind",
        type=str,
        required=True,
        help="""
        Bind address of the server.
        Examples: localhost:1234, :4321.
        """,
    )
    p.add_argument(
        "--cert",
        type=Path,
        help="""
        Directory with an SSL certificate cert.pem and key file key.pem to use.
        If omitted, a fresh certificate is used for this invocation.
        """,
    )
    p.add_argument(
        "--cert-letsencrypt",
        action="store_true",
        help="""
        Overrides --cert.
        Takes unique certificate from /etc/letsencrypt/.
        """,
    )
    p.add_argument(
        "--heartbeat",
        type=float,
        help="Optional period of heartbeat (in seconds) to send by the server.",
    )
    p.add_argument(
        "--log",
        type=Path,
        help="""
        Optional log file to append debug level logging to.
        This is in addition to the logging printed to standard error by the --verbose option.
        If this is an existing directory, it will be used for rotating log files.
        """,
    )
    p.add_argument(
        "--verbose",
        action="count",
        default=0,
        help="""
        Print INFO level (once specified) or DEBUG level (twice specified) logging on standard error.
        """,
    )
    return p


def cli() -> int:
    p = parser()
    args = p.parse_args()

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
        if args.log:
            if args.log.is_dir():
                yield logging.handlers.RotatingFileHandler(
                    args.log / "log",
                    maxBytes=1024 * 1024 * 8,
                    backupCount=16,
                )
            else:
                yield logging.FileHandler(args.log)

    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(module)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers(),
        level=logging.NOTSET,
    )

    logger = logging.getLogger(__name__)
    logger.debug("started")

    bind = util.url.netloc_formatter.parse(args.bind)

    matcher = PathMatcherTOML(args.matcher)
    assert args.heartbeat is None or args.heartbeat >= 1

    dir_cert = args.cert
    if args.cert_letsencrypt:
        dir_cert = util.openssl.detect_cert_dir_lets_encrypt()

    logger.debug(f"path matcher: {matcher}")
    logger.debug(f"bind address: {bind}")
    logger.debug(f"certificate directory {dir_cert}")
    logger.debug(f"heartbeat period (in seconds): {args.heartbeat}")

    try:
        with Server(
            bind,
            matcher,
            dir_cert=dir_cert,
            heartbeat=args.heartbeat,
        ) as server:
            server.serve_forever()
    finally:
        logger.debug("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(cli())
