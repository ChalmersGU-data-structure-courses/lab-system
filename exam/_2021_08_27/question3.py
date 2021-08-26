import os
import pathlib
import random
import re
import string
import subprocess
import tempfile

image_dir = pathlib.Path(__file__).parent / 'question3'

def gen_tmp_file(suffix = None):
    (fd, name) = tempfile.mkstemp(suffix = suffix)
    os.close(fd)
    return pathlib.Path(name)    

def format_direction(is_left):
    return 'left' if is_left else 'right'

def svg_template_initial_tree(is_left):
    return image_dir / f'BST-{format_direction(is_left)}.svg'

# svg_template is a function taking a boolean 'is_left' as argument and returning a path to the SVG file.
# The result is a string.
def instantiate_svg_template(svg_template, is_left, nodes):
    return re.sub('##(\\d+)', lambda m: nodes[int(m.group(1))], svg_template(is_left).read_text())

def png_from_svg(png_path, svg):
    with png_path.open('wb') as png_file:
        subprocess.run(
            ['rsvg-convert', '--zoom', str(2)],
            input = svg.encode(),
            stdout = png_file,
            check = True,
        )

def png_from_svg_template(png_path, *args):
    x = instantiate_svg_template(*args)
    png_from_svg(png_path, x)

class _Generator:
    def __init__(self, placeholder_id, seed, version):
        self.placeholder_id = placeholder_id

        self.r = random.Random(seed)
        self.is_left = self.r.choice([True, False])
        self.nodes = sorted(self.r.sample(string.ascii_uppercase, 9), reverse = not self.is_left)
        self.params = [self.is_left, self.nodes]

    def replacements(self, solution = False):
        yield ('insert', self.nodes[5])
        yield ('remove', self.nodes[6])

    def replacements_img(self, solution = False):
        path = gen_tmp_file(suffix = '.png')
        png_from_svg_template(path, svg_template_initial_tree, *self.params)
        yield (self.placeholder_id, path)

def Generator(placeholder_id):
    def f(seed, version = None):
        return _Generator(placeholder_id, seed, version)
    return f
