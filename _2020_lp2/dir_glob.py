import itertools
from pathlib import Path

from general import join_lines


def read_patterns(file, missing_ok = False):
    if missing_ok and not file.exists():
        return []

    return (Path(line) for line in file.read_text().splitlines())

def write_patterns(file, patterns):
    file.write_text(join_lines(map(str, patterns)))

root = Path('/')
children = Path('*')
descendants = Path('**')

def move_up_pattern(name, pattern):
    return root / name / pattern.relative_to(root) if pattern.is_absolute() else children / pattern

def move_up_patterns(name, patterns):
    return map(lambda pattern: move_up_pattern(name, pattern), patterns)

# Pitfal: does not list hidden files.
def match_pattern(dir, pattern):
    return dir.glob(str(pattern.relative_to(root) if pattern.is_absolute() else descendants / pattern))

def match_patterns(dir, patterns):
    return itertools.chain.from_iterable(match_pattern(dir, pattern) for pattern in patterns)
