import os
import pathlib
import random
import re
import tempfile

def shuffled(r, xs):
    ys = list(xs)
    r.shuffle(ys)
    return ys

def gen_tmp_file(suffix = None):
    (fd, name) = tempfile.mkstemp(suffix = suffix)
    os.close(fd)
    return pathlib.Path(name)    

class Generator:
    def __init__(self, seed, version):
        self.version = version

        self.image_dir = pathlib.Path(__file__).parent / 'question3'
        self.image_pattern = 'BST-(\\d+).png'
        
        def f():
            for path in self.image_dir.iterdir():
                m = re.fullmatch(self.image_pattern, path.name)
                if m:
                    yield (int(m.group(1)), path)
        self.versions = dict(f())
        assert sorted(self.versions.keys()) == list(range(len(self.versions)))

        self.version_order = shuffled(random.Random('half-empty bottle'), self.versions.keys())
        self.version_shuffled = self.version_order[self.version]

    def replacements_img(self, solution = False):
        path = gen_tmp_file(suffix = '.png')
        with tempfile.TemporaryDirectory() as dir:
            link = pathlib.Path(dir) / 'link'
            link.symlink_to(self.versions[self.version_shuffled].resolve())
            link.rename(path)
        yield ('kix.c5e9tjg3u8t7', path)

g = Generator(0, 3)
