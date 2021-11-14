import chardet
from collections import defaultdict, namedtuple
import contextlib
from datetime import datetime, timedelta, timezone
import decimal
import errno
import fcntl
import functools
import itertools
import json
from pathlib import Path
import re
import tempfile
import time
from types import SimpleNamespace
import os
import shlex
import shutil
import subprocess
import sys

def identity(x):
    return x

def compose(f, g):
    return lambda *x: g(f(*x))

def compose_many(*fs):
    return functools.reduce(compose, fs, identity)

def flatten(*xss):
    return list(itertools.chain(*xss))

def singleton(x):
    return (x,)

def from_singleton(xs):
    (x,) = xs
    return x

def ensure_empty(it):
    try:
        next(it)
        raise ValueError('unexpected element')
    except StopIteration:
        return

def from_singleton_maybe(xs):
    xs = iter(xs)
    try:
        r = next(xs)
    except StopIteration:
        return None
    try:
        ensure_empty(xs)
    except ValueError:
        raise ValueError('contains more than one element')
    return r

def choose_unique(f, xs):
    return from_singleton(filter(f, xs))

def swap_pair(xs):
    (a, b) = xs
    return (b, a)

def interchange(xss):
    return tuple(zip(*xss))

def last(xs, default = None, strict = False):
    for x in xs:
        good = True

    if good:
        return x

    assert(not strict)
    return default

def with_special_case(f, key, value):
    return lambda x: value if x == key else f(x)

def check_return(pred):
    def f(x):
        if pred(x):
            return x
        raise ValueError(f'Forbidden value {x}')
    return f

def with_default(f, x, default):
    return f(x) if x != None else default

def with_none(f, x):
    return with_default(f, x, None)

def maybe(f):
    return lambda x: with_none(f, x)

# Bug in pyflakes (TODO: report):
# ./general.py:102:28 local variable 'last' defined in enclosing scope on line 70 referenced before assignment
# ./general.py:106:9 local variable 'last' is assigned to but never used
def without_adjacent_dups(eq, xs):
    has_last = False
    last = None  # Only there to work around bug in pyflakes.
    for x in xs:
        if has_last and eq(last, x):
            continue
        yield x
        has_last = True
        last = x

def unique_by(f, xs):
    rs = list()
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

def list_get(xs, i):
    return xs[i] if i < len(xs) else None

def map_maybe(f, xs):
    return filter(lambda x: x != None, map(f, xs))

# missing in itertools.
def starfilter(f, xs):
    for x in xs:
        if f(*x):
            yield x

def sdict(xs, strict = True):
    r = dict()
    if strict:
        for k, v in xs:
            if k in r:
                raise ValueError(f'duplicate entry for key {k}')
            r[k] = v
    return r

def multidict(xs):
    r = defaultdict(list)
    for (k, v) in xs:
        r[k].append(v)
    return r

def ignore_none_keys(xs):
    return starfilter(lambda k, _: k != None, xs)

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

def component(i):
    return lambda x: x[i]

first  = component(0)
second = component(1)
third  = component(2)
fourth = component(3)

def ev(*x):
    return lambda f: f(*x)

def tupling(*fs):
    return lambda *x: tuple(map(ev(*x), fs))

def zip_dicts_with(f, us, vs):
    for k, u in us.items():
        v = vs.get(k)
        if v != None:
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
    us, vs = list(), list()
    for x in xs:
        (us if f(x) else vs).append(x)
    return (us, vs)

def join_lines(lines):
    return ''.join(line + '\n' for line in lines)

def join_null(lines):
    return ''.join(line + '\0' for line in lines)

def doublequote(s):
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'

def parens(s):
    return f'({s})'

class Timer:
    def __enter__(self):
        self.start = time.monotonic()
        return self

    def __exit__(self, type, value, traceback):
        self.end = time.monotonic()
        self.time = self.end - self.start

class JSONObject(SimpleNamespace):
    DATE_PATTERN = re.compile("[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._dict = kwargs

        for key in kwargs:
            value = str(kwargs[key])
            # idea from canvasapi/canvas_object.py
            if JSONObject.DATE_PATTERN.match(value):
                t = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo = timezone.utc)
                new_key = key + "_date"
                self.__setattr__(new_key, t)

class JSONEncoderForJSONObject(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, JSONObject):
            return obj._dict

def print_json(x):
    print(json_encoder.encode(x))

json_encoder = JSONEncoderForJSONObject(indent = 4, sort_keys = True)

def write_lines(file, lines):
    for line in lines:
        file.write(line)
        file.write('\n')

def print_error(*objects, sep = ' ', end = '\n'):
    print(*objects, sep = sep, end = end, file = sys.stderr)

def get_recursive_modification_time(path):
    t = os.path.getmtime(path)
    #print(t)
    #if Path(path).islink():
    #    t = max(t, get_recursive_modification_time(path.parent / path.readlink()))
    return t

def set_modification_time(path, date):
    t = date.timestamp()
    os.utime(path, (t, t))

# In Python 3.9, equivalent to path.with_stem(stem).
def with_stem(path, stem):
    return path.with_name(stem + path.suffix)

def add_suffix(path, suffix):
    return path.parent / (path.name + suffix)

def sorted_directory_list(dir, filter = None):
   return dict(sorted(((f.name, f) for f in dir.iterdir() if not filter or filter(f)), key = lambda x: x[0]))

class OpenWithModificationTime:
    def __init__(self, path, date):
        self.path = path
        self.date = date

    def __enter__(self):
        self.file = self.path.open('w')
        return self.file.__enter__()

    def __exit__(self, exc_type, exc_value, traceback):
        self.file.__exit__(exc_type, exc_value, traceback)
        set_modification_time(self.path, self.date)

class OpenWithNoModificationTime(OpenWithModificationTime):
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self.time = os.path.getmtime(self.path)
        self.file = self.path.open('w')
        return self.file.__enter__()

    def __exit__(self, exc_type, exc_value, traceback):
        self.file.__exit__(exc_type, exc_value, traceback)
        os.utime(self.path, (self.time, self.time))

def modify(path, callback):
    content = path.read_text()
    content = callback(content)
    with path.open('w') as file:
       file.write(content)

def modify_no_modification_time(path, callback):
    content = path.read_text()
    content = callback(content)
    with OpenWithNoModificationTime(path) as file:
       file.write(content)

def mkdir_fresh(path):
    if path.exists():
        shutil.rmtree(path)
    path.mkdir()

def file_exists_error(path):
    e = errno.EEXIST
    raise FileExistsError(e, os.strerror(e), str(path))

def safe_symlink(source, target, exists_ok = False):
    if source.exists():
        if not (exists_ok and source.is_symlink() and Path(os.readlink(source)) == target):
            file_exists_error(source)
    else:
        source.symlink_to(target, target.is_dir())

# 'rel' is the path to 'dir_from', taken relative to 'dir_to'.
# Returns list of newly created files.
def link_dir_contents(dir_from, dir_to, rel = None, exists_ok = False):
    if rel == None:
        rel = Path(os.path.relpath(dir_from, dir_to))

    files = list()
    for path in dir_from.iterdir():
        file = dir_to / path.name
        files.append(file)
        target = rel / path.name
        safe_symlink(file, target, exists_ok = exists_ok)
    return files

def copy_tree_fresh(source, to, **flags):
    if to.exists():
        if to.is_dir():
            shutil.rmtree(to)
        else:
            to.unlink()
    shutil.copytree(source, to, **flags)

def exec_simple(file):
    r = dict()
    exec(file.read_text(), r)
    return SimpleNamespace(**r)

def readfile(fil):
    with open(fil, "br") as F:
        bstr = F.read()
    try:
        return bstr.decode()
    except UnicodeDecodeError:
        try:
            return bstr.decode(encoding="latin1")
        except UnicodeDecodeError:
            return bstr.decode(errors="replace")

def java_string_encode(x):
    return json.dumps(x)

def java_string_decode(y):
    return json.loads(y)

def guess_encoding(b):
    encodings = ['utf-8', 'latin1']
    for encoding in encodings:
        try:
            return b.decode(encoding = encoding)
        except UnicodeDecodeError:
            pass

    return b.decode()

def fix_encoding(path):
    content = guess_encoding(path.read_bytes())
    with OpenWithNoModificationTime(path) as file:
        file.write(content)

def format_with_leading_zeroes(x, bound):
    num_digits = len(str(bound - 1))
    return f'{x:0{num_digits}}'

def format_with_rel_prec(x, precision = 3):
    context = decimal.Context(prec = precision, rounding = decimal.ROUND_DOWN)
    return str(context.create_decimal_from_float(x))

def appropriate_time_unit(delta):
    time_units_min = {
        'microseconds': timedelta(microseconds = 1),
        'milliseconds': timedelta(milliseconds = 1),
        'seconds': timedelta(seconds = 1),
        'minutes': timedelta(seconds = 100),
        'hours': timedelta(minutes = 100),
        'days': timedelta(days = 2),
        'weeks': timedelta(days = 30),
    }

    for time_unit, min in reversed(time_units_min.items()):
        if abs(delta) >= min:
            return time_unit
    return time_unit

def format_timespan_using(delta, time_unit, precision = 2):
    return '{} {}'.format(format_with_rel_prec(delta / timedelta(**{time_unit: 1})), time_unit)

def format_timespan(delta, precision = 2):
    return format_timespan_using(delta, appropriate_time_unit(delta), precision)

def add_to_path(dir):
    path = str(dir.resolve())
    assert(not (':' in path))
    os.environ['PATH'] = path + ':' + os.environ['PATH']

@contextlib.contextmanager
def temp_fifo():
    with tempfile.TemporaryDirectory() as dir:
        fifo = Path(dir) / 'fifo'
        os.mkfifo(fifo)
        try:
            yield fifo
        finally:
            fifo.unlink()

def Popen(cmd, **kwargs):
    print(shlex.join(cmd), file = sys.stderr)
    fds = list(kwargs.get('pass_fds', []))
    for fd in fds:
        os.set_inheritable(fd, True)
    p = subprocess.Popen(cmd, **kwargs)
    for fd in fds:
        os.close(fd)
    return p

def check_process(p):
    p.wait()
    assert(p.returncode == 0)

# Only implemented for linux.
def pipe(min_size):
    (r, w) = os.pipe()
    F_SETPIPE_SZ = 1031
    fcntl.fcntl(r, F_SETPIPE_SZ, min_size)
    return (r, w)

@contextlib.contextmanager
def working_dir(path):
    old = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)

def log_command(logger, cmd, working_dir = False):
    logger.debug('running command{}:\n{}'.format(' in {}'.format(shlex.quote(os.getcwd())) if working_dir else '', shlex.join(cmd)))

def wait_and_check(process, cmd):
    r = process.wait()
    if r != 0:
        raise subprocess.CalledProcessError(r, cmd)

# Detection seems not to be so good.
# A Unicode file with 'Markus Järveläinen' is detected as EUC-KR.
def detect_encoding(files):
    detector = chardet.universaldetector.UniversalDetector()
    for file in files:
        if isinstance(file, str):
            file = Path(file)
        detector.feed(file.read_bytes())
    detector.close()
    return detector.result['encoding']

def read_text_detect_encoding(path):
    try:
        return path.read_text()
    except UnicodeDecodeError:
        return path.read_text(encoding = detect_encoding([path]))

def read_without_comments(path):
    return list(filter(lambda s: s and not s.startswith('#'), path.read_text().splitlines()))

def unique_list(xs):
    return list(dict.fromkeys(xs))

def find_all(key, s, start = 0):
    r = s.find(key, start)
    if r != -1:
        yield r
        yield from find_all(key, s, r + len(key))

def find_all_many(keywords, s):
    '''
    keywords is a dictionary whose values are keywords to be searched in the string text.
    The result is a list of pairs (k, i) where k is a dictionary key and i is a position in s where k appears.
    The result is sorted by positions.
    '''
    return sorted((i, k) for (k, v) in keywords.items() for i in find_all(v, s))

def filter_keywords(keywords, s):
    '''
    keywords is a dictionary whose values are keywords to be searched in the string text.
    The result is a list of (not necessarily unique) keys of dictionary in the order they appear in text.
    '''
    return [k for i, k in find_all_many(keywords, s)]

# A context manager for file paths.
class ScopedFiles:
    def __init__(self):
        self.files = []

    def add(self, file):
        self.files.append(file)

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        for file in reversed(self.files):
            file.unlink()

Lens = namedtuple('Lens', ['get', 'set'])

# For copyable collections such as list and dict.
def component(key):
    def set(u, value):
        v = u.copy()
        v[key] = value
        return v

    return Lens(
        get = lambda u: u[key],
        set = lambda u, value: set(u, key, value),
    )

def component_tuple(key):
    def set(u, value):
        v = list(u)
        v[key] = value
        return tuple(v)

    return Lens(
        get = lambda u: u[key],
        set = set,
    )

def component_namedtuple(key):
    return Lens(
        get = lambda u: u[key],
        set = lambda u, value: u._replace(**{key: value}),
    )

def on(lens, f):
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
    return lambda xs: dict((key, f(xs[key])) for (key, f) in fs.items())

def combine_namedtuple(fs):
    return lambda xs: fs.__class__._make(f(x) for (f, x) in zip(fs, xs))

# Deduce the type of collections to work on from the collection type of the argument.
def combine_generic(fs):
    if isinstance(fs, (list, tuple)):
        r = combine
    elif isinstance(fs, dict):
        r = combine_dict
    elif hasattr(fs.__class__, '_make'):
        r = combine_namedtuple
    return r(fs)

def remove_prefix(xs, prefix, strict = True):
    if xs[:len(prefix)] == prefix:
        return xs[len(prefix):]

    if strict:
        raise ValueError('{xs} does not have prefix {[refix}')
    return xs

def map_values(f, u):
    return dict((key, f(value)) for (key, value) in u.items())

def eq_on(x, y, f = identity):
    return f(x) == f(y)

def ne_on(x, y, f = identity):
    return f(x) != f(y)

def dict_union(us):
    '''
    The union of an iterable of dictionaries.
    Later keys take precedence.
    '''
    r = dict()
    for u in us:
        r |= u
    return r

def normalize_list_index(n, i):
    return i if i >= 0 else n + i

def previous_items(collection, item):
    ''' Returns a generator producing items in a collection prior to the given one in reverse order. '''
    found = False
    for i in reversed(collection):
        if found:
            yield i
        if i == item:
            found = True

def range_of(xs):
    xs = tuple(xs)
    return (min(xs), max(xs) + 1)

def len_range(range):
    (start, end) = range
    return end - start

def range_is_empty(range):
    (start, end) = range
    return start != None and end != None and start >= end

def range_from_size(i, n):
    return (i, i + n)

def range_singleton(i):
    return range_from_size(i, 1)

def is_range_singleton(range):
    (start, end) = range
    return end == start + 1

def range_shift(range, offset):
    (start, end) = range
    return (start + offset, end + offset)

def when(condition, value):
    # not condition or value
    return value if condition else True

def canonical_keys(items, key = None):
    '''
    Canonicalize sort keys.
    Takes an iterable of unique items.
    Returns a dictionary mapping items to sort keys from an interval starting at 0.
    If key is given, it is used as key function for sorting the items.
    Note that the items are not required to be unique under the key function.
    '''
    def f():
        for (out_key, (_, xs)) in enumerate(itertools.groupby(sorted(items, key = key), key = key)):
            for x in xs:
                yield (x, out_key)
    return dict(f())
