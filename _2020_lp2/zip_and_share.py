#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK

# We defer expensive initialization to after argument parsing is done.
# This makes bash completion more responsive.
import argparse
from pathlib import Path
import shlex


dir_script = Path(__file__).parent
cache_dir_default = dir_script / 'cache'
file_auth_token_default = dir_script / 'auth_token'

p = argparse.ArgumentParser(add_help = False, description = '''
Compress a directory for systems with/without symlink support and upload the result to Canvas.
    ''', epilog = '''
This Python script supports bash completion.
For this, python-argparse needs to be installed and configured.
See https://github.com/kislyuk/argcomplete for more information.
''')

g = p.add_argument_group('primary arguments')
g.add_argument('dir', type = Path, help = '''
The directory to compress and upload to Canvas.
The directory may only contain relative symlinks resolving within the directory.
''')
g.add_argument('--zip', action = 'store_true', help = '''
Zip the directory using xz in two different ways, one preserving symlinks and one resolving symlinks.
The zipped files have their named derived from the given directory and are stored in its parent directory
Pre-existing files of the same name are deleted
''')
g.add_argument('--share', action = 'store_true', help = '''
Upload the zipped files to Canvas.
''')

g = p.add_argument_group('secondary arguments')
g.add_argument('--canvas-dir', type = str, metavar = 'NAME', default = 'temp', help = '''
The Canvas folder to store the zipped files in.
Defaults to 'temp' in the course root directory.
''')
g.add_argument('--delete-zips', action = 'store_true', help = '''
Delete the zipped files after they have been uploaded to Canvas.
''')
g.add_argument('--no-symlink-zip', action = 'store_true', help = '''
Do not produce the zipped file with symlinks preserved.
''')
g.add_argument('--no-nonsymlink-zip', action = 'store_true', help = '''
Do not produce the zipped file with symlinks resolved.
''')
g.add_argument(
    '--compression',
    choices = list(map(str, range(0, 10))),
    metavar = '{0..9}',
    default = 0,
    help = '''
Compression level to use with xz
''')

g = p.add_argument_group('general arguments')
g.add_argument('-h', '--help', action = 'help', help = '''
Show this help message and exit.
''')
g.add_argument('-v', '--verbose', action = 'store_true', help = '''
Print INFO level logging.
This includes accesses to Canvas API endpoints.
''')
g.add_argument('--auth-file', type = str, metavar = 'AUTH', default = file_auth_token_default, help = f'''
Path to a file storing the Canvas authentication token.
Defaults to {shlex.quote(str(file_auth_token_default))}.
''')
g.add_argument('--cache-dir', type = str, metavar = 'CACHE', default = cache_dir_default, help = f'''
The cache directory to use.
If it does not exist, it will be created.
Defaults to {shlex.quote(str(cache_dir_default))}.
''')

#Support for argcomplete.
try:
    import argcomplete
    argcomplete.autocomplete(p)
except ModuleNotFoundError:
    pass

args = p.parse_args()
# Argument parsing is done: expensive initialization can start now.


from collections import namedtuple
import logging
import shutil

from util.general import print_error
from canvas import Canvas, Course

from . import compression
from . import config


logger = logging.getLogger(__name__)

# Handle verbosity.
logging.basicConfig()
if args.verbose:
    logging.getLogger().setLevel(logging.INFO)
else:
    logging.getLogger().setLevel(25)

# Check directory exists.
if not args.dir.is_dir():
    print_error('The given path {} is not a valid directory.'.format(shlex.quote(str(args.dir))))
    exit(1)

# Check for GNU tar.
tar = compression.find_gnu_tar()
if not tar:
    print_error('Cannot find GNU tar.')
    exit(1)
logger.log(logging.INFO, 'Found GNU tar: {}'.format(shlex.quote(tar)))

# Check that all the necessary programs are installed.
for program in ['xz']:
    if not shutil.which(program):
        print_error('Cannot find the program {}.'.format(shlex.quote(program)))
        exit(1)

canvas = Canvas(config.canvas_url, cache_dir = Path(args.cache_dir))
course = Course(canvas, config.course_id)

preserve_symlink_suffix = {
    True: '-symlinks',
    False: '',
}

Config = namedtuple('Config', field_names = ['compressor', 'suffix', 'preserve_symlinks', 'skip'])

configs = [
    Config(
        compressor = compression.get_xz(args.compression),
        suffix = '.txz',
        preserve_symlinks = True,
        skip = args.no_symlink_zip,
    ),
    Config(
        compressor = compression.get_xz(args.compression),
        suffix = '.txz',
        preserve_symlinks = False,
        skip = args.no_nonsymlink_zip
    ),
]
configs = list(filter(lambda config: not config.skip, configs))

def output(c):
    return args.dir.with_name(args.dir.name + preserve_symlink_suffix[c.preserve_symlinks] + c.suffix)

def output_quoted_name(c):
    return shlex.quote(str(output(c)))

if args.zip:
    print_error('Zipping...')

    for c in configs:
        if output(c).exists():
            print_error('Deleting pre-existing file {}.'.format(output_quoted_name(c)))
            output(c).unlink()

        print_error('Zipping file {}.'.format(output_quoted_name(c)))
        file_ignore = args.dir / ('.ignore' + preserve_symlink_suffix[c.preserve_symlinks])
        if not file_ignore.exists():
            print_error('Warning: file {} is missing.'.format(shlex.quote(str(file_ignore))))
            file_ignore = []

        compression.compress_dir(
            output(c),
            args.dir,
            exclude = file_ignore,
            move_up = True,
            sort_by_name = True,
            preserve_symlinks = c.preserve_symlinks,
            tar = tar,
            compressor = c.compressor,
        )

if args.share:
    print_error('Uploading...')

    # Sanity check.
    for c in configs:
        if not output(c).is_file():
            print_error('File {} is missing.'.format(output_quoted_name(c)))
            exit(1)

    folder_id = canvas.get_list(course.endpoint + ['folders', 'by_path', args.canvas_dir], use_cache = False)[-1].id

    for c in configs:
        print_error('Uploading file {}.'.format(output_quoted_name(c)))
        file_id = course.post_file(output(c), folder_id, output(c).name, locked = True, use_curl = True)
        if args.delete_zips:
            print_error('Deleting file {}.'.format(output_quoted_name(c)))
            output(c).unlink()

        print('{}: {}'.format(output_quoted_name(c), course.get_file_descr(file_id).url))
