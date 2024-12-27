#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK

# We defer expensive initialization to after argument parsing is done.
# This makes bash completion more responsive.
import argparse
from pathlib import Path
import shlex

from . import lab_assignment_constants


dir_script = Path(__file__).parent
path_extra = dir_script / 'node_modules' / '.bin'
cache_dir_default = dir_script / 'cache'
file_auth_token_default = dir_script / 'auth_token'

p = argparse.ArgumentParser(add_help = False, description = '''
Process student submissions to an assignment on Canvas.
This involves two stages, 'unpack' and 'process', that can be specified as arguments.
The 'process' stage caches its results; it can be called iteratively on the same submission working director'.
    ''', epilog = '''
This Python script supports bash completion.
For this, python-argparse needs to be installed and configured.
See https://github.com/kislyuk/argcomplete for more information.
''')

g = p.add_argument_group('primary arguments')
g.add_argument('lab', type = int, choices = [1, 2, 3, 4], metavar = 'LAB', help = '''
The lab to process.
''')
g.add_argument('dir', type = Path, metavar = 'SUB_WORKING_DIR', help = '''
The submission working directory.
This is the base of the hierarchy in which the submissions are collected and processed.
If it does not exist and the submission processing workflow includes unpacking, it will be created.
This directory will be self-contained: it will contain lots of symlinks to reduce file duplication, but they will never point outside the directory.
Thus, you can safely share the directory with users whose filesystems support symlinks.
For the others, copy the directory with the option for resolving symlinks
''')  # noqa: E501
g.add_argument('--unpack', action = 'store_true', help = f'''
Collect the submissions and unpack them in the submission working directory.
This will create the submission working directory if it did not exist.
It will (re)create subfolders for each lab group containing '{lab_assignment_constants.rel_dir_current}' and '{lab_assignment_constants.rel_dir_previous}' subdirectories for the submission of the respective kind.
It will also as create a '{lab_assignment_constants.rel_dir_build}' subdirectory with the current submission overlayed on top of the problem files.
If any submitted files have name not conforming to the expected solution files, an error is raised.
In that case, the user is provided with information on all such files and a skeleton with which to extend 'name_handlers' in '{lab_assignment_constants.rel_file_submission_fixes}' in the lab directory (see documentation in that file).
''')  # noqa: E501
g.add_argument('--process', action = 'store_true', help = '''
Assuming the submissions have been unpacked, process them.
This involves the following phases, in order: compilation, testing, robograding, creating overview index.
Unless changed using --allow-compilation-errors, the workflow will stop after the compilation stage if there where any errors.
This is useful to detect fixable errors such as package declarations and non-existing imports.
You should then extend 'content_handlers' in '{lab_assignment_constants.rel_file_submission_fixes}' in the lab directory to persistently fix theses errors (see documentation in that file).
The file ids can be found by inspecting the symlink targets.
Afterwards, you will need to run --unpack again for these fixes to take effect; to save time, restrict its effect via the --group option to those lab groups impacted by the new content handlers.
In any case, the following phases run only for those lab groups passing compilation
Testing uses the tests specified in '{Path(lab_assignment_constants.rel_dir_test) / lab_assignment_constants.rel_file_tests}' in the lab directory.
It produces output files in the '{lab_assignment_constants.rel_dir_build_test}' subdirectory of each lab group folder.
Robograding copies the java files in '{Path(lab_assignment_constants.rel_dir_robograder)}' into the submission working directory, compiles them with the model solution, and runs them with each lab group submission.
The executed Java classes are specified specified in '{Path(lab_assignment_constants.rel_dir_robograder) / lab_assignment_constants.rel_file_robograders}'.
On successful execution, it produces a text file '{lab_assignment_constants.rel_file_robograding}' in each lab group folder.
On failure, it instead produces a text file '{lab_assignment_constants.rel_file_robograding_errors}'.
Creation of the overview index outputs files in the '{lab_assignment_constants.rel_dir_analysis}' subdirectory of each lab group folder and references these in a top-level file 'index.html' that provides an overview over the processed submissions.
For this phase, the npm programs 'diff2html-cli' and 'highlights' need to be in PATH or {path_extra}.
If npm is installed, this may be achieved by executing 'npm install diff2html-cli highlights' in the directory of this script.
''')  # noqa: E501

g = p.add_argument_group('secondary arguments')
g.add_argument('-h', '--help', action = 'help', help = '''
Show this help message and exit.
''')
g.add_argument('-v', '--verbose', action = 'count', default = 0, help = '''
Print INFO level logging (once specified) or DEBUG level logging (twice specified).
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
g.add_argument('--groups', nargs = '*', type = str, metavar = 'GROUP', help = '''
Restrict submission processing to these groups.
If omitted, all currently ungraded submissions will be processed.
''')

g = p.add_argument_group('unpacking options')
g.add_argument('--recreate-swd', action = 'store_true', help = '''
Recreate the entire submission wording directory.
''')
g.add_argument('--refresh-group-set', action = 'store_true', help = '''
Collect group membership information from Canvas instead of the cache.
Use this at the beginning of a submission processing workflow to make sure the cached group memberships are up to date.
Collecting group membership information from Canvas is an expensive operation (on the order of 1 minute)
''')
g.add_argument('--refresh-submissions', action = 'store_true', help = '''
Collect submissions from Canvas instead of the cache.
Use this at the beginning of a submission processing workflow to make sure the cached submissions are up to date.
It is recommended to use this option only then for fetching the submission info from Canvas is an expensive operation (on the order of 30 seconds)
''')  # noqa: E501
g.add_argument('--no-name-handlers', action = 'store_true', help = f'''
Do not fix submitted file names using the name handlers in '{lab_assignment_constants.rel_file_submission_fixes}' in the lab directory
''')  # noqa: E501
g.add_argument('--no-content-handlers', action = 'store_true', help = f'''
Do not fix submitted file contents using the content handlers in '{lab_assignment_constants.rel_file_submission_fixes}' in the lab directory
''')  # noqa: E501

help = f'''
Together with each submitted file '<file>' written in the '{lab_assignment_constants.rel_dir_current}' and '{lab_assignment_constants.rel_dir_previous}' subdirectories of each lab group, store its Canvas id in '.<file>'.
This can be used for easy Canvas id lookup when writing 'content_handlers' to fix compilation errors
'''  # noqa: E501
#g.add_argument('--write-ids', action = 'store_true', help = help)

g = p.add_argument_group('compilation options')
g.add_argument('--no-compilation', action = 'store_true', help = '''
Skip the compilation phase of the submission processing workflow.
''')
g.add_argument('--allow-compilation-errors', action = 'store_true', help = '''
Continue the submission processing workflow if there were errors in the compilation stage.
Compilation errors will be listed in the overview document.
''')

g = p.add_argument_group('testing options')
g.add_argument('--no-testing', action = 'store_true', help = '''
Skip the testing phase of the submission processing workflow.
''')
g.add_argument('--machine-speed', type = float, metavar = 'SPD', default = 1, help = '''
Machine speed relative to which to interpret timeout values.
Defaults to 1.
''')

g = p.add_argument_group('robograding options')
g.add_argument('--no-robograding', action = 'store_true', help = '''
Skip the robograding phase of the submission processing workflow.
''')
g.add_argument('--robograde-model-solution', action = 'store_true', help = '''
Robograde also the model solution.
''')

g = p.add_argument_group('overview options')
g.add_argument('--remove-class-files', action = 'store_true', help = '''
After finishing processing, remove all compiled java files from the submission working directory.
Use this option if you plan to share this folder with people who may be running different versions of the Java Development Kit.
''')  # noqa: E501
g.add_argument('--no-overview', action = 'store_true', help = '''
Skip creation of an overview index file at the end of the submission processing workflow.
''')
g.add_argument('--deadline', type = int, choices = [0, 1, 2], help = f'''
Optional deadline to use for recording of late submissions in the overview index file.
These are specified in '{lab_assignment_constants.rel_file_deadlines}' in the lab folder.
''')
g.add_argument('--no-preview', action = 'store_true', help = '''
After finishing processing, do not open the overview index file in a webbrowser tab.
''')

#Support for argcomplete.
try:
    import argcomplete
    argcomplete.autocomplete(p)
except ModuleNotFoundError:
    pass

args = p.parse_args()
# Argument parsing is done: expensive initialization can start now.


import logging
import shutil

from util.general import print_error, join_lines
from canvas import Canvas, Course
from util.path import system_path_add

from . import config
from .lab_assignment import LabAssignment


if not (args.unpack or args.dir.exists()):
    print_error(
        f'The submission working directory {format(shlex.quote(str(args.dir)))} '
        'does not exist (and no --unpack option given).'
    )
    exit(1)

system_path_add(path_extra)

# Check that all the necessary programs are installed.
if args.process and not args.no_overview and not (shutil.which('diff2html') and shutil.which('highlights')):
    print_error('''
Cannot find 'diff2html' and 'highlights'.
They are needed for producing the overview file.
To fix, make sure npm is installed and run 'npm install diff2html-cli highlights' in the directory of this script.
    '''.strip())
    exit(1)
if args.process and (not args.no_overview) and not (shutil.which('diff')):
    print_error('''
Cannot find 'diff'.
It is needed for producing the overview file.
To fix, make sure diffutils is installed.
    '''.strip())
    exit(1)
if args.process and (not args.no_compilation) and not (shutil.which('javac')):
    print_error('''
Cannot find 'javac'.
It is needed for compilation.
To fix, make sure a Java Development Kit (JDK) is installed.
    '''.strip())
    exit(1)
if args.process and (not args.no_testing or not args.no_robograding) and not (shutil.which('java')):
    print_error('''
Cannot find 'java'.
It is needed for testing and robograding.
To fix, make sure a Java Development Kit (JDK) is installed.
    '''.strip())
    exit(1)

logging.basicConfig()
logging.getLogger().setLevel(25 if args.verbose == 0 else logging.INFO if args.verbose == 1 else logging.DEBUG)

canvas = Canvas(config.canvas_url, cache_dir = Path(args.cache_dir))
course = Course(canvas, config.course_id, use_cache = not args.refresh_group_set)
lab_assignment = LabAssignment(
    course,
    args.lab,
    use_name_handlers = not args.no_name_handlers,
    use_content_handlers = not args.no_content_handlers,
    use_cache = not args.refresh_group_set
)
lab_assignment.collect_submissions(use_cache = not args.refresh_submissions)

extra = dict()
extra['dir'] = args.dir
extra['groups'] = (
    lab_assignment.get_ungraded_submissions()
    if args.groups is None else
    lab_assignment.parse_groups(args.groups)
)

root = Path('/')

if args.unpack:
    if args.recreate_swd and args.dir.exists():
        shutil.rmtree(args.dir)
    lab_assignment.submissions_unpack(**extra)
    lab_assignment.submissions_prepare_build(**extra)

    def write_ignore_file(name, paths):
        (args.dir / name).write_text(join_lines(map(str, paths)))

    file_ignore = '.ignore'
    file_ignore_symlinks = '.ignore-symlinks'
    ignore = list(map(lambda path: root / path, [file_ignore, file_ignore_symlinks])) + [Path('*.class')]
    write_ignore_file(file_ignore_symlinks, ignore)
    write_ignore_file(file_ignore, ignore + [root / lab_assignment_constants.rel_dir_files])

if args.process:
    if not args.no_compilation:
        lab_assignment.submissions_compile(strict = not(args.allow_compilation_errors), **extra)
    if not args.no_testing:
        lab_assignment.submissions_test(**extra, machine_speed = args.machine_speed)
    if not args.no_robograding:
        lab_assignment.submissions_robograde(**extra, robograde_model_solution = args.robograde_model_solution)
    if args.remove_class_files:
        lab_assignment.submissions_remove_class_files(**extra)
    if not args.no_overview:
        lab_assignment.build_index(deadline = args.deadline, preview = not(args.no_preview), **extra)
