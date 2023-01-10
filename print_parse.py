# Should only be imported qualified.
import ast
import base64
import builtins
import collections
import dataclasses
import datetime
import functools
import json
import pathlib
import re
import shlex
import urllib.parse

from escaping_formatter import regex_escaping_formatter
import general
import path_tools

PrintParse = collections.namedtuple('PrintParse', ['print', 'parse'])
PrintParse.__doc__ = 'Approximations to isomorphisms.'


identity = PrintParse(
    print = general.identity,
    parse = general.identity,
)

def compose(*xs):
    xs = builtins.tuple(xs)
    return PrintParse(
        print = general.compose(*(x.print for x in xs)),
        parse = general.compose(*(x.parse for x in reversed(xs))),
    )

def invert(x):
    return PrintParse(
        print = x.parse,
        parse = x.print,
    )

swap = PrintParse(
    print = general.swap,
    parse = general.swap,
)

interchange = PrintParse(
    print = general.interchange,
    parse = general.interchange,
)

singleton = PrintParse(
    print = general.singleton,
    parse = general.from_singleton,
)

#from_singleton = invert(singleton)

reversal = PrintParse(
    print = lambda xs: builtins.tuple(reversed(xs)),
    parse = lambda xs: builtins.tuple(reversed(xs)),
)

def on_print(print):
    return PrintParse(
        print = print,
        parse = general.identity,
    )

def on_parse(parse):
    return PrintParse(
        print = general.identity,
        parse = parse,
    )

lower = on_parse(str.lower)

def on(lens, x):
    return PrintParse(
        print = general.on(lens, x.print),
        parse = general.on(lens, x.parse),
    )

# These functions take collections of printer-parsers.
def combine(xs):
    return PrintParse(
        print = general.combine(builtins.tuple(x.print for x in xs)),
        parse = general.combine(builtins.tuple(x.parse for x in xs)),
    )

def combine_dict(xs):
    return PrintParse(
        print = general.combine_dict(builtins.dict((key, x.print) for (key, x) in xs.items())),
        parse = general.combine_dict(builtins.dict((key, x.parse) for (key, x) in xs.items())),
    )

def combine_namedtuple(xs):
    return PrintParse(
        print = general.combine_namedtuple(xs.__class__._make(x.print for x in xs)),
        parse = general.combine_namedtuple(xs.__class__._make(x.parse for x in xs)),
    )

def combine_generic(fs):
    if isinstance(fs, (builtins.list, builtins.tuple)):
        r = combine
    elif isinstance(fs, builtins.dict):
        r = combine_dict
    elif hasattr(fs.__class__, '_make'):
        r = combine_namedtuple
    return r(fs)

def list(x):
    return PrintParse(
        print = lambda vs: [x.print(v) for v in vs],
        parse = lambda vs: [x.parse(v) for v in vs],
    )

def tuple(x):
    return PrintParse(
        print = lambda vs: builtins.tuple(x.print(v) for v in vs),
        parse = lambda vs: builtins.tuple(x.parse(v) for v in vs),
    )

def dict(x):
    return PrintParse(
        print = lambda vs: {key: x.print(v) for (key, v) in vs.items()},
        parse = lambda vs: {key: x.parse(v) for (key, v) in vs.items()},
    )

def maybe(x):
    return PrintParse(
        print = general.maybe(x.print),
        parse = general.maybe(x.parse),
    )

def with_special_case(x, value, value_printed):
    return PrintParse(
        print = general.with_special_case(x.print, value, value_printed),
        parse = general.with_special_case(x.parse, value_printed, value),
    )

def with_none(x, none_printed):
    return with_special_case(x, None, none_printed)

def without(x, value):
    return compose(on_print(general.check_return(lambda x: x != value)), x)

quote = PrintParse(
    print = lambda s: ast.unparse(ast.Constant(s)),
    parse = ast.literal_eval,
)

doublequote = PrintParse(
    print = general.doublequote,
    parse = ast.literal_eval,
)

string_letters = PrintParse(
    print = general.identity,
    parse = ''.join,
)

def int_str(format = ''):
    format_str = f'{{:{format}d}}'
    return PrintParse(
        print = lambda n: format_str.format(n),
        parse = int,
    )

def regex_parser(regex, keyed = False, **kwargs):
    pattern = re.compile(regex, **kwargs)

    def f(s):
        match = pattern.fullmatch(s)
        if not match:
            raise ValueError('no parse')
        return match.groupdict() if keyed else match.groups()
    return f

def regex_non_canonical(holed_string, regex, **kwargs):
    return compose(
        singleton,
        regex_non_canonical_many(holed_string, regex, **kwargs),
    )

def regex_non_canonical_many(holed_string, regex, **kwargs):
    return PrintParse(
        print = lambda args: holed_string.format(*args),
        parse = regex_parser(regex, **kwargs),
    )

def regex_non_canonical_keyed(holed_string, regex, **kwargs):
    return PrintParse(
        print = lambda args: holed_string.format(**args),
        parse = regex_parser(regex, keyed = True, **kwargs),
    )

# Bug.
# This and following functions only work for holed_string arguments
# that don't contained regex special characters (except for the holes).
def regex(holed_string, regex = '.*', **kwargs):
    return regex_non_canonical(
        holed_string,
        regex_escaping_formatter.format(holed_string, f'({regex})'),
        **kwargs,
    )

# Sidestep limitations of shadowing in Python.
_regex = regex

def regex_many(holed_string, regexes, **kwargs):
    return regex_non_canonical_many(
        holed_string,
        regex_escaping_formatter.format(
            holed_string,
            *(f'({regex})' for regex in regexes)
        ),
        **kwargs,
    )

def regex_keyed(holed_string, regexes_keyed, **kwargs):
    return regex_non_canonical_keyed(
        holed_string,
        regex_escaping_formatter.format(
            holed_string,
            **builtins.dict((key, f'(?P<{key}>{regex})') for (key, regex) in regexes_keyed.items())
        ),
        **kwargs,
    )

# Takes a format string with a single hole.
def regex_int(holed_string, format = '', regex = '\\d+', **kwargs):
    return compose(
        int_str(format = format),
        _regex(holed_string, regex = regex, **kwargs),
    )

qualify_with_slash = regex_many('{}/{}', ['[^/]*', '.*'])

parens = regex_non_canonical('({})', r'\((.*)\)')
parens_bytes = regex_non_canonical(b'({})', br'\((.*)\)')

bracks = regex_non_canonical('[{}]', r'\[(.*)\]')
bracks_bytes = regex_non_canonical(b'[{}]', br'\[(.*)\]')

braces = regex_non_canonical('{{{}}}', r'\{(.*)\}')
braces_bytes = regex_non_canonical(b'{{{}}}', br'\{(.*)\}')

def join(sep = None, maxsplit = -1):
    _sep = ' ' if sep is None else sep
    return PrintParse(
        print = lambda x: _sep.join(x),
        parse = lambda s: s.split(sep, maxsplit),
    )

def join_bytes(sep = None, maxsplit = -1):
    _sep = b' ' if sep is None else sep
    return PrintParse(
        print = lambda x: _sep.join(x),
        parse = lambda s: s.split(sep, maxsplit),
    )

# Takes an iterable of (value, printed) pairs.
# The default semantics is strict, assuming that values and printings are unique.
# If duplicates are allowed, use strict = False.
def from_dict(xs, print_strict = True, parse_strict = True):
    xs = builtins.tuple(xs)
    return PrintParse(
        print = general.sdict(((x, y) for (x, y) in xs), strict = print_strict).__getitem__,
        parse = general.sdict(((y, x) for (x, y) in xs), strict = parse_strict).__getitem__,
    )

def add(k):
    return PrintParse(
        print = lambda x: x + k,
        parse = lambda x: x - k,
    )

from_one = add(1)

def skip_natural(n):
    def print(i):
        return i if i < n else i + 1

    def parse(i):
        if i == n:
            raise ValueError(f'value {i} is forbidden')
        return i if i < n else i - 1

    return PrintParse(
        print = print,
        parse = parse,
    )

def _singleton_range_parse(range):
    if not general.is_range_singleton(range):
        raise ValueError(f'not a singleton range: {range}')

    return range

singleton_range = PrintParse(
    print = general.range_singleton,
    parse = _singleton_range_parse,
)

def url_quote(safe = '/'):
    return PrintParse(
        print = lambda s: urllib.parse.quote(s, safe = safe),
        parse = urllib.parse.unquote,
    )

url_quote_no_safe = url_quote(safe = '')

pure_posix_path = PrintParse(
    print = str,
    parse = pathlib.PurePosixPath,
)

pure_path = PrintParse(
    print = str,
    parse = pathlib.PurePath,
)

posix_path = PrintParse(
    print = str,
    parse = pathlib.PosixPath,
)

path = PrintParse(
    print = str,
    parse = pathlib.Path,
)

search_path = PrintParse(
    print = path_tools.search_path_join,
    parse = path_tools.search_path_split,
)

# A network location.
# Reference: Section 3.1 of RFC 1738
NetLoc = collections.namedtuple(
    'NetLoc',
    ['host', 'port', 'user', 'password'],
    defaults = [None, None, None]
)

def netloc_normalize(it):
    '''Normalize an iterable into a net location.'''
    return NetLoc(*it)

# Exercise.
# Merge _netloc_print and _netloc_regex_parse into a nice printer-parser network.
def _netloc_print(netloc):
    def password():
        return '' if netloc.password is None else ':' + netloc.password

    login = '' if netloc.user is None else netloc.user + password() + '@'
    port = '' if netloc.port is None else ':' + netloc.port
    return login + netloc.host + port

_safe_regex = '[\\w\\.\\-\\~]*'

_netloc_regex_parser = regex_parser(
    f'(?:(?P<user>{_safe_regex})(?::(?P<password>{_safe_regex}))?@)?(?P<host>{_safe_regex})(?::(?P<port>\\d+))?',
    keyed = True,
    flags = re.ASCII
)
p = _netloc_regex_parser

def _netloc_parse(s):
    return NetLoc(**_netloc_regex_parser(s))

# String representation of network locations.
netloc = compose(
    combine_namedtuple(NetLoc(
        host = url_quote_no_safe,
        port = maybe(int_str()),
        user = maybe(url_quote_no_safe),
        password = maybe(url_quote_no_safe),
    )),
    PrintParse(
        print = _netloc_print,
        parse = _netloc_parse,
    ),
)

query = PrintParse(
    print = lambda query: urllib.parse.urlencode(
        query, doseq = True,
    ),
    parse = lambda query_string: urllib.parse.parse_qs(
        query_string,
        keep_blank_values = True,
        # TODO:
        # Enable once this pull request has been accepted:
        # https://github.com/python/cpython/pull/29716
        #strict_parsing = True,
    )
)

URL = collections.namedtuple(
    'URL',
    ['scheme', 'netloc', 'path', 'query', 'fragments'],
    defaults = ['', {}, None]
)

URL_HTTP = functools.partial(URL, 'http')
URL_HTTPS = functools.partial(URL, 'https')

url = compose(
    combine_namedtuple(urllib.parse.SplitResult(
        identity,
        netloc,
        pure_posix_path,
        query,
        identity,
    )),
    PrintParse(
        print = urllib.parse.urlunsplit,
        parse = urllib.parse.urlsplit,
    ),
)

command_line = PrintParse(
    print = shlex.join,
    parse = shlex.split,
)

ascii = PrintParse(
    print = lambda s: s.encode('ascii'),
    parse = lambda x: x.decode('ascii'),
)

def base64_pad(x):
    k = -len(x) % 4
    if k != 0:
        x += b'=' * k
    return x

base64_standard = PrintParse(
    print = base64.standard_b64encode,
    parse = general.compose(base64_pad, base64.standard_b64decode),
)

base64_standard_str = compose(ascii, base64_standard, invert(ascii))

module_datetime = datetime

def datetime(format):
    return PrintParse(
        print = lambda x: module_datetime.datetime.strftime(x, format),
        parse = lambda x: module_datetime.datetime.strptime(x, format),
    )

module_json = json

json = PrintParse(
    print = module_json.dumps,
    parse = module_json.loads,
)

json_nice = PrintParse(
    print = functools.partial(module_json.dumps, indent = 4, sort_keys = True),
    parse = module_json.loads,
)

def dataclass_dict(cls):
    fields = cls.__dataclass_fields__

    def pp_field(field):
        # Don't use exceptions because this may lie on the critical path.
        if field.metadata is None:
            return identity
        return field.metadata.get('pp', identity)

    def print(x):
        return {
            name: pp_field(field).print(getattr(x, name))
            for (name, field) in fields.items()
        }

    def parse(u):
        return cls(**{
            name: pp_field(field).parse(u[name])
            for (name, field) in fields.items()
        })

    cls.pp = PrintParse(print = print, parse = parse)
    return cls

def dataclass_json(cls, nice = False):
    dataclass_dict(cls)
    cls.pp = compose(cls.pp, json_nice if nice else json)
    return cls

def field(pp):
    return dataclasses.field(metadata = {'pp': pp})
