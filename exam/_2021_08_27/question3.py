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

def format_left(is_left):
    return 'left' if is_left else 'right'

def format_L(is_left):
    return 'L' if is_left else 'R'

def format_smaller(is_left):
    return 'smaller' if is_left else 'larger'

def format_smallest(is_left):
    return 'smallest' if is_left else 'largest'

def svg_template_initial_tree(is_left):
    return image_dir / f'BST-{format_left(is_left)}.svg'

def svg_template_inserted_tree(is_left):
    return image_dir / f'BST-{format_left(is_left)}-inserted.svg'

def svg_template_removed_tree(is_left, intended):
    suffix_intended = 'a' if intended else 'b'
    return image_dir / f'BST-{format_left(is_left)}-removed-{suffix_intended}.svg'

# svg_template is a function taking a boolean 'is_left' as argument and returning a path to the SVG file.
# The result is a string.
def instantiate_svg_template(svg_template, nodes, *params):
    return re.sub('##(\\d+)', lambda m: nodes[int(m.group(1))], svg_template(*params).read_text())

def png_from_svg(png_path, svg):
    with png_path.open('wb') as png_file:
        subprocess.run(
            ['rsvg-convert', '--zoom', str(2)],
            input = svg.encode(),
            stdout = png_file,
            check = True,
        )

def gen_png_from_svg_template(*args):
    png_path = gen_tmp_file(suffix = '.png')
    png_from_svg(png_path, instantiate_svg_template(*args))
    return png_path

class _Generator:
    def __init__(self, is_dit961, seed, version):
        self.is_dit961 = is_dit961

        self.r = random.Random(seed)
        self.is_left = self.r.choice([True, False])
        self.nodes = sorted(self.r.sample(string.ascii_uppercase, 9), reverse = not self.is_left)

    def replacements(self, solution = False):
        for (i, node) in enumerate(self.nodes):
            yield (str(i), node)

        if solution:
            for v in [True, False]:
                yield (format_left(v), format_left(v == self.is_left))
                yield (format_L(v), format_L(v == self.is_left))
                yield (format_smaller(v), format_smaller(v == self.is_left))
                yield (format_smallest(v), format_smallest(v == self.is_left))

    def replacements_img(self, solution = False):
        yield ('kix.bjfury1ntd88' if not self.is_dit961 else 'kix.j8188v64adk0', gen_png_from_svg_template(svg_template_initial_tree, self.nodes, self.is_left))

        if solution:
            yield ('kix.fb9j64evdz0y' if not self.is_dit961 else 'kix.9piqdo6kwqda', gen_png_from_svg_template(svg_template_inserted_tree, self.nodes, self.is_left))
            for v, id in [
                (True, 'kix.r7dc08ncuqle' if not self.is_dit961 else 'kix.af62clhvh9zy'),
                (False, 'kix.7d5i67igq28c' if not self.is_dit961 else 'kix.1anrg18eoi5'),
            ]:
                yield (id, gen_png_from_svg_template(svg_template_removed_tree, self.nodes, self.is_left, v))

def Generator(is_dit961 = False):
    def f(seed, version = None):
        return _Generator(is_dit961, seed, version)
    return f
