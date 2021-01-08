from collections import defaultdict
from datetime import datetime, timedelta, timezone
import decimal
import errno
import functools
import itertools
import json
from pathlib import Path
import  time
import re
from types import SimpleNamespace
import os
import shutil
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
    return [x]

def from_singleton(xs):
    ys = list(xs)
    assert(len(ys) >= 1)
    assert(len(ys) <= 1)
    return ys[0]

def choose_unique(f, xs):
    return from_singleton(filter(f, xs))

def last(xs, default = None, strict = False):
    for x in xs:
        good = True

    if good:
        return x

    assert(not strict)
    return default

def with_default(f, x, default):
    return f(x) if x != None else default

def with_none(f, x):
    return with_default(f, x, None)

def without_adjacent_dups(eq, xs):
    has_last = False
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

def on(f, key):
    return lambda x, y: f(key(x), key(y))

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

def sdict(xs):
    r = dict()
    for k, v in xs:
        assert not k in r
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

def on_component(i, f):
    def h(xs):
        ys = copy(xs)
        ys[i] = f(xs[i])
        return ys
    return h

on_first  = functools.partial(on_component, 0)
on_second = functools.partial(on_component, 1)
on_third  = functools.partial(on_component, 2)
on_fourth = functools.partial(on_component, 3)

def ev(*x):
    return lambda f: f(*x)

def tuple(*fs):
    return lambda *x: tuple(map(ev(*x), fs))

def zip_dicts_with(f, us, vs):
    for k, u in us.items():
        v = vs.get(k)
        if v:
            yield (k, f(u, vs[k]))

def zip_dicts(us, vs):
    return zip_dicts_with(tuple, us, vs)

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
