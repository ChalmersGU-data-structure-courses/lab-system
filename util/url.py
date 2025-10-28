import functools
import re
import urllib.parse
from dataclasses import dataclass
from pathlib import PurePosixPath
from types import MappingProxyType

import util.print_parse
from util.print_parse import PrinterParser


@dataclass
class URLQuoter(PrinterParser[str, str]):
    safe: str = "/"

    def print(self, url: str, /):
        return urllib.parse.quote(url, safe=self.safe)

    def parse(self, url_quoted: str, /):
        return urllib.parse.unquote(url_quoted)


url_strict_quoter: URLQuoter
url_strict_quoter = URLQuoter(safe="")

url_strict_safe_strict: str
url_strict_safe_strict = "[\\w_\\.\\-\\~]*"


@dataclass
class NetLoc:
    host: str
    port: int | None = None
    user: str | None = None
    password: str | None = None
    """
    A network location.
    Reference: Section 3.1 of RFC 1738
    """

    def __str__(self):
        return netloc_formatter.print(self)


_NetLoc_NamedTuple = util.print_parse.named_tuple_from_dataclass(NetLoc)


class _NetLocRawPP(PrinterParser[_NetLoc_NamedTuple, str]):
    regex_parser: util.print_parse.RegexParser

    def __init__(self):
        parts = [
            f"(?:(?P<user>{url_strict_safe_strict})",
            f"(?::(?P<password>{url_strict_safe_strict}))?@)?",
            f"(?P<host>{url_strict_safe_strict})",
            "(?::(?P<port>\\d+))?",
        ]
        self.regex_parser = util.print_parse.RegexParser(
            str().join(parts),
            flags=re.ASCII,
        )

    def print(self, x: _NetLoc_NamedTuple, /) -> str:
        def parts():
            if x.user is not None:
                yield x.user
                if x.password is not None:
                    yield ":"
                    yield x.password
                yield "@"
            yield x.host
            if x.port is not None:
                yield ":"
                yield str(x.port)

        return str().join(parts())

    def parse(self, y: str, /) -> _NetLoc_NamedTuple:
        return _NetLoc_NamedTuple(**self.regex_parser(y).groupdict())


netloc_formatter: PrinterParser[NetLoc, str]
netloc_formatter = util.print_parse.compose(
    util.print_parse.DataclassAsNamedTuple(NetLoc, _NetLoc_NamedTuple),
    util.print_parse.combine_namedtuple(
        _NetLoc_NamedTuple(
            host=url_strict_quoter,
            port=util.print_parse.maybe(util.print_parse.int_str()),
            user=util.print_parse.maybe(url_strict_quoter),
            password=util.print_parse.maybe(url_strict_quoter),
        )
    ),
    _NetLocRawPP(),
)
"""String representation of network locations."""


Query = dict[str, tuple[str]]
"""Query arguments in a URL."""


class QueryFormatter(PrinterParser[Query, str]):
    def print(self, query: Query, /) -> str:
        return urllib.parse.urlencode(
            query,
            doseq=True,
        )

    def parse(self, query_string: str, /) -> Query:
        return urllib.parse.parse_qs(
            query_string,
            keep_blank_values=True,
            strict_parsing=True,
        )


@dataclass
class URL:
    scheme: str
    netloc: NetLoc
    path: PurePosixPath = PurePosixPath()
    query: Query = MappingProxyType({})
    fragment: str | None = None


_URL_NamedTuple = util.print_parse.named_tuple_from_dataclass(URL)

URL_HTTP = functools.partial(URL, "http")
URL_HTTPS = functools.partial(URL, "https")

url_formatter: PrinterParser[URL, str]
url_formatter = util.print_parse.compose(
    util.print_parse.DataclassAsNamedTuple(URL, _URL_NamedTuple),
    util.print_parse.combine_namedtuple(
        _URL_NamedTuple(
            scheme=util.print_parse.identity,
            netloc=netloc_formatter,
            path=util.print_parse.pure_posix_path,
            query=QueryFormatter(),
            fragment=util.print_parse.identity,
        )
    ),
    util.print_parse.PrintParse(
        print=urllib.parse.urlunsplit,
        parse=urllib.parse.urlsplit,
    ),
)
