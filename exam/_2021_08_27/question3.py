import os
import pathlib
import random
import tempfile

def gen_tmp_file(suffix = None):
    (fd, name) = tempfile.mkstemp(suffix = suffix)
    os.close(fd)
    return pathlib.Path(name)    

class Generator:
    def __init__(self, seed, version):
        self.r = random.Random(seed)
        self.version = version

    def replacements_img(self, solution = False):
        path = gen_tmp_file(suffix = '.png')
        with tempfile.TemporaryDirectory() as dir:
            link = pathlib.Path(dir) / 'link'
            link.symlink_to(pathlib.Path(__file__).resolve() / 'question3' / f'BST-{self.version:0>2d}.png')
            link.rename(path)
        yield ('kix.c5e9tjg3u8t7', path)
