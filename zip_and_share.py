#!/usr/bin/env python
# PYTHON_ARGCOMPLETE_OK

# We defer expensive initialization to after argument parsing is done.
# This makes bash completion more responsive.
import argparse
from pathlib import Path
import shlex

import lab_assignment_constants

dir_script = Path(__file__).parent
cache_dir_default = dir_script / 'cache'
file_auth_token_default = dir_script / 'auth_token'

p = argparse.ArgumentParser(add_help = False, description = '\n'.join([
    f'Zip a directory in several ways and upload the result to Canvas.',
    f'The directory may contain relative symlinks resolving within the directory.',
]), epilog = '\n'.join([
    f'This Python script supports bash completion.',
    f'For this, python-argparse needs to be installed and configured.',
    f'See https://github.com/kislyuk/argcomplete for more information.',
]))

g = p.add_argument_group('primary arguments')
g.add_argument('dir', type = Path, help = '\n'.join([
    f'The directory to zip and upload to Canvas.',
]))
g.add_argument('--zip', action = 'store_true', help = '\n'.join([
    f'Zip the directory in two different ways.',
    f'One using zip, preserving the symlinks.',
    f'One using 7z (with large dictionary size) with symlinks resolved.',
    f'The zip files have their named derived from the given directory and are stored in its parent directory.'
    f'Pre-existing zip files of the same name are deleted.'
]))
g.add_argument('--share', action = 'store_true', help = '\n'.join([
    f'Upload the zip files to Canvas.',
]))

g = p.add_argument_group('secondary arguments')
g.add_argument('--canvas-folder', type = str, default = 'temp', help = '\n'.join([
    f'The Canvas folder to store the zip files in.'
    f'Defaults to \'temp\' in the course root directory.',
]))
g.add_argument('--delete-zips', action = 'store_true', help = '\n'.join([
    f'Delete the produced zip files after they have been uploaded to Canvas.',
]))

g = p.add_argument_group('general arguments')
g.add_argument('-h', '--help', action = 'help', help = '\n'.join([
    f'Show this help message and exit.',
]))
g.add_argument('-v', '--verbose', action = 'store_true', help = '\n'.join([
    f'Print INFO level logging.',
    f'This includes accesses to Canvas API endpoints.',
]))
g.add_argument('--auth-token-file', type = str, default = file_auth_token_default, help = '\n'.join([
    f'Path to a file storing the Canvas authentication token.',
    f'Defaults to {shlex.quote(str(file_auth_token_default))}.',
]))
g.add_argument('--cache-dir', type = str, default = cache_dir_default, help = '\n'.join([
    f'The cache directory to use.',
    f'If it does not exist, it will be created.',
    f'Defaults to {shlex.quote(str(cache_dir_default))}.',
]))

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
import os
import shutil
import subprocess

from general import print_error, add_to_path
from canvas import Canvas, GroupSet, Course
import compression
import config
from lab_assignment import LabAssignment

# Check directory exists.
if not args.dir.is_dir():
    print_error('The given path {} is not a valid directory.'.format(shlex.quote(str(args.dir))))
    exit(1)

# Check that all the necessary programs are installed.
if not shutil.which('zip'):
    print_error('Cannot find \'zip\'.')
    exit(1)
if not shutil.which('7z'):
    print_error('Cannot find \'zip\'.')
    exit(1)

# Handle verbosity.
logging.basicConfig()
if args.verbose:
    logging.getLogger().setLevel(logging.INFO)
else:
    logging.getLogger().setLevel(25)

canvas = Canvas(config.canvas_url, cache_dir = Path(args.cache_dir))
course = Course(canvas, config.course_id)

root = Path('/')

# Does not compress well with 'preverse_symlinks = False'.
def cmd_zip(output, paths, preserve_symlinks = False, ignore = []):
    return ['zip'] + (['--symlinks'] if preverse_symlinks else []) + ['-r', str(output), '--'] + list(map(str, paths))

def cmd_7z(output, paths, preserve_symlinks = True, ignore = []):
    format_ignore = lambda path: '-x' + ('' if path.is_absolute() else 'r') + '!' + str(path.relative_to(root) if path.is_absolute() else path)
    return ['7z', 'a'] + ([] if preserve_symlinks else ['-l', '-md=26']) + list(map(format_ignore, ignore)) + [str(output), '--'] + list(map(str, paths))

zippers = {
    'zip': cmd_zip,
    '7z': cmd_7z,
}

preserve_symlink_suffix = {
    True: '-symlinks',
    False: '',
}

Config = namedtuple('Config', field_names = ['compressor', 'suffix', 'preserve_symlinks'])

configs = [
    Config(compressor = compression.xz, suffix = '.txz', preserve_symlinks = True),
    Config(compressor = compression.xz, suffix = '.txz', preserve_symlinks = False),
]

def output(c):
    return args.dir.with_name(args.dir.name + preserve_symlink_suffix[c.preserve_symlinks] + c.suffix)

def output_quoted_name(c):
    return shlex.quote(str(output(c)))

if args.zip:
    print_error('Zipping...')
    for c in configs:
        if output(c).exists():
            print_error('Deleting pre-existing zip file {}.'.format(output_quoted_name(c)))
            output(c).unlink()

        compression.compress_dir(
            output(c),
            args.dir,
            exclude = args.dir / ('.ignore' + preserve_symlink_suffix[c.preserve_symlinks]),
            move_up = True,
            sort_by_name = True,
            preserve_symlinks = c.preserve_symlinks,
            compressor = c.compressor)

if args.share:
    # Sanity check.
    for c in configs:
        if not output(c).is_file():
            print_error('The zip file {} is missing.'.format(output_quoted_name(c)))
            exit(1)

    folder_id = canvas.get_list(course.endpoint + ['folders', 'by_path', args.canvas_folder], use_cache = False)[-1].id
 
    for c in configs:
        print_error('Uploading {}.'.format(output_quoted_name(c)))
        file_id = course.post_file(output(c), folder_id, output(c).name, locked = True, use_curl = True)
        if args.delete_zips:
            print_error('Deleting zip file {}.'.format(output_quoted_name(c)))
            output(c).unlink()
