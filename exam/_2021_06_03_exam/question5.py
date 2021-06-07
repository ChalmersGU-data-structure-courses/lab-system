import java
from pathlib import Path
import random
import subprocess

this_dir = Path(__file__).parent

name = 'HashTables20210604'

def parse_output(s):
    for line in s.splitlines():
        a = line.split('=', maxsplit = 1)
        if len(a) == 2:
            yield(a[0], a[1].strip('"'))

def compile():
    java.compile_java([this_dir / (name + '.java')])

def run_and_parse(args):
    cmd = list(java.java_cmd(name, args))
    output = subprocess.run(cmd, check = True, capture_output = True, encoding = 'utf-8', cwd = this_dir).stdout
    yield from parse_output(output)

class Generator:
    def __init__(self, seed):
        r = random.Random(seed)
        self.java_seed = r.randrange(1000000)
        compile()

    def replacements(self, solution = False):
        args = ['problem', 'solution'] if solution else []
        yield from run_and_parse([str(self.java_seed), *args])
