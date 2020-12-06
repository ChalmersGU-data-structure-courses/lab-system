#!/usr/bin/env python
# PYTHON_ARGCOMPLETE_OK

# We defer expensive initialization to after argument parsing is done.
# This makes bash completion more responsive.
import argparse
from pathlib import Path
import shlex

import lab_assignment_constants

dir_script = Path(__file__).parent
path_extra = dir_script / 'node_modules' / '.bin'
cache_dir_default = dir_script / 'cache'
file_auth_token_default = dir_script / 'auth_token'

p = argparse.ArgumentParser(add_help = False, description = '\n'.join([
    f'Process student submissions to an assignment on Canvas.',
    f'This involves two stages, \'unpack\' and \'process\', that can be specified as arguments.',
    f'The \'process\' stage caches its results; it can be called iteratively on the same submission working directory with varying options.'
]), epilog = '\n'.join([
    f'This Python script supports bash completion.',
    f'For this, python-argparse needs to be installed and configured.',
    f'See https://github.com/kislyuk/argcomplete for more information.',
]))

g = p.add_argument_group('primary arguments')
g.add_argument('lab', type = int, choices = [1, 2, 3, 4], help = 'The lab to process.')
g.add_argument('dir', type = Path, help = '\n'.join([
    f'The submission working directory.',
    f'This is the base of the hierarchy in which the submissions are collected and processed.',
    f'If it does not exist and the submission processing workflow includes unpacking, it will be created.',
    f'This directory will be self-contained: it will contain lots of symlinks to reduce file duplication, but they will never point outside the directory.',
    f'Thus, you can safely share the directory with users whose filesystems support symlinks.',
    f'For the others, copy the directory with the option for resolving symlinks.'
]))
g.add_argument('--unpack', action = 'store_true', help = '\n'.join([
    f'Collect the submissions and unpack them in the submission working directory.',
    f'This will create the submission working directory if it did not exist.',
    f'It will (re)create subfolders for each lab group containing \'{lab_assignment_constants.rel_dir_current}\' and \'{lab_assignment_constants.rel_dir_previous}\' subdirectories for the submission of the respective kind.',
    f'It will also as create a \'{lab_assignment_constants.rel_dir_build}\' subdirectory with the current submission overlayed on top of the problem files.',
    f'If any submitted files have name not conforming to the expected solution files, an error is raised.',
    f'In that case, the user is provided with information on all such files and a skeleton with which to extend \'name_handlers\' in \'{lab_assignment_constants.rel_file_submission_fixes}\' in the lab directory (see documentation in that file).',
]))
g.add_argument('--process', action = 'store_true', help = '\n'.join([
    f'Assuming the submissions have been unpacked, process them.',
    f'This involves the following phases, in order: compilation, testing, pregrading, creating overview index.',
    f'Unless changed using --allow-compilation-errors, the workflow will stop after the compilation stage if there where any errors.',
    f'This is useful to detect fixable errors such as package declarations and non-existing imports.',
    f'You should then extend \'content_handlers\' in \'{lab_assignment_constants.rel_file_submission_fixes}\' in the lab directory to persistently fix theses errors (see documentation in that file).',
    f'The file ids can be found by inspecting the symlink targets.',
    f'Afterwards, you will need to run --unpack again for these fixes to take effect; to save time, restrict its effect via the --group option to those lab groups impacted by the new content handlers.',
    f'In any case, the following phases run only for those lab groups passing compilation.'
    f'Testing uses the tests specified in \'{Path(lab_assignment_constants.rel_dir_test) / lab_assignment_constants.rel_file_tests}\' in the lab directory.',
    f'It produces output files in the \'{lab_assignment_constants.rel_dir_build_test}\' subdirectory of each lab group folder.',
    f'Pregrading links the java files in \'{Path(lab_assignment_constants.rel_dir_test) / "tests_java"}\' into the build directory and gets its output from the main classes specified in \'{Path(lab_assignment_constants.rel_dir_test) / lab_assignment_constants.rel_file_tests_java}\'.',
    f'It produces a text file \'{lab_assignment_constants.rel_file_pregrading}\' in each lab group folder.',
    f'Creation of the overview index outputs files in the \'{lab_assignment_constants.rel_dir_analysis}\' subdirectory of each lab group folder and references these in a top-level file \'index.html\' that provides an overview over the processed submissions.',
    f'For this phase, the npm programs \'diff2html-cli\' and \'highlights\' need to be in PATH or {path_extra}.',
    f'If npm is installed, this may be achieved by executing \'npm install diff2html-cli highlights\' in the directory of this script.',
]))

g = p.add_argument_group('secondary arguments')
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
g.add_argument('--groups', nargs = '+', type = str, help = '\n'.join([
    f'Restrict submission processing to these groups.',
    f'If omitted, all currently ungraded submissions will be processed.',
]))

g = p.add_argument_group('unpacking options')
g.add_argument('--recreate-swd', action = 'store_true', help = '\n'.join([
    f'Recreate the entire submission wording directory.'
]))
g.add_argument('--refresh-group-set', action = 'store_true', help = '\n'.join([
    f'Collect group membership information from Canvas instead of the cache.',
    f'Use this at the beginning of a submission processing workflow to make sure the cached group memberships are up to date.',
    f'Collecting group membership information from Canvas is an expensive operation (on the order of 1 minute).'
]))
g.add_argument('--refresh-submissions', action = 'store_true', help = '\n'.join([
    f'Collect submissions from Canvas instead of the cache.',
    f'Use this at the beginning of a submission processing workflow to make sure the cached submissions are up to date.',
    f'It is recommended to use this option only then for collecting the submission from Canvas is an expensive operation (on the order of 5 minutes).'
]))
g.add_argument('--no-name-handlers', action = 'store_true', help = '\n'.join([
    f'Do not fix submitted file names using the name handlers in \'{lab_assignment_constants.rel_file_submission_fixes}\' in the lab directory.'
]))
g.add_argument('--no-content-handlers', action = 'store_true', help = '\n'.join([
    f'Do not fix submitted file contents using the content handlers in \'{lab_assignment_constants.rel_file_submission_fixes}\' in the lab directory.'
]))
# g.add_argument('--write-ids', action = 'store_true', help = '\n'.join([
#     f'Together with each submitted file \'<file>\' written in the \'{lab_assignment_constants.rel_dir_current}\' and \'{lab_assignment_constants.rel_dir_previous}\' subdirectories of each lab group, store its Canvas id in \'.<file>\'.',
#     f'This can be used for easy Canvas id lookup when writing \'content_handlers\' to fix compilation errors.'
# ]))

g = p.add_argument_group('compilation options')
g.add_argument('--no-compilation', action = 'store_true', help = '\n'.join([
    f'Skip the compilation phase of the submission processing workflow.',
]))
g.add_argument('--allow-compilation-errors', action = 'store_true', help = '\n'.join([
    f'Continue the submission processing workflow if there were errors in the compilation stage.',
    f'Compilation errors will be listed in the overview document.',
]))

g = p.add_argument_group('testing options')
g.add_argument('--no-testing', action = 'store_true', help = '\n'.join([
    f'Skip the testing phase of the submission processing workflow.',
]))

g = p.add_argument_group('pregrading options')
g.add_argument('--no-pregrading', action = 'store_true', help = '\n'.join([
    f'Skip the pregrading phase of the submission processing workflow.',
]))

g = p.add_argument_group('overview options')
g.add_argument('--remove-class-files', action = 'store_true', help = '\n'.join([
    f'After finishing processing, remove all compiled java files from the submission working directory.',
    f'Use this option if you plan to share this folder with people who may be running different versions of the Java Development Kit.',
]))
g.add_argument('--no-overview', action = 'store_true', help = '\n'.join([
    f'Skip creation of an overview index file at the end of the submission processing workflow.',
]))
g.add_argument('--deadline', type = int, choices = [0, 1, 2], help = '\n'.join([
    f'Optional deadline to use for recording of late submissions in the overview index file.',
    f'These are specified in \'{lab_assignment_constants.rel_file_deadlines}\' in the lab folder.',
]))
g.add_argument('--no-preview', action = 'store_true', help = '\n'.join([
    f'After finishing processing, do not open the overview index file in a webbrowser tab.'
]))

#Support for argcomplete.
try:
    import argcomplete
    argcomplete.autocomplete(p)
except ModuleNotFoundError:
    pass

args = p.parse_args()
# Argument parsing is done: expensive initialization can start now.

import logging
import os
import shutil

from general import print_error, add_to_path, join_lines
from canvas import Canvas, GroupSet, Course
from lab_assignment import LabAssignment
import config

if not (args.unpack or args.dir.exists()):
    print_error('The submission working directory {} does not exist (and no --unpack option given).'.format(shlex.quote(str(args.dir))))
    exit(1)

add_to_path(path_extra)

# Check that all the necessary programs are installed.
if args.process and not args.no_overview and not (shutil.which('diff2html') and shutil.which('highlights')):
    print_error('Cannot find \'diff2html\' and \'highlights\'.')
    print_error('They are needed for producing the overview file.')
    print_error('To fix, make sure npm is installed and run \'npm install diff2html-cli highlights\' in the directory of this script.')
    exit(1)
if args.process and (not args.no_overview) and not (shutil.which('diff')):
    print_error('Cannot find \'diff\'.')
    print_error('It is needed for producing the overview file.')
    print_error('To fix, make sure diffutils is installed.')
    exit(1)
if args.process and (not args.no_compilation) and not (shutil.which('javac')):
    print_error('Cannot find \'javac\'.')
    print_error('It is needed for compilation.')
    print_error('To fix, make sure a Java Development Kit (JDK) is installed.')
    exit(1)
if args.process and (not args.no_testing or not args.no_pregrading) and not (shutil.which('java')):
    print_error('Cannot find \'java\'.')
    print_error('It is needed for testing and pregrading.')
    print_error('To fix, make sure a Java Development Kit (JDK) is installed.')
    exit(1)

logging.basicConfig()
if args.verbose:
    logging.getLogger().setLevel(logging.INFO)
else:
    logging.getLogger().setLevel(25)

canvas = Canvas(config.canvas_url, cache_dir = Path(args.cache_dir))
group_set = GroupSet(canvas, config.course_id, config.group_set, use_cache = not args.refresh_group_set)
lab_assignment = LabAssignment(canvas, config.course_id, args.lab, use_name_handlers = not args.no_name_handlers, use_content_handlers = not args.no_content_handlers)
lab_assignment.collect_submissions(use_cache = not args.refresh_submissions)

extra = dict()
extra['dir'] = args.dir
extra['groups'] = lab_assignment.parse_groups(args.groups) if args.groups else lab_assignment.get_ungraded_submissions()

if args.unpack:
    if args.recreate_swd and args.dir.exists():
        shutil.rmtree(args.dir)
    lab_assignment.submissions_unpack(write_ids = args.write_ids, **extra)
    lab_assignment.submissions_prepare_build(**extra)

if args.process:
    if not args.no_compilation:
        lab_assignment.submissions_compile(strict = not(args.allow_compilation_errors), **extra)
    if not args.no_testing:
        lab_assignment.submissions_test(**extra)
    if not args.no_pregrading:
        lab_assignment.submissions_pregrade(strict = True, **extra)
    if args.remove_class_files:
        lab_assignment.submissions_remove_class_files(**extra)
    if not args.no_overview:
        lab_assignment.build_index(deadline = args.deadline, preview = not(args.no_preview), **extra)

    file_ignore = '.ignore'
    file_ignore_no_symlinks = '.ignore_no_symlinks'
    ignore = [file_ignore, file_ignore_no_symlinks]
    (args.dir / file_ignore).write_text(join_lines(ignore + ['*.class']))
    (args.dir / file_ignore_no_symlinks).write_text(join_lines(ignore + ['*.class', '/files']))
