# Recommended to import qualified.
import ast
import base64
import collections
import dataclasses
import datetime as module_datetime
import functools
import itertools
import json as module_json
import pathlib
import re
import shlex
from typing import Any, Callable, ClassVar, Protocol
from collections.abc import Iterable, Sequence

import util.general
import util.path
from util.path import PurePosixPath
from util.escaping_formatter import regex_escaping_formatter


class PrinterParser[I, O](Protocol):
    """
    A protocol for printer-parsers.
    These approximate isomorphisms.
    Some input domain is encoded (printed) to some output domain.
    Reversely, the output domain is decoded (parsed) to the input domain.
    Here, the input and output domains may be documented subsets of I and O, respectively.

    Ideally, this satisfies the following invariants:
    * `parse(print(x)) = x` for `x` in the input domain,
    * `print(parse(y)) = y` for `y` in the output domain.

    The first of these invariants is the more important one.
    The second is sometimes not be satisfied.
    There may then be several ways of representing an element of the input domain in the output domain.
    For example, this happens with case-insensitive parsing.

    In applications, the output type is often bigger than the output domain.
    For example, the output type is often str.
    In such cases, parse is a partial function that may raise an exception.
    We currently do not have a designated exception type for that.
    """

    def print(self, _: I, /) -> O:
        """
        Print (encode) from the input domain to the output domain.
        """

    def parse(self, _: O, /) -> I:
        """
        Parse (decode) from the output domain to the input domain.
        """


@dataclasses.dataclass
class Debug[I, O](PrinterParser[I, O]):
    name: str
    pp: PrinterParser[I, O]

    def print(self, x: I, /) -> O:
        print(f"{self.name} printing {x}")
        return self.pp.print(x)

    def parse(self, y: O, /) -> I:
        print(f"{self.name} parsing {y}")
        return self.pp.parse(y)


PrintParse = collections.namedtuple("PrintParse", ["print", "parse"])


class Composition(PrinterParser):
    """
    The composition an iterable of printer parsers.
    Composes the printers in forward order and the parsers in reverse order.
    """

    # type: ignore
    def __init__(self, *pps: PrinterParser):
        self.pps = pps
        self.print = compose(*(pp.print for pp in self.pps))  # type: ignore
        self.parse = compose(*(pp.parse for pp in reversed(self.pps)))  # type: ignore


class Inverse(PrinterParser):
    """The inverse of a printer-parser."""

    def __init__(self, pp: PrinterParser):
        self.print = pp.parse  # type: ignore
        self.parse = pp.print  # type: ignore


identity = PrintParse(
    print=util.general.identity,
    parse=util.general.identity,
)


def compose(*xs) -> PrinterParser:
    """
    Compose an iterable of printer-parsers.
    Composes the printers in forward order and the parsers in reverse order.
    """
    xs = tuple(xs)
    return PrintParse(
        print=util.general.compose(*(x.print for x in xs)),
        parse=util.general.compose(*(x.parse for x in reversed(xs))),
    )


def invert[I, O](pp: PrinterParser[I, O]) -> PrinterParser[O, I]:
    """
    Invert a printer-parsers.
    Exchanges the print and parse functions.
    """
    return PrintParse(
        print=pp.parse,
        parse=pp.print,
    )


swap = PrintParse(
    print=util.general.swap,
    parse=util.general.swap,
)

interchange = PrintParse(
    print=util.general.interchange,
    parse=util.general.interchange,
)

singleton = PrintParse(
    print=util.general.singleton,
    parse=util.general.from_singleton,
)

reversal = PrintParse(
    print=lambda xs: tuple(reversed(xs)),
    parse=lambda xs: tuple(reversed(xs)),
)


def on_print[T](print_: Callable[[T], T]) -> PrinterParser[T, T]:
    return PrintParse(
        print=print_,
        parse=util.general.identity,
    )


def on_parse[T](parse: Callable[[T], T]) -> PrinterParser[T, T]:
    return PrintParse(
        print=util.general.identity,
        parse=parse,
    )


def on_parse_normalize[X, Y](
    values: Iterable[X],
    key: Callable[[X], Y],
    debug: bool = True,
) -> PrinterParser[X, X]:
    """See util.general.Normalizer."""
    return on_parse(util.general.Normalizer(values, key, debug))


@dataclasses.dataclass
class CheckType[X](PrinterParser[X, X]):
    type_: type[X]

    def print(self, x, /):
        return x

    def parse(self, y, /):
        if not isinstance(y, self.type_):
            raise ValueError(f"not of type {self.type_}: {y}")
        return y


class SetAsList[X](PrinterParser[set[X], list[X]]):
    def print(self, xs, /):
        return list(xs)

    def parse(self, xs, /):
        return set(xs)


def on[A, B](
    lens: util.general.Lens[A, B],
    pp: PrinterParser[B, B],
) -> PrinterParser[A, A]:
    return PrintParse(
        print=util.general.on(lens, pp.print),
        parse=util.general.on(lens, pp.parse),
    )


def combine(pps) -> PrinterParser:
    return PrintParse(
        print=util.general.combine(tuple(x.print for x in pps)),
        parse=util.general.combine(tuple(x.parse for x in pps)),
    )


def combine_dict(pps) -> PrinterParser:
    return PrintParse(
        print=util.general.combine_dict({key: x.print for (key, x) in pps.items()}),
        parse=util.general.combine_dict({key: x.parse for (key, x) in pps.items()}),
    )


def combine_namedtuple(pps) -> PrinterParser:
    return PrintParse(
        print=util.general.combine_namedtuple(
            pps.__class__._make(x.print for x in pps)
        ),
        parse=util.general.combine_namedtuple(
            pps.__class__._make(x.parse for x in pps)
        ),
    )


def combine_generic(fs) -> PrinterParser:
    if isinstance(fs, (list, tuple)):
        r = combine
    elif isinstance(fs, dict):
        r = combine_dict
    elif hasattr(fs.__class__, "_make"):
        r = combine_namedtuple
    else:
        raise ValueError(f"no combine instance for {type(fs)}")
    return r(fs)


def over_list[I, O](pp: PrinterParser[I, O]) -> PrinterParser[list[I], list[O]]:
    return PrintParse(
        print=lambda vs: [pp.print(v) for v in vs],
        parse=lambda vs: [pp.parse(v) for v in vs],
    )


def over_tuple(pp: PrinterParser) -> PrinterParser[tuple, tuple]:
    return PrintParse(
        print=lambda vs: tuple(pp.print(v) for v in vs),
        parse=lambda vs: tuple(pp.parse(v) for v in vs),
    )


def over_dict[K, VI, VO](
    pp: PrinterParser[VI, VO],
) -> PrinterParser[dict[K, VI], dict[K, VO]]:
    return PrintParse(
        print=lambda vs: {key: pp.print(v) for (key, v) in vs.items()},
        parse=lambda vs: {key: pp.parse(v) for (key, v) in vs.items()},
    )


def maybe[I, O](pp: PrinterParser[I, O]) -> PrinterParser[I | None, O | None]:
    return PrintParse(
        print=util.general.maybe(pp.print),
        parse=util.general.maybe(pp.parse),
    )


def with_special_case[I, O](
    pp: PrinterParser[I, O],
    value: I,
    value_printed: O,
) -> PrinterParser[I, O]:
    return PrintParse(
        print=util.general.with_special_case(pp.print, value, value_printed),
        parse=util.general.with_special_case(pp.parse, value_printed, value),
    )


def with_none[I, O](
    pp: PrinterParser[I, O],
    none_printed: O,
) -> PrinterParser[I | None, O]:
    return with_special_case(pp, None, none_printed)  # type: ignore


def without[I, O](pp: PrinterParser[I, O], value: I) -> PrinterParser[I, O]:
    return compose(on_print(util.general.check_return(lambda x: x != value)), pp)


quote: PrinterParser[str, str]
quote = PrintParse(
    print=lambda s: ast.unparse(ast.Constant(s)),
    parse=ast.literal_eval,
)

doublequote: PrinterParser[str, str]
doublequote = PrintParse(
    print=util.general.doublequote,
    parse=ast.literal_eval,
)


def escape(chars: Iterable[str]) -> PrinterParser[str, str]:
    # pylint: disable-next=redefined-builtin
    def print(s):
        for c in itertools.chain(["\\"], chars):
            s = s.replace(c, "\\" + c)
        return s

    def parse_helper(it):
        while True:
            try:
                c = next(it)
            except StopIteration:
                return

            if c == "\\":
                # pylint: disable-next=R1708
                yield next(it)
            else:
                yield c

    def parse(s):
        return "".join(parse_helper(iter(s)))

    return PrintParse(
        print=print,
        parse=parse,
    )


escape_parens: PrinterParser[str, str]
escape_parens = escape(["(", ")"])

escape_brackets: PrinterParser[str, str]
escape_brackets = escape(["[", "]"])

string_letters: PrinterParser[str, Iterable[str]]
string_letters = PrintParse(
    print=util.general.identity,
    parse="".join,
)


def int_str(format="") -> PrinterParser[int, str]:
    format_str = f"{{:{format}d}}"
    return PrintParse(
        print=format_str.format,
        parse=int,
    )


class RegexParser:
    def __init__(
        self,
        # pylint: disable-next=redefined-outer-name
        regex: str,
        **kwargs,
    ):
        self.pattern = re.compile(regex, **kwargs)

    def __call__(self, s: str) -> re.Match:
        m = self.pattern.fullmatch(s)
        if not m:
            raise ValueError(f"does not match {self.pattern.pattern}: {s}")
        return m


def regex_non_canonical(
    holed_string: str,
    # pylint: disable-next=redefined-outer-name
    regex: str,
    **kwargs,
) -> PrinterParser[str, str]:
    return compose(
        singleton,
        RegexNoncanonicalMany(holed_string, regex, **kwargs),
    )


@dataclasses.dataclass
class RegexNoncanonicalMany(PrinterParser[Sequence[str], str]):
    holed_string: str
    regex_parser: RegexParser

    def __init__(
        self,
        holed_string: str,
        # pylint: disable-next=redefined-outer-name
        regex: str,
        **kwargs,
    ):
        self.holed_string = holed_string
        self.regex_parser = RegexParser(regex, **kwargs)

    def print(self, args: Sequence[str], /) -> str:
        return self.holed_string.format(*args)

    def parse(self, s: str, /) -> Sequence[str]:
        return self.regex_parser(s).groups()


@dataclasses.dataclass
class RegexNoncanonicalKeyed(PrinterParser[dict[str, str], str]):
    holed_string: str
    regex_parser: RegexParser

    def __init__(
        self,
        holed_string: str,
        # pylint: disable-next=redefined-outer-name
        regex: str,
        **kwargs,
    ):
        self.holed_string = holed_string
        self.regex_parser = RegexParser(regex, **kwargs)

    def print(self, args: dict[str, str], /) -> str:
        return self.holed_string.format(**args)

    def parse(self, s: str, /) -> dict[str, str]:
        return self.regex_parser(s).groupdict()


# pylint: disable-next=redefined-outer-name
def regex(holed_string: str, regex: str = ".*", **kwargs) -> PrinterParser[str, str]:
    """
    BUG.
    This and following functions only work under the following assumption.
    The holed_string argument must not contain regex special characters (except for holes).
    """
    return regex_non_canonical(
        holed_string,
        regex_escaping_formatter.format(holed_string, f"({regex})"),
        **kwargs,
    )


# Sidestep limitations of shadowing in Python.
_regex = regex


def regex_many(
    holed_string: str,
    regexes: Iterable[str],
    **kwargs,
) -> PrinterParser[Sequence[str], str]:
    return RegexNoncanonicalMany(
        holed_string,
        regex_escaping_formatter.format(
            holed_string, *(f"({regex})" for regex in regexes)
        ),
        **kwargs,
    )


def regex_keyed(
    regexes_keyed: dict[str, str],
    holed_string: str,
    **kwargs,
) -> PrinterParser[dict[str, str], str]:
    return RegexNoncanonicalKeyed(
        holed_string,
        regex_escaping_formatter.format(
            holed_string,
            **{key: f"(?P<{key}>{regex})" for (key, regex) in regexes_keyed.items()},
        ),
        **kwargs,
    )


def regex_int(
    holed_string: str,
    format: str = "",
    # pylint: disable-next=redefined-outer-name
    regex: str = "\\d+",
    **kwargs,
) -> PrinterParser[int, str]:
    """Takes a format string with a single hole."""
    return compose(
        int_str(format=format),
        _regex(holed_string, regex=regex, **kwargs),
    )


qualify_with_slash: PrinterParser[tuple[str, str], str]
qualify_with_slash = regex_many("{}/{}", ["[^/]*", ".*"])  # type: ignore

parens: PrinterParser[str, str]
parens = regex_non_canonical("({})", r"\((.*)\)")

bracks: PrinterParser[str, str]
bracks = regex_non_canonical("[{}]", r"\[(.*)\]")

braces: PrinterParser[str, str]
braces = regex_non_canonical("{{{}}}", r"\{(.*)\}")


@dataclasses.dataclass
class Join(PrinterParser[list[str], str]):
    sep: str | None = None
    maxsplit: int = -1

    def print(self, x: Iterable[str], /) -> str:
        _sep = " " if self.sep is None else self.sep
        return _sep.join(x)

    def parse(self, y: str, /) -> list[str]:
        return y.split(self.sep, self.maxsplit)


@dataclasses.dataclass
class JoinBytes(PrinterParser[list[bytes], bytes]):
    sep: bytes | None = None
    maxsplit: int = -1

    def print(self, x: Iterable[bytes], /) -> bytes:
        _sep = b" " if self.sep is None else self.sep
        return _sep.join(x)

    def parse(self, y: bytes, /) -> list[bytes]:
        return y.split(self.sep, self.maxsplit)


class Dict[I, O](PrinterParser[I, O]):
    """
    Printer-parser based on a dictionary of (value, printed) pairs.
    The default semantics is strict, assuming that values and printings are unique.
    If duplicates are allowed, use print_strict = False or parse_strict = False, respectively.
    """

    def __init__(
        self,
        xs: Iterable[tuple[I, O]],
        print_strict: bool = True,
        parse_strict: bool = True,
        print_debug: bool = True,
        parse_debug: bool = True,
    ):
        xs = tuple(xs)
        self.u = util.general.sdict(((x, y) for (x, y) in xs), strict=print_strict)
        self.v = util.general.sdict(((y, x) for (x, y) in xs), strict=parse_strict)
        self.print_debug = print_debug
        self.parse_debug = parse_debug

    def print(self, x: I, /) -> O:
        return util.general.mapping_lookup(self.u, x, debug=self.print_debug)

    def parse(self, y: O, /) -> I:
        return util.general.mapping_lookup(self.v, y, debug=self.parse_debug)


@dataclasses.dataclass
class Add(PrinterParser[int, int]):
    increment: int

    def print(self, x: int, /) -> int:
        return x + self.increment

    def parse(self, y: int, /) -> int:
        return y - self.increment


from_one: PrinterParser[int, int]
from_one = Add(1)


@dataclasses.dataclass
class SkipNatural(PrinterParser[int, int]):
    n: int

    def print(self, x: int, /) -> int:
        return x if x < self.n else x + 1

    def parse(self, y: int, /) -> int:
        if y == self.n:
            raise ValueError(f"value {y} is forbidden")
        return y if y < self.n else y - 1


def _singleton_range_parse(range_):
    if not util.general.is_range_singleton(range_):
        raise ValueError(f"not a singleton range: {range_}")

    return range_


singleton_range: PrinterParser[int, util.general.Range]
singleton_range = PrintParse(
    print=util.general.range_singleton,
    parse=_singleton_range_parse,
)


pure_posix_path: PrinterParser[PurePosixPath, str]
pure_posix_path = PrintParse(
    print=str,
    parse=PurePosixPath,
)

pure_path: PrinterParser[pathlib.PurePath, str]
pure_path = PrintParse(
    print=str,
    parse=pathlib.PurePath,
)

posix_path: PrinterParser[pathlib.PosixPath, str]
posix_path = PrintParse(
    print=str,
    parse=pathlib.PosixPath,
)

path: PrinterParser[pathlib.Path, str]
path = PrintParse(
    print=str,
    parse=pathlib.Path,
)

search_path: PrinterParser[Iterable[str], str]
search_path = PrintParse(
    print=util.path.search_path_join,
    parse=util.path.search_path_split,
)

command_line: PrinterParser[Iterable[str], str]
command_line = PrintParse(
    print=shlex.join,
    parse=shlex.split,
)

string_coding: PrinterParser[str, bytes]
string_coding = PrintParse(
    str.encode,
    bytes.decode,
)


class ASCII(PrinterParser[str, bytes]):
    def print(self, s: str, /) -> bytes:
        return s.encode("ascii")

    def parse(self, x: bytes, /) -> str:
        return x.decode("ascii")


# pylint: disable-next=redefined-builtin
ascii: PrinterParser[str, bytes]
ascii = ASCII()


def base64_pad(x: bytes) -> bytes:
    k = -len(x) % 4
    if k != 0:
        x += b"=" * k
    return x


base64_standard: PrinterParser[bytes, bytes]
base64_standard = PrintParse(
    print=base64.standard_b64encode,
    parse=util.general.compose(base64_pad, base64.standard_b64decode),
)

base64_standard_str: PrinterParser[str, bytes]
base64_standard_str = compose(ascii, base64_standard, invert(ascii))


def datetime(format: str) -> PrinterParser[module_datetime.datetime, str]:
    return PrintParse(
        print=lambda x: module_datetime.datetime.strftime(x, format),
        parse=lambda x: module_datetime.datetime.strptime(x, format),
    )


def json_coding(**kwargs) -> PrinterParser[Any, str]:
    return PrintParse(
        print=functools.partial(module_json.dumps, **kwargs),
        parse=module_json.loads,
    )


json_coding_nice: PrinterParser[Any, str]
json_coding_nice = json_coding(indent=4, sort_keys=True)

# TODO: change name
json: PrinterParser[Any, str]
json = json_coding()


class Dataclass(Protocol):
    """
    Protocol for dataclasses.
    """

    __dataclass_fields__: ClassVar[dict[str, Any]]


def dataclass_dict[T: Dataclass](cls: type[T]) -> type[T]:
    fields = cls.__dataclass_fields__

    def pp_field(field):
        # Don't use exceptions because this may lie on the critical path.
        default = CheckType(field.type)
        if field.metadata is None:
            return default
        return field.metadata.get("pp", default)

    # pylint: disable-next=redefined-builtin
    def print(x):
        return {
            name: pp_field(field).print(getattr(x, name))
            for (name, field) in fields.items()
        }

    def parse(u):
        return cls(
            **{name: pp_field(field).parse(u[name]) for (name, field) in fields.items()}
        )

    cls.pp_dict = PrintParse(print=print, parse=parse)  # type: ignore
    return cls


def dataclass_json[T: Dataclass](
    cls: type[T],
    nice: bool = False,
) -> type[T]:
    dataclass_dict(cls)
    cls.pp_json = compose(cls.pp_dict, json_coding_nice if nice else json)  # type: ignore
    return cls


def dataclass_field(pp):
    # pylint: disable=invalid-field-call
    return dataclasses.field(metadata={"pp": pp})


def named_tuple_from_dataclass(cls):
    return collections.namedtuple(
        cls.__name__,
        [field.name for field in dataclasses.fields(cls)],
    )


@dataclasses.dataclass
class DataclassAsNamedTuple[S, T](PrinterParser[S, T]):
    cls_source: type[S]
    cls_target: type[T]

    def print(self, x: S, /) -> T:
        return self.cls_target(**x.__dict__)

    def parse(self, y: T, /) -> S:
        return self.cls_source(**y._asdict())


class StringAsPathSegment(PrinterParser):
    def print(self, x, /):
        return x.replace("%", "%%").replace("/", "%s")

    def parse(self, y, /):
        return y.replace("%s", "/").replace("%%", "%")
