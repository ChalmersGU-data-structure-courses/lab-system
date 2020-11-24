from collections import defaultdict
import json
from types import SimpleNamespace
import re
from datetime import datetime, timedelta, timezone
import os
import sys

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
