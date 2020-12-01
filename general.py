from collections import defaultdict
import decimal
import json
from types import SimpleNamespace
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import shutil
import sys

def from_singleton(xs):
    ys = list(xs)
    assert(len(ys) >= 1)
    assert(len(ys) <= 1)
    return ys[0]

def unique_by(f, xs):
    rs = list()
    for x in xs:
        if not any(f(x, r) for r in rs):
            rs.append(x)

    return rs

def multidict(xs):
    r = defaultdict(list)
    for (k, v) in xs:
        r[k].append(v)
    return r

def group_by(f, xs):
    return multidict([(f(x), x) for x in xs])

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

def set_modification_time(path, date):
    t = date.timestamp()
    os.utime(path, (t, t))

# In Python 3.9, equivalent to path.with_stem(stem).
def with_stem(path, stem):
    return path.with_name(stem + path.suffix)

def add_suffix(path, suffix):
    return path.parent / (path.name + suffix)

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
    with path.open('w') as file:
       file.write(callback(content))

def modify_no_modification_time(path, callback):
    content = path.read_text()
    with OpenWithNoModificationTime(path) as file:
       file.write(callback(content))

def mkdir_fresh(path):
    if path.exists():
        shutil.rmtree(path)
    path.mkdir()

# 'rel' is the path to 'dir_from', taken relative to 'dir_to'.
# Returns list of newly created files.
def link_dir_contents(dir_from, dir_to, rel = None):
    if rel == None:
        rel = Path(os.path.relpath(dir_from, dir_to))

    files = list()
    for path in dir_from.iterdir():
        file = dir_to / path.name
        files.append(file)
        target = rel / path.name
        if file.exists():
            assert(Path(os.readlink(file)) == target)
        else:
            file.symlink_to(target, path.is_dir())
    return files

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

def guess_encoding(b):
    encodings = ['utf-8', 'latin1']
    for encoding in encodings:
        try:
            return b.decode(encoding = encoding)
        except UnicodeDecodeError:
            pass

    return b.decode()

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
    num = delta / timedelta(**{time_unit: 1})
    context = decimal.Context(prec = precision, rounding = decimal.ROUND_DOWN)
    return '{} {}'.format(context.create_decimal_from_float(num), time_unit)

def format_timespan(delta, precision = 2):
    return format_timespan_using(delta, appropriate_time_unit(delta), precision)
