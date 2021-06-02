import java
from pathlib import Path
import random
import subprocess

this_dir = Path(__file__).parent

class Generator:
    def __init__(self, seed):
        r = random.Random(seed)
        java_seed = r.randrange(1000000)
        name = 'HashTables20210603'
        java.compile_java([this_dir / (name + '.java')])
        cmd = list(java.java_cmd(name, [str(java_seed)]))
        self.output = subprocess.run(cmd, check = True, capture_output = True, encoding = 'utf-8', cwd = this_dir).stdout

    def replacements(self, solution = False):
        for line in self.output.splitlines():
            a = line.split('=')
            if len(a) == 2:
                yield(a[0], a[1])
