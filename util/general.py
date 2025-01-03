import abc
import contextlib
import dataclasses
import decimal
import fcntl
import functools
import itertools
import json
import logging
import os
import re
import shlex
import string
import subprocess
import sys
import time
from collections import defaultdict, namedtuple
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Callable, Protocol

import more_itertools
import requests


def identity[T](x: T) -> T:
    return x


def compose_binary(f, g):
    return lambda *x: g(f(*x))


def compose(*fs):
    return functools.reduce(compose_binary, fs, identity)


def flatten(*xss):
    return list(itertools.chain(*xss))


def singleton(x):
    return (x,)


class EmptynessError(ValueError):
    def __init__(self, element, rest):
        self.element = element
        self.rest = rest


def ensure_empty(it):
    it = iter(it)
    try:
        x = next(it)
        raise EmptynessError(x, it)
    except StopIteration:
        pass


class UniquenessError(ValueError):
    def __init__(self, iterator):
        self.iterator = iterator

    @classmethod
    @abc.abstractmethod
    def inflect_value(cls): ...


class UniquenessErrorNone(UniquenessError):
    def __init__(self):
        super().__init__(())

    @classmethod
    def inflect_value(cls):
        return "no value"


class UniquenessErrorMultiple(UniquenessError):
    def __init__(self, first, second, rest):
        super().__init__(itertools.chain((first, second), rest))
        self.first = first
        self.second = second
        self.rest = rest

    @classmethod
    def inflect_value(cls):
        return "multiple values"


def from_singleton(xs):
    xs = iter(xs)
    try:
        r = next(xs)
    except StopIteration:
        raise UniquenessErrorNone() from None
    try:
        ensure_empty(xs)
    except EmptynessError as e:
        raise UniquenessErrorMultiple(r, e.element, e.rest) from None
    return r


def from_singleton_maybe(xs):
    xs = iter(xs)
    try:
        r = next(xs)
    except StopIteration:
        return None
    try:
        ensure_empty(xs)
    except EmptynessError as e:
        raise UniquenessErrorMultiple(r, e.element, e.rest) from None
    return r


def choose_unique(f, xs):
    return from_singleton(filter(f, xs))


def swap(xs):
    (a, b) = xs
    return (b, a)


def interchange(xss):
    return tuple(zip(*xss))


def last(xs, default=None, strict=False):
    good = False
    for x in xs:
        good = True

    if good:
        # pylint: disable-next=undefined-loop-variable
        return x

    assert not strict
    return default


def with_special_case(f, key, value):
    return lambda x: value if x == key else f(x)


def check_return(pred):
    def f(x):
        if pred(x):
            return x
        raise ValueError(f"Forbidden value {x}")

    return f


def with_default(f, x, default=None):
    return default if x is None else f(x)


def maybe(f):
    return lambda x: with_default(f, x)


def defaulting_to(default, value, key=None):
    return default if value == key else value


# Bug in pyflakes (TODO: report):
# ./util.general.py:102:28 local variable 'last' defined in enclosing scope on line 70 referenced before assignment
# ./util.general.py:106:9 local variable 'last' is assigned to but never used
# pylint: disable-next=redefined-outer-name
def without_adjacent_dups(eq, xs):
    has_last = False
    # pylint: disable-next=redefined-outer-name
    last = None  # Only there to work around bug in pyflakes.
    for x in xs:
        if has_last and eq(last, x):
            continue
        yield x
        has_last = True
        last = x


def unique_by(f, xs):
    rs = []
    for x in xs:
        if not any(f(x, r) for r in rs):
            rs.append(x)

    return rs


def eq(x, y):
    return x == y


def equal_by(f, x, y):
    return f(x) == f(y)


def ilen(it):
    return sum(1 for _ in it)


def inhabited(it):
    return any(map(lambda: True, it))


def list_get(xs, i):
    return xs[i] if i < len(xs) else None


def map_maybe(f, xs):
    return filter(lambda x: x is not None, map(f, xs))


# missing in itertools.
def starfilter(f, xs):
    for x in xs:
        if f(*x):
            yield x


class SDictException(ValueError):
    def __init__(self, key, value_a, value_b, format_value=None):
        self.key = key
        self.value_a = value_a
        self.value_b = value_b
        msg = f"duplicate entry for key {key}"
        if format_value is not None:
            msg += f": values {format_value(value_a)} and {format_value(value_b)}"
        super().__init__(msg)


def sdict(xs, strict=True, format_value=None):
    r = {}
    for k, v in xs:
        if strict and k in r:
            raise SDictException(k, r[k], v, format_value=format_value)
        r[k] = v
    return r


def multidict(xs):
    r = defaultdict(list)
    for k, v in xs:
        r[k].append(v)
    return r


def ignore_none_keys(xs):
    return starfilter(lambda k, _: k is not None, xs)


dict_ = compose(ignore_none_keys, dict)
sdict_ = compose(ignore_none_keys, sdict)
sdict_ = compose(ignore_none_keys, sdict)


def with_key(f):
    return lambda x: (f(x), x)


def with_val(f):
    return lambda x: (x, f(x))


def map_with_key(f, xs):
    return map(with_key(f), xs)


def map_with_val(f, xs):
    return map(with_val(f), xs)


map_with_key_ = compose(map_with_key, ignore_none_keys)

dict_from_fun = compose(map_with_val, dict)
sdict_from_fun = compose(map_with_val, sdict)
multidict_from_fun = compose(map_with_val, multidict)


def ev(*x):
    return lambda f: f(*x)


def tupling(*fs):
    return lambda *x: tuple(map(ev(*x), fs))


def zip_dicts_with(f, us, vs):
    for k, u in us.items():
        v = vs.get(k)
        if v is not None:
            yield (k, f(u, v))


def zip_dicts(us, vs):
    return zip_dicts_with(tupling, us, vs)


def group_by_unique(f, xs):
    return sdict(map_with_key(f, xs))


def group_by(f, xs):
    return multidict(map_with_key(f, xs))


def group_by_(f, xs):
    return multidict(map_with_key_(f, xs))


def namespaced(reader):
    for row in reader:
        yield SimpleNamespace(**row)


def get_attr(name):
    return lambda x: getattr(x, name)


def partition(f, xs):
    us, vs = [], []
    for x in xs:
        (us if f(x) else vs).append(x)
    return (us, vs)


def join_lines(lines, terminator="\n"):
    return "".join(line + terminator for line in lines)


def text_from_lines(*lines, terminator: str = "\n") -> str:
    """
    Variable-length argument wrapper for join_lines.
    """
    return join_lines(lines, terminator=terminator)


def doublequote(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def parens(s):
    return f"({s})"


class JSONObject(SimpleNamespace):
    DATE_PATTERN = re.compile("[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._dict = kwargs

        for key, value in kwargs.items():
            value_str = str(value)
            # idea from canvasapi/canvas_object.py
            if JSONObject.DATE_PATTERN.match(value_str):
                t = datetime.strptime(value_str, "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=timezone.utc
                )
                new_key = key + "_date"
                self.__setattr__(new_key, t)


class JSONEncoderForJSONObject(json.JSONEncoder):
    def default(self, o):
        if not isinstance(o, JSONObject):
            return None

        # pylint: disable-next=protected-access
        return o._dict


def print_json(x):
    print(json_encoder.encode(x))


json_encoder = JSONEncoderForJSONObject(indent=4, sort_keys=True)


def print_error(*objects, sep=" ", end="\n"):
    print(*objects, sep=sep, end=end, file=sys.stderr)


def format_with_leading_zeroes(x, bound):
    num_digits = len(str(bound - 1))
    return f"{x:0{num_digits}}"


def format_with_rel_prec(x, precision=3):
    context = decimal.Context(prec=precision, rounding=decimal.ROUND_DOWN)
    return str(context.create_decimal_from_float(x))


def appropriate_time_unit(delta):
    time_units_min = {
        "microseconds": timedelta(microseconds=1),
        "milliseconds": timedelta(milliseconds=1),
        "seconds": timedelta(seconds=1),
        "minutes": timedelta(seconds=100),
        "hours": timedelta(minutes=100),
        "days": timedelta(days=2),
        "weeks": timedelta(days=30),
    }

    for time_unit, min_ in reversed(time_units_min.items()):
        if abs(delta) >= min_:
            return time_unit
    # pylint: disable-next=undefined-loop-variable
    return time_unit


def format_timespan_using(delta, time_unit, precision=3):
    amount = format_with_rel_prec(
        delta / timedelta(**{time_unit: 1}),
        precision=precision,
    )
    return f"{amount} {time_unit}"


def format_timespan(delta, precision=3):
    return format_timespan_using(delta, appropriate_time_unit(delta), precision)


class Timer:
    # pylint: disable=attribute-defined-outside-init

    def __enter__(self):
        self.start = time.monotonic()
        return self

    def __exit__(self, type_, value, traceback):
        self.stop = time.perf_counter()
        self.time = self.stop - self.start
        self.timedelta = timedelta(seconds=self.time)


@contextlib.contextmanager
def timing(name=None, logger=None, level=logging.DEBUG):
    # Perform measurement.
    timer = Timer()
    with timer:
        yield

    # Format message.
    if name is None:
        name = "timing"
    duration = format_timespan(timer.timedelta)
    msg = f"{name}: {duration}"

    # Log message.
    if logger is None:
        print(msg, file=sys.stderr)
    else:
        logger.log(level, msg)


def Popen(cmd, **kwargs):
    print(shlex.join(cmd), file=sys.stderr)
    fds = list(kwargs.get("pass_fds", []))
    for fd in fds:
        os.set_inheritable(fd, True)

    # pylint: disable-next=R1732
    p = subprocess.Popen(cmd, **kwargs)
    for fd in fds:
        os.close(fd)
    return p


def check_process(p):
    p.wait()
    assert p.returncode == 0


# Only implemented for linux.
def pipe(min_size):
    (r, w) = os.pipe()
    F_SETPIPE_SZ = 1031
    fcntl.fcntl(r, F_SETPIPE_SZ, min_size)
    return (r, w)


def log_command(logger, cmd, working_dir=False):
    where = " in " + format(shlex.quote(os.getcwd())) if working_dir else ""
    logger.debug(f"running command{where}:\n{shlex.join(map(str, cmd))}")


def wait_and_check(process, cmd, stderr=None):
    r = process.wait()
    if r != 0:
        raise subprocess.CalledProcessError(r, cmd, stderr=stderr)


def unique_list(xs):
    return list(dict.fromkeys(xs))


def find_all(key, s, start=0):
    r = s.find(key, start)
    if r != -1:
        yield r
        yield from find_all(key, s, r + len(key))


def find_all_many(keywords, s):
    """
    keywords is a dictionary whose values are keywords to be searched in the string text.
    The result is a list of pairs (k, i) where k is a dictionary key and i is a position in s where k appears.
    The result is sorted by positions.
    """
    return sorted((i, k) for (k, v) in keywords.items() for i in find_all(v, s))


def filter_keywords(keywords, s):
    """
    keywords is a dictionary whose values are keywords to be searched in the string text.
    The result is a list of (not necessarily unique) keys of dictionary in the order they appear in text.
    """
    return [k for i, k in find_all_many(keywords, s)]


class Lens[A, B](Protocol):
    """
    Protocol for a lens.
    """
    def get(self, _a: A, /) -> B:
        """
        Get the target attribute from _a.
        """

    def set(self, _a: A, _b: B, /) -> A:
        """
        Set the target attribute of _a to _b.
        """


LensOf = namedtuple("LensOf", ["get", "set"])


# For copyable collections such as list and dict.
def component(key):
    def set_(u, value):
        v = u.copy()
        v[key] = value
        return v

    return LensOf(
        get=lambda u: u[key],
        set=set_,
    )


def component_tuple(key):
    def set_(u, value):
        v = list(u)
        v[key] = value
        return tuple(v)

    return LensOf(
        get=lambda u: u[key],
        set=set_,
    )


def component_namedtuple(key):
    return LensOf(
        get=lambda u: u[key],
        set=lambda u, value: u._replace(**{key: value}),
    )


def on[A, B](lens: Lens[A, B], f: Callable[[B], B]) -> Callable[[A], A]:
    return lambda u: lens.set(u, f(lens.get(u)))


# These functions take a collection of unary functions
# and return a unary function acting on collections
# of the same layout (e.g., same length, same keys).
def combine_list(fs):
    return lambda xs: list(f(x) for (f, x) in zip(fs, xs))


def combine_tuple(fs):
    return lambda xs: tuple(f(x) for (f, x) in zip(fs, xs))


combine = combine_tuple


def combine_dict(fs):
    return lambda xs: {key: f(xs[key]) for (key, f) in fs.items()}


def combine_namedtuple(fs):
    return lambda xs: fs.__class__._make(f(x) for (f, x) in zip(fs, xs))


# Deduce the type of collections to work on from the collection type of the argument.
def combine_generic(fs):
    if isinstance(fs, (list, tuple)):
        r = combine
    elif isinstance(fs, dict):
        r = combine_dict
    elif hasattr(fs.__class__, "_make"):
        r = combine_namedtuple
    else:
        raise ValueError(f"no combine instance for {type(fs)}")
    return r(fs)


def remove_prefix(xs, prefix):
    if xs[: len(prefix)] == prefix:
        return xs[len(prefix) :]

    raise ValueError(f"{xs} does not have prefix {prefix}")


def remove_suffix(xs, suffix):
    if xs[-len(suffix) :] == suffix:
        return xs[: -len(suffix)]

    raise ValueError(f"{xs} does not have prefix {suffix}")


def map_keys_and_values(f, g, u):
    return {f(key): g(value) for (key, value) in u.items()}


def map_keys(f, u):
    return map_keys_and_values(f, identity, u)


def map_values(g, u):
    return map_keys_and_values(identity, g, u)


def eq_on(x, y, f=identity):
    return f(x) == f(y)


def ne_on(x, y, f=identity):
    return f(x) != f(y)


def dict_union(us):
    """
    The union of an iterable of dictionaries.
    Later keys take precedence.
    """
    r = {}
    for u in us:
        r |= u
    return r


def normalize_list_index(n, i):
    return i if i >= 0 else n + i


def previous_items(collection, item):
    """Returns a generator producing items in a collection prior to the given one in reverse order."""
    found = False
    for i in reversed(collection):
        if found:
            yield i
        if i == item:
            found = True


Range = tuple[int, int]


def range_of(xs) -> Range | None:
    xs = list(xs)
    return (min(xs), max(xs) + 1) if xs else None


def len_range(range_: Range) -> int:
    (start, end) = range_
    return end - start


def range_is_empty(range_: Range) -> bool:
    (start, end) = range_
    return start is not None and end is not None and start >= end


def range_from_size(i: int, n: int) -> Range:
    return (i, i + n)


def range_singleton(i: int) -> Range:
    return range_from_size(i, 1)


def is_range_singleton(range_: Range) -> bool:
    (start, end) = range_
    return end == start + 1


def range_shift(range_: Range, offset: int) -> Range:
    (start, end) = range_
    return (start + offset, end + offset)


def when(condition, value):
    # not condition or value
    return value if condition else True


def canonical_keys(items, key=None):
    """
    Canonicalize sort keys.
    Takes an iterable of unique items.
    Returns a dictionary mapping items to sort keys from an interval starting at 0.
    If key is given, it is used as key function for sorting the items.
    Note that the items are not required to be unique under the key function.
    """

    def f():
        for out_key, (_, xs) in enumerate(
            itertools.groupby(sorted(items, key=key), key=key)
        ):
            for x in xs:
                yield (x, out_key)

    return dict(f())


def split_dict(u, f):
    """
    Split the dictionary u into two parts, based on the key filter function f.
    The function f takes a key and returns a boolean.
    The result is a pair of dictionaries (v, w):
    - v contains all keys that satisfy f.
    - w contains the remaining keys.
    """
    v = {}
    w = {}
    for key, value in u.items():
        (v if f(key) else w)[key] = value
    return (v, w)


def recursive_defaultdict():
    return defaultdict(recursive_defaultdict)


def recursive_dict_values(u):
    if isinstance(u, dict):
        for v in u.values():
            yield from recursive_dict_values(v)
    else:
        yield u


def expand_hierarchy(v, key_split, initial_value=None):
    r = {} if initial_value is None else initial_value
    for combined_key, value in v.items():
        last_key = None
        for part in key_split(combined_key):
            x = r if last_key is None else x.setdefault(last_key, {})  # noqa: F821
            last_key = part
        if last_key is None:
            r = value
        else:
            x[last_key] = value
    return r


def flatten_hierarchy_prefix(u, key_combine, prefix):
    def f(u, prefix):
        if isinstance(u, dict):
            for key, value in u.items():
                prefix.append(key)
                yield from f(value, prefix)
                prefix.pop()
        else:
            yield (key_combine(prefix), u)

    return dict(f(u, prefix))


def flatten_hierarchy(u, key_combine=tuple):
    return dict(flatten_hierarchy_prefix(u, key_combine, []))


@dataclasses.dataclass
class BoolException(Exception):
    value: bool


@contextlib.contextmanager
def add_cleanup(manager, action):
    """
    Adds a cleanup action to a context manager.

    Arguments:
    * manager: The manager to modify.
    * action:
        A nullary callback function.
        Called just before the manager.__exit__ is called.

    Returns the new context manager.
    """
    with manager as value:
        try:
            yield value
        finally:
            action()


def escape_percent(s):
    return re.sub("%", "%%", s)


def has_whitespace(s):
    return any(c in s for c in string.whitespace)


def is_sorted(xs, key=None):
    if key is None:
        key = identity

    return all(key(a) <= key(b) for (a, b) in pairwise(xs))


# No longer used?
def next_after(xs, select):
    it = itertools.dropwhile(lambda x: not select(x), xs)
    try:
        next(it)
    except StopIteration:
        raise KeyError() from None
    try:
        return next(it)
    except StopIteration:
        return None


_OMIT = object()


def intercalate(it, middle, start=_OMIT, end=_OMIT):
    if not start is _OMIT:
        yield start
    yield from more_itertools.intersperse(middle, it)
    if not end is _OMIT:
        yield end


@contextlib.contextmanager
def traverse_managers_iterable(xs):
    """Lazy traversal of context managers."""
    with contextlib.ExitStack() as stack:

        def f():
            for x in xs:
                yield stack.enter_context(x)

        yield f()


@contextlib.contextmanager
def traverse_managers_list(xs):
    """Strict traversal of context managers."""
    with traverse_managers_iterable(xs) as it:
        yield list(it)


# In itertools from 3.10.
def pairwise(iterable):
    a, b = itertools.tee(iterable)
    next(b, None)
    return zip(a, b)


# In more_itertools from 3.10
def before_and_after(predicate, it):
    it = iter(it)
    transition = []

    def true_iterator():
        for elem in it:
            if predicate(elem):
                yield elem
            else:
                transition.append(elem)
                return

    return (true_iterator(), itertools.chain(transition, it))


def caching(f):
    @functools.wraps(f)
    def g(*args, **kwargs):
        # pylint: disable=protected-access
        try:
            return g._cached_value
        except AttributeError:
            g._cached_value = f(*args, **kwargs)
            return g._cached_value

    return g


def now():
    return datetime.now(tz=timezone.utc)


## # Network protocols


# TODO: move elsewhere.
class BearerAuth(requests.auth.AuthBase):
    def __init__(self, token):
        self.token = token

    def __call__(self, r):
        r.headers["Authorization"] = f"Bearer {self.token}"
        return r
