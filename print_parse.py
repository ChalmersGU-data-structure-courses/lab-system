# Designed to be imported qualified.
import re
import collections

import general

# Approximations to isomorphisms.
PrintParse = collections.namedtuple('PrintParse', ['print', 'parse'])

id = PrintParse(
    print = general.identity,
    parse = general.identity,
)

def compose(x, y):
    return PrintParse(
        print = general.compose(x.print, y.print),
        parse = general.compose(y.parse, x.parse),
    )

def swap(x):
    return PrintParse(
        print = x.parse,
        parse = x.print,
    )

singleton = PrintParse(
    print = general.singleton,
    parse = general.from_singleton,
)

#from_singleton = swap(singleton)

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

def on(i, x):
    return PrintParse(
        print = general.on(i, x.print),
        parse = general.on(i, x.parse),
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

def regex(holed_string, regex = '.*', **kwargs):
    return regex_non_canonical(
        holed_string,
        holed_string.format(f'({regex})'),
        **kwargs,
    )

# Sidestep limitations of shadowing in Python.
_regex = regex

def regex_many(holed_string, regexes, **kwargs):
    return regex_non_canonical_many(
        holed_string,
        holed_string.format(*(f'({regex})' for regex in regexes)),
        **kwargs,
    )

def regex_keyed(holed_string, regexes_keyed, **kwargs):
    return regex_non_canonical_keyed(
        holed_string,
        holed_string.format(**dict((key, f'(?P<{key}>{regex})') for (key, regex) in regexes_keyed.items())),
        **kwargs,
    )

# Takes a format string with a single hole.
def regex_int(holed_string, format = '', regex = '\\d+', **kwargs):
    return compose(
        int_str(format = format),
        _regex(holed_string, regex = regex, **kwargs),
    )

qualify_with_slash = regex_many('{}/{}', ['[^/]*', '.*'])

# Takes an iterable of (value, printed) pairs.
# The default semantics is strict, assuming that values and printings are unique.
# If duplicates are allowed, use strict = False.
def from_dict(xs, print_strict = True, parse_strict = True):
    xs = tuple(xs)
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
