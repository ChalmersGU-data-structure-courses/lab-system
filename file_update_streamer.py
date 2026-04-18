#!/usr/bin/env python3
"""Server-sent events streamer for updated files."""

import abc
import argparse
import contextlib
import http.server
import io
import logging
import select
import socket
import socketserver
import sys
import tomllib
from collections.abc import Generator
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path, PurePosixPath

import watchdog.observers
from watchdog.events import FileClosedEvent, FileMovedEvent

import util.http
import util.openssl
import util.path
import util.print_parse
import util.url


@contextlib.contextmanager
def socket_timeout(s: socket.socket, timeout: float | None):
    saved = s.gettimeout()
    s.settimeout(timeout)
    try:
        yield
    finally:
        s.settimeout(saved)


@contextlib.contextmanager
def socket_blocking(s: socket.socket, blocking: bool):
    yield from socket_timeout(s, None if blocking else 0)


def socket_remote(s: socket.socket) -> util.url.NetLoc:
    return util.url.NetLoc(*s.getpeername())


class ContentHandler(abc.ABC):
    @abc.abstractmethod
    def handle(self, content: str) -> None: ...


@contextlib.contextmanager
def watch_file(
    path: Path,
    handler: ContentHandler,
    trigger_initial: bool = False,
) -> None:
    def handle():
        handler.handle(path.read_text())

    class FileEventHandler(watchdog.events.FileSystemEventHandler):
        def match(self, e) -> bool:
            def conditions():
                yield isinstance(e, FileClosedEvent) and Path(e.src_path) == path
                yield isinstance(e, FileMovedEvent) and Path(e.dest_path) == path

            return any(conditions())

        def on_any_event(self, event):
            if self.match(event):
                handle()

    if trigger_initial:
        handle()

    observer = watchdog.observers.Observer()
    observer.schedule(FileEventHandler(), path.parent)
    observer.start()
    try:
        yield
    finally:
        observer.stop()
        observer.join()


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


class Handler(http.server.BaseHTTPRequestHandler):
    wbufsize = 65536

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

    def handle(self):
        self.connection.settimeout(15)
        self.connection.do_handshake()
        super().handle()

    def do_GET(self):
        self.debug("open connection")

        url: util.url.URL = util.url.url_formatter.parse(self.path)
        if not util.path.is_normal(url.path):
            self.warning(f"malformed path {self.path}")
            self.send_error(400, "path malformed")
            return

        path = PurePosixPath(url.path)
        initial = "initial" in url.query
        try:
            password = url.query["password"][0]
        except LookupError:
            password = None

        self.info(f"path {path}, initial {initial}, password {password}")

        result = self.server.path_matcher.match(url.path)
        self.debug(f"match result {result}")

        if result is None:
            self.warning("forbidden")
            self.send_error(403, "forbidden")
            return

        if result.password is not None and not password == result.password:
            self.warning("incorrect password")
            self.send_error(403, "forbidden")
            return

        self.connection.settimeout(None)

        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        @dataclass
        class EchoHandler(ContentHandler):
            wfile: io.BufferedIOBase

            def handle(self, content):
                for line in content.splitlines():
                    self.wfile.write(b"data: ")
                    self.wfile.write(line.encode())
                    self.wfile.write(b"\n")
                self.wfile.write(b"\n")
                self.wfile.flush()

        with watch_file(result.path, EchoHandler(self.wfile), trigger_initial=initial):
            while True:
                timeout = self.server.heartbeat
                xs, _, _ = select.select([self.connection], [], [], timeout)
                if xs:
                    break

                self.wfile.write(b":heartbeat\n")
                self.wfile.flush()

        self.debug("close connection")
        self.connection.close()


class Server(util.http.HTTPSServer, socketserver.ThreadingMixIn):
    def __init__(
        self,
        netloc: util.url.Netloc,
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
        * initial: if set, serve initial file content.  
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
                    args.log_file / "log",
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

    bind = util.url.netloc_formatter.parse(args.bind)

    matcher = PathMatcherTOML(args.matcher)
    assert args.heartbeat is None or args.heartbeat >= 1

    dir_cert = args.cert
    if args.cert_letsencrypt:
        dir_cert = util.openssl.detect_cert_dir_lets_encrypt()

    logger.debug(f"Path matcher: {matcher}")
    logger.debug(f"Bind address: {bind}.")
    logger.debug(f"Certificate directory {dir_cert}.")
    logger.debug(f"Heartbeat period (in seconds): {args.heartbeat}")

    with Server(bind, matcher, dir_cert=dir_cert, heartbeat=args.heartbeat) as server:
        server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(cli())
