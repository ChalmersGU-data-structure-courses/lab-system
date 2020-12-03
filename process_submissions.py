import argparse
import logging
from pathlib import Path
import shlex

from general import print_error, print_json
from canvas import Canvas, GroupSet, Course
from lab_assignment import LabAssignment
import submission_fix_lib
import config

p = argparse.ArgumentParser(
    description = '\n'.join([
        'Process student submissions to an assignment on Canvas.',
        'This involves two stages, \'unpack\' and \'process\', that can be specified as arguments.',
        'The \'process\' stage caches its results; it can be called iteratively on the same submission working directory.'
    ])
)

p.add_argument('lab', type = int, choices = [1, 2, 3, 4], help = 'The lab to process.')
p.add_argument('dir', type = Path, help = '\n'.join([
    'The submission working directory.',
    'This is the base of the hierarchy in which the submissions are collected and processed.',
    'If it does not exist and the submission procession workflow includes unpacking, it will be created.',
    'This directory will be self-contained: it will contain lots of symlinks to reduce file duplication, but they will never point outside the directory.',
    'Thus, you can safely share the directory.'
]))
p.add_argument('--unpack', action = 'store_true', help = '\n'.join([
    'Collect the submissions and unpack them in the submission working directory.',
    'This will (re)create the submission working directory.',
    f'It will create subfolders for each lab group containing \'{LabAssignment.rel_dir_current}\' and \'{LabAssignment.rel_dir_previous}\' subdirectories for the submission of the respective kind.',
    f'It will also as create a \'{LabAssignment.rel_dir_build}\' subdirectory with the current submission overlayed on top of the problem files.',
    'If any submitted files have name not conforming to the expected solution files, an error is raised.',
    f'In that case, the user is provided with information on all such files and a skeleton with which to extend \'name_handlers\' in \'{submission_fix_lib.script_submission_fixes}\' in the lab directory (see documentation in that file).',
]))
p.add_argument('--process', action = 'store_true', help = '\n'.join([
    'Assuming the submissions have been unpacked, process them.',
    'This involves the following phases, in order: compilation, testing, pregrading, creating overview index.',
    'Unless changed using --allow-compilation-errors, the workflow will stop after the compilation stage if there where any errors.',
    'This is useful to detect fixable errors such as package declarations and non-existing imports.',
    'You should then extend \'content_handlers\' in \'{submission_fix_lib.script_submission_fixes}\' in the lab directory to persistently fix theses errors (see documentation in that file).',
    'The option --write-ids is useful here.',
    'Afterwards, you will need to run --unpack again for these fixes to take effect.',
    'In any case, the following phases run only for those lab groups passing compilation.'
    f'Testing uses the tests specified in \'{Path(LabAssignment.rel_dir_test) / LabAssignment.rel_file_tests}\' in the lab directory.',
    f'Pregrading links the java files in \'{Path(LabAssignment.rel_dir_test) / "tests_java"}\' into the build directory and gets its output from the main classes specified in \'{Path(LabAssignment.rel_dir_test) / LabAssignment.rel_file_tests_java}\'.',
    f'Both phases output files in the \'{LabAssignment.rel_dir_analysis}\' subdirectory of each lab group folder.',
    'Creation of the overview index outputs further such files and creates a top-level index file that provides an overview over the processed submissions.',
]))

p.add_argument('-v', '--verbose', action = 'store_true', help = '\n'.join([
    'Print INFO level logging.',
    'This includes accesses to Canvas API endpoints.',
]))
cache_dir_default = Path(__file__).parent / 'cache'
p.add_argument('--cache-dir', type = str, default = cache_dir_default, help = '\n'.join([
    'The cache directory to use.',
    'If it does not exist, it will be created.',
    f'This defaults to {format(shlex.quote(str(cache_dir_default)))}.',
]))
p.add_argument('--refresh-submissions', action = 'store_true', help = '\n'.join([
    'Collect submissions from Canvas instead of the cache.',
    'Use this at the beginning of a submission procession workflow to make sure the cached submissions are up to date.',
    'It is recommended to use this option only then for collecting the submission from Canvas is an expensive operation (on the order of 5 minutes).'
]))
p.add_argument('--refresh-group-set', action = 'store_true', help = '\n'.join([
    'Collect group membership information from Canvas instead of the cache.',
    'Use this at the beginning of a submission procession workflow to make sure the cached group memberships are up to date.',
    'Collecting group membership information from Canvas is an expensive operation (on the order of 1 minute).'
]))
p.add_argument('--deadline', type = int, choices = [0, 1, 2], help = '\n'.join([
    'Deadline to use for the overview index file.',
    f'These are specified in \'{LabAssignment.rel_file_deadlines}\' in the lab folder.',
    'If unspecified, information is late submissions will not be recorded in the overview file.'
]))
p.add_argument('--groups', nargs = '+', type = str, help = '\n'.join([
    'Restrict submission processing to these groups.',
    'If omitted, all currently ungraded submissions will be processed.',
]))
p.add_argument('--write-ids', action = 'store_true', help = '\n'.join([
    'Together with each submitted file \'<file>\' written in the \'{LabAssignment.rel_dir_current}\' and \'{LabAssignment.rel_dir_previous}\' subdirectories of each lab group, store a file \'.<file>\' containing its Canvas id.',
    'This can be used for easy Canvas id lookup when writing \'content_handlers\' to fix compilation errors.'
]))
p.add_argument('--allow-compilation-errors', action = 'store_true', help = '\n'.join([
    'Continue the submission procession workflow if there were errors in the compilation stage.',
    'Compilation errors will be listed in the overview document.',
]))
p.add_argument('--no-compilation', action = 'store_true', help = '\n'.join([
    'Skip the compilation phase of the submission procession workflow.',
]))
p.add_argument('--no-tests', action = 'store_true', help = '\n'.join([
    'Skip the testing phase of the submission procession workflow.',
]))
p.add_argument('--no-pregrading', action = 'store_true', help = '\n'.join([
    'Skip the pregrading phase of the submission procession workflow.',
]))
p.add_argument('--no-overview', action = 'store_true', help = '\n'.join([
    'Skip creaton of an overview index file at the end of the submission procession workflow.',
]))
p.add_argument('--remove-class-files', action = 'store_true', help = '\n'.join([
    'After finishing processing, remove all compiled java files from the submission working directory.',
    'Use this option if you plan to share this folder with people who may be running different versions of the Java Development Kit.',
]))
args = p.parse_args()

logging.basicConfig()
if args.verbose:
    logging.getLogger().setLevel(logging.INFO)
else:
    logging.getLogger().setLevel(25)

canvas = Canvas(config.canvas_url, cache_dir = Path(args.cache_dir))
group_set = GroupSet(canvas, config.course_id, config.group_set, use_cache = not args.refresh_group_set)
lab_assignment = LabAssignment(canvas, config.course_id, args.lab)
lab_assignment.collect_submissions(use_cache = not args.refresh_submissions)

extra = dict()
extra['dir'] = args.dir
if args.groups:
    extra['groups'] = args.groups

if args.unpack:
    lab_assignment.submissions_unpack(write_ids = args.write_ids, **extra)
    lab_assignment.submissions_prepare_build(**extra)

if args.process:
    if not args.no_compilation:
        lab_assignment.submissions_compile(strict = not(args.allow_compilation_errors), **extra)
    if not args.no_tests:
        lab_assignment.submissions_test(**extra)
    if not args.no_pregrading:
        lab_assignment.submissions_pregrade(strict = True, **extra)
    if args.remove_class_files:
        lab_assignment.submissions_remove_class_files(**extra)
    if not args.no_overview:
        lab_assignment.build_index(deadline = args.deadline, **extra)
