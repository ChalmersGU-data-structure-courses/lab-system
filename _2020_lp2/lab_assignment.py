from collections import namedtuple, OrderedDict
from datetime import datetime, timedelta
import itertools
import json
import logging
import os.path
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import webbrowser

from dominate import document
from dominate.tags import (
    meta, link, title, script, style, h1, h2, div, pre, p,
    span, del_, button, table, thead, tbody, th, tr, td, a,
)
from dominate.util import raw, text

from util.general import (
    from_singleton, ilen, Timer, print_error,
    format_with_rel_prec, format_timespan,
)
from canvas import Assignment
from util.path import (
    add_suffix,
    modify, get_modification_time,
    sorted_directory_list,
    mkdir_fresh, link_dir_contents, copy_tree_fresh,
)

from . import lab_assignment_constants
from . import submission_fix_lib
from . import test_lib


logger = logging.getLogger(__name__)

def java_string_encode(x):
    return json.dumps(x)

def get_java_version():
    p = subprocess.run(
        ['java', '-version'],
        stdin = subprocess.DEVNULL,
        stdout = subprocess.DEVNULL,
        stderr = subprocess.PIPE,
        encoding = 'utf-8',
        check = True
    )
    v = shlex.split(str(p.stderr).splitlines()[0])
    assert(v[1] == 'version')
    return [int(x) for x in v[2].split('.')]

def diff_cmd(file_0, file_1):
    return [
        'diff',
        '--text', '--ignore-blank-lines', '--ignore-space-change', '--strip-trailing-cr',
        '-U', '1000000',
        '--',
        file_0, file_1,
    ]

def diff2html_cmd(file_input, file_output, highlight):
    return [
        'diff2html',
        '--style', 'side',
        '--highlightCode', str(bool(highlight)).lower(),
        '--input', 'file',
        '--file', file_output,
        '--',
        file_input,
    ]

def diff_similarity(root, rel_file_0, rel_file_1, file_diff):
    with file_diff.open('wb') as out:
        cmd = diff_cmd(rel_file_0, rel_file_1)
        process = subprocess.run(cmd, cwd = root, stdout = out)
        assert(process.returncode in [0, 1])

    if process.returncode == 0:
        return 1

    diff_lines = file_diff.read_text().splitlines()

    # remove diff header
    header_len = 3
    assert(len(diff_lines) >= header_len)
    diff_lines = diff_lines[header_len:]

    return sum(not any([line.startswith(c) for c in ['+', '-']]) for line in diff_lines) / len(diff_lines)

def highlights_cmd(file_input):
    return ['highlights', file_input]

def highlight_file(dir_source, dir_target, name, css):
    cmd = highlights_cmd(dir_source / name)
    process = subprocess.run(cmd, check = True, stdout = subprocess.PIPE, encoding = 'utf-8')
    doc = document(title = name)
    with doc.head:
        meta(charset = 'utf-8')
        link(rel = 'stylesheet', href = css)
    with doc.body:
        raw(process.stdout)
    result_name = name + '.html'
    (dir_target / result_name).write_text(doc.render())
    return result_name

def as_iterable_of_strings(xs):
    return [str(xs)] if isinstance(xs, str) or not hasattr(xs, '__iter__') else [str(x) for x in xs]

def add_classpath(classpath):
    if classpath is not None:
        yield from ['-classpath', ':'.join(as_iterable_of_strings(classpath))]

def javac_cmd(files = None, destination = None, classpath = None, options = None):
    yield 'javac'
    if destination is not None:
        yield from ['-d', str(destination)]
    yield from add_classpath(classpath)
    if options is not None:
        for option in options:
            yield str(option)
    if files is not None:
        for file in files:
            yield str(file)

def java_cmd(name, args = [], classpath = None, security_policy = None, enable_assertions = False, options = None):
    yield 'java'
    if security_policy:
        yield ''.join(['-D', 'java.security.manager'])
        yield ''.join(['-D', 'java.security.policy', '==', str(security_policy)])
    if enable_assertions:
        yield '-ea'
    yield from add_classpath(classpath)
    if options is not None:
        for option in options:
            yield str(option)
    yield name
    yield from args

# Apparently, '-g' is needed to make sure exceptions properly reference names in some circumstances.
javac_options = ['-g']

def java_options(version):
    if version[0] >= 14:
        yield ''.join(['-XX', ':', '+', 'ShowCodeDetailsInExceptionMessages'])

def log_command(cmd, working_dir = None):
    logger.debug('running command{}:\n{}'.format(
        '' if working_dir is None else ' in {}'.format(shlex.quote(str(working_dir))),
        shlex.join(cmd)
    ))

# Unless forced, only recompiles if necessary: missing or outdated class-files.
# On success, returns None.
# On failure, returns compile errors as string.
def compile_java(files, force_recompile = False, strict = False, working_dir = None, **kwargs):
    def is_up_to_date(file_java):
        path_java = (working_dir if working_dir else Path()) / file_java
        path_class = path_java.with_suffix('.class')
        return path_class.exists() and os.path.getmtime(path_class) > get_modification_time(path_java)

    if force_recompile:
        recompile = True
    elif not all(map(is_up_to_date, files)):
        logger.debug('Not all class files existing or up to date; (re)compiling.')
        recompile = True
    else:
        recompile = False

    if recompile:
        cmd = list(javac_cmd(files, **kwargs))
        log_command(cmd, working_dir)
        process = subprocess.run(cmd, cwd = working_dir, stderr = subprocess.PIPE, encoding = 'utf-8')
        if process.returncode != 0:
            print_error('Encountered compilation errors in {}:'.format(shlex.quote(str(working_dir))))
            print_error(process.stderr)
            assert(not strict)
            return process.stderr
    return None

def policy_permission(type, args = []):
    return 'permission {};'.format(
        ' '.join([type] + ([', '.join(java_string_encode(str(arg)) for arg in args)] if args else []))
    )

permission_all = ('java.security.AllPermission', [])

def permission_file_descendants_read(dir):
    return ('java.io.FilePermission', [Path(dir) / '-', 'read'])

def policy_grant(path, permissions):
    return '\n'.join([
        ' '.join(['grant'] + ([] if path is None else ['codeBase', java_string_encode('file:' + str(path))])) + ' {',
        *('  ' + policy_permission(*permission) for permission in permissions),
        '};',
        ''
    ])

def policy(entries):
    return '\n'.join(policy_grant(*entry) for entry in entries)

def format_file(root, name, rel_dir, rel_dir_formatting, rel_css):
    (root / rel_dir_formatting).mkdir(exist_ok = True)
    cell = td()
    if (root / rel_dir / name).exists():
        result_name = highlight_file(
            root / rel_dir,
            root / rel_dir_formatting,
            name,
            os.path.relpath(rel_css, rel_dir_formatting),
        )
        with cell:
            a(name, href = rel_dir_formatting / result_name)
    else:
        with cell:
            del_(name, Class = 'error')
    return cell

code_suffices = ['.java']

def format_diff(root, name, rel_dir_0, rel_dir_1, rel_dir_formatting, diff_title):
    (root / rel_dir_formatting).mkdir(exist_ok = True)
    rel_file_0 = rel_dir_0 / name
    rel_file_1 = rel_dir_1 / name
    file_0 = root / rel_file_0
    file_1 = root / rel_file_1
    cell = td()
    if not file_0.is_file() and not file_1.is_file():
        cell.add(span('nothing', Class = 'error'))
    elif not file_1.is_file():
        cell.add(span('missing', Class = 'error'))
    elif not file_0.is_file():
        cell.add(span('extra', Class = 'error'))
    else:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            file_diff = tmp_dir / 'diff'
            similarity = diff_similarity(root, rel_file_0, rel_file_1, file_diff)

            if similarity == 1:
                cell.add(span('same', Class = 'same'))
            else:
                rel_file_diff_formatted = add_suffix(rel_dir_formatting / name, '.html')
                cmd = diff2html_cmd(file_diff, rel_file_diff_formatted, file_1.suffix in code_suffices)
                subprocess.run(cmd, check = True, cwd = root)
                modify(root / rel_file_diff_formatted, lambda content: content.replace(
                    '<title>Diff to HTML by rtfpessoa</title>', title(diff_title, __pretty = False).render()
                ).replace(
                    '<h1>Diff to HTML by <a href="https://github.com/rtfpessoa">rtfpessoa</a></h1>',
                    h1(diff_title, __pretty = False).render()
                ))
                cell.add(a(f'{100*similarity:.0f}% same', href = rel_file_diff_formatted))
    return cell

class LabAssignment(Assignment):
    @staticmethod
    def parse_tests(file):
        if not file.exists():
            return []

        r = dict()
        exec(file.read_text(), r)
        return r['tests']

    def __init__(self, course, dir, use_name_handlers = True, use_content_handlers = True, use_cache = True):
        # Obsolete.
        #if isinstance(dir, int):
        #    dir = Path(__file__).parent.parent / 'lab{}'.format(dir)

        self.dir = dir
        self.name = (dir / 'name').read_text()
        super().__init__(course, self.name, use_cache = use_cache)

        self.dir_problem = dir / lab_assignment_constants.rel_dir_problem
        self.dir_solution = dir / lab_assignment_constants.rel_dir_solution
        self.dir_test = dir / lab_assignment_constants.rel_dir_test
        self.dir_robograder = dir / lab_assignment_constants.rel_dir_robograder

        self.name_handlers = None
        self.content_handlers = None
        script_submission_fixes = dir / lab_assignment_constants.rel_file_submission_fixes
        if script_submission_fixes.is_file():
            r = submission_fix_lib.load_submission_fixes(script_submission_fixes)
            if use_name_handlers:
                self.name_handlers = submission_fix_lib.package_handlers(r.name_handlers)
            if use_content_handlers:
                self.content_handlers = submission_fix_lib.package_handlers(r.content_handlers)

        self.files_solution = sorted_directory_list(self.dir_solution, filter = lambda f: f.is_file())
        self.files_problem = sorted_directory_list(self.dir_problem, filter = lambda f: f.is_file())
        self.deadlines = [
            datetime.fromisoformat(line)
            for line in (dir / lab_assignment_constants.rel_file_deadlines).read_text().splitlines()
        ]

        def load_if_exists(f, path):
            return f(path) if path.exists() else None
        self.tests = load_if_exists(
            lambda x: test_lib.parse_tests(x), self.dir_test / lab_assignment_constants.rel_file_tests
        )
        self.robograders = load_if_exists(
            LabAssignment.parse_tests, self.dir_robograder / lab_assignment_constants.rel_file_robograders
        )

        self.java_version = get_java_version()

    # Only works if groups follow a uniform naming scheme with varying number at end of string.
    def group_from_number(self, group_number):
        return self.group_set.name_to_id[self.group_set.prefix + str(group_number)]

    def group_dir(self, dir_output, group):
        group_name = self.group_set.details[group].name
        return Path(group_name) if dir_output == Path() else dir_output / group_name

    def group_number(self, group):
        numbers = [s for s in self.group_set.str(group).split() if s.isdigit()]
        assert(len(numbers) == 1)
        return int(numbers[0])

    def parse_deadline(self, deadline):
        if isinstance(deadline, datetime):
            return deadline
        if isinstance(deadline, int):
            return self.deadlines[deadline]
        assert(deadline is None)
        return deadline

    # Returns the index of the deadline under which this date falls.
    # If there is none, returns the number of deadlines.
    def get_deadline_index(self, x):
        return ilen(filter(lambda d: d < x, self.deadlines))

    def parse_group(self, x):
        if isinstance(x, int):
            return x
        assert(isinstance(x, str))
        if x.isdigit():
            x = self.group_set.prefix + x
        return self.group_set.name_to_id[x]

    def parse_groups(self, xs):
        return list(map(self.parse_group, xs))

    def get_ungraded_submissions(self):
        return [group for group, s in self.submissions.items() if LabAssignment.is_to_be_graded(s)]

    @staticmethod
    def is_to_be_graded(s):
        x = Assignment.last_graded_submission(s)
        if x and x.grade == 'complete':
            return False

        return Assignment.current_submission(s).workflow_state == 'submitted'

    # def unpack(self, dir, submissions, unhandled = None, write_ids = False):
    #     logger.info('unpacking: {}'.format(shlex.quote(str(dir))))
    #     unhandled_any = False
    #     dir.mkdir()
    #
    #     def unhandled_warn(id, name):
    #         nonlocal unhandled
    #         name_unhandled = name + '.unhandled'
    #         if unhandled != None:
    #             unhandled.append((id, name, dir / name_unhandled))
    #         return name_unhandled
    #
    #     files = Assignment.get_files(
    #         submissions,
    #         Assignment.name_handler(self.files_solution, self.name_handlers, unhandled_warn)
    #     )
    #     file_mapping = self.create_submission_dir(
    #         dir,
    #         submissions[-1],
    #         files,
    #         write_ids = write_ids,
    #         content_handlers = self.content_handlers
    #     )

    def unpack_linked(self, dir_files, dir, rel_dir_files, submissions, unhandled = None):
        logger.info('unpacking: {}'.format(shlex.quote(str(dir))))
        dir.mkdir()

        def unhandled_warn(id, name):
            nonlocal unhandled
            name_unhandled = name + '.unhandled'
            if unhandled is not None:
                unhandled.append((id, name, dir / name_unhandled))
            return name_unhandled

        files = Assignment.get_files(
            submissions,
            Assignment.name_handler(self.files_solution, self.name_handlers, unhandled_warn)
        )
        self.create_submission_dir_linked(
            dir_files,
            dir,
            rel_dir_files,
            submissions[-1],
            files,
            content_handlers = self.content_handlers
        )

    # static
    stages = {
        False: lab_assignment_constants.rel_dir_current,
        True: lab_assignment_constants.rel_dir_previous,
    }

    def name_handler_suggestion(self, name, file):
        suggestions = list()

        # Remove copy suffices
        repeat = ['remove_windows_copy', 'remove_dash_copy']
        while(True):
            progress = False
            for handler_name in repeat:
                try:
                    name = getattr(submission_fix_lib, handler_name)(name)
                    suggestions.append(handler_name)
                    progress = True
                except submission_fix_lib.HandlerException:
                    pass
            if not progress:
                break

        # Fix capitalization.
        # Known files are assumed unique up to capitalization.
        names_known_lower = dict((n.lower(), n) for n in itertools.chain(self.files_solution, self.files_problem))
        x = names_known_lower.get(name.lower())
        if x and name != x:
            suggestions.append('fix_capitalization({})'.format(repr(x)))
            name = x

        # Recognition stage
        file_problem = self.files_problem.get(name)
        if name in self.files_solution:
            pass
        elif file_problem:
            suggestions.append(
                'is_problem_file' if file_problem.read_bytes() == file.read_bytes() else 'is_modified_problem_file'
            )
        else:
            suggestions.append('???')

        if len(suggestions) == 1:
            return from_singleton(suggestions)
        return '[{}]'.format(', '.join(suggestions))

    def submissions_unpack(self, dir, groups):
        logger.log(25, 'Unpacking submissions...')
        dir.mkdir(exist_ok = True)

        unhandled = list()
        for group in groups:
            dir_group = self.group_dir(dir, group)
            mkdir_fresh(dir_group)
            for previous, rel_dir in LabAssignment.stages.items():
                submissions = Assignment.get_submissions(self.submissions[group], previous)
                if submissions:
                    #self.unpack(
                    #    dir_group_submission,
                    #    submissions,
                    #    unhandled = unhandled if not previous else None,
                    #    write_ids = write_ids
                    #)
                    self.unpack_linked(
                        dir / lab_assignment_constants.rel_dir_files,
                        dir_group / rel_dir,
                        Path('..') / '..' / lab_assignment_constants.rel_dir_files,
                        submissions,
                        unhandled = unhandled if not previous else None
                    )

            with (dir_group / 'members.txt').open('w') as file:
                for user in self.group_set.group_users[group]:
                    print(self.course.user_str(user), file = file)

        if unhandled:
            print_error('There were unhandled files.')
            print_error('You can find them by running: find {}/*/{} -name \'*.unhandled\''.format(
                shlex.quote(str(dir)),
                shlex.quote(lab_assignment_constants.rel_dir_current)
            ))
            print_error(
                'Add (without comments) and complete the below \'name_handlers\' '
                'in \'{}\' in the lab directory.'.format(lab_assignment_constants.rel_file_submission_fixes)
            )
            print_error('Remember to push your changes so that your colleagues benefit from your fixes.')
            for id, name, file in unhandled:
                suggestion = self.name_handler_suggestion(name, file)
                print_error('    # {}'.format(shlex.quote(str(file))))
                print_error('    {}: {},'.format(id, suggestion))
            exit(1)

    def prepare_build(self, dir, dir_problem, rel_dir_submission):
        logger.info('preparing build directory: {}'.format(shlex.quote(str(dir))))
        dir_build = dir / lab_assignment_constants.rel_dir_build
        dir_submission = dir / rel_dir_submission

        # Link the problem files.
        mkdir_fresh(dir_build)
        link_dir_contents(dir_problem, dir_build, exists_ok = True)

        # Link the submitted files.
        for file in dir_submission.iterdir():
            if not file.name.startswith('.'):
                target = dir_build / file.name
                assert(not(target.is_dir()))
                if target.is_file():
                    target.unlink()
                target.symlink_to(os.path.relpath(file, dir_build))

    def submissions_prepare_build(self, dir, groups):
        logger.log(25, 'Preparing build directories...')
        assert(dir.exists())

        # make output directory self-contained
        subdirs = [
            (self.dir_problem, dir / lab_assignment_constants.rel_dir_problem),
            (self.dir_solution, dir / lab_assignment_constants.rel_dir_solution)
        ]
        if not dir.samefile(self.dir):
            for source, target in subdirs:
                copy_tree_fresh(source, target)

        if [() for _, target in subdirs for f in target.iterdir() if f.suffix == '.class']:
            print_error('I am refusing to work on a lab whose problem/solution folders contain class files.')
            exit(1)

        self.prepare_build(
            dir,
            dir / lab_assignment_constants.rel_dir_problem,
            lab_assignment_constants.rel_dir_solution
        )
        for group in groups:
            self.prepare_build(
                self.group_dir(dir, group),
                dir / lab_assignment_constants.rel_dir_problem,
                lab_assignment_constants.rel_dir_current
            )

    # Return value indicates success.
    def compile(self, dir, dir_problem, rel_dir_submission, strict = True):
        logger.info('compiling: {}'.format(shlex.quote(str(dir))))

        # Compile java files.
        compilation_errors = compile_java(
            [Path(f.name) for d in [dir_problem, dir / rel_dir_submission] for f in d.iterdir() if f.suffix == '.java'],
            strict = False,
            working_dir = dir / lab_assignment_constants.rel_dir_build,
            destination = Path(),
            options = javac_options,
        )
        if compilation_errors is not None:
            (dir / lab_assignment_constants.rel_file_compilation_errors).write_text(compilation_errors)
            return False

        return True

    # Return value indicates success.
    def submissions_compile(self, dir, groups, strict = True):
        logger.log(25, 'Compiling...')
        assert(dir.exists())

        # make output directory self-contained
        if not dir.samefile(self.dir):
            shutil.copytree(self.dir_problem, dir / lab_assignment_constants.rel_dir_problem, dirs_exist_ok = True)
            shutil.copytree(self.dir_solution, dir / lab_assignment_constants.rel_dir_solution, dirs_exist_ok = True)

        r = self.compile(
            dir,
            dir / lab_assignment_constants.rel_dir_problem,
            lab_assignment_constants.rel_dir_solution,
            strict = True
        )  # solution files must compile
        for group in groups:
            r &= self.compile(
                self.group_dir(dir, group),
                dir / lab_assignment_constants.rel_dir_problem,
                lab_assignment_constants.rel_dir_current,
                strict = False
            )
        if not r and strict:
            print_error('There were compilation errors.')
            print_error(
                'Investigate if any of them are due to differences in the '
                'students\' compilation environment, for example: package declarations, unresolved imports.'
            )
            print_error(
                'If so, add appropriate handlers to \'content_handlers\' in '
                '\'{}\' to fix them persistently.'.format(lab_assignment_constants.rel_file_submission_fixes)
            )
            print_error('For this, you must know the Canvas ids of the files to edit.')
            print_error('These can be learned by activating the option to write ids.')
            print_error('Remember to push your changes so that your colleagues benefit from your fixes.')
            print_error('You need to unpack the submissions again for your fixes to take effect.')
            print_error(
                'If there are still unresolved compilation errors, you may allow '
                'them in this phase (they will be reported in the overview index).'
            )
            exit(1)
        return r

    def remove_class_files(self, dir):
        logger.info('removing class files: {}'.format(shlex.quote(str(dir))))
        dir_build = dir / lab_assignment_constants.rel_dir_build
        for file in dir_build.iterdir():
            if file.suffix == '.class':
                file.unlink()

    def submissions_remove_class_files(self, dir, groups):
        logger.log(25, 'Removing class files...')
        assert(dir.exists())
        self.remove_class_files(dir)
        for group in groups:
            self.remove_class_files(self.group_dir(dir, group))

    @staticmethod
    def parse_int_from_file(file):
        return int(file.read_text()) if file.exists() else None

    @staticmethod
    def parse_float_from_file(file):
        return float(file.read_text()) if file.exists() else None

    @staticmethod
    def is_test_successful(dir):
        return all([
            not LabAssignment.parse_float_from_file(dir / 'timeout'),
            LabAssignment.parse_int_from_file(dir / 'ret') == 0,
        ])

    @staticmethod
    def write_test_report(dir, test_name, file_out):
        dir_test = dir / test_name

        ret = LabAssignment.parse_int_from_file(dir_test / 'ret')
        timeout = LabAssignment.parse_float_from_file(dir_test / 'timeout')
        out = (dir_test / 'out').read_text()
        err = (dir_test / 'err').read_text()

        doc = document(title = 'Report for test {}'.format(test_name))
        with doc.head:
            meta(charset = 'utf-8')
            style("""\
pre { margin: 0px; white-space: pre-wrap; }
.error { color: #af0000; }
""")
        with doc.body:
            if timeout is not None:
                p('Timed out after {} seconds.'.format(timeout), Class = 'error')
            elif ret != 0:
                p('Failed with return code {}.'.format(ret), Class = 'error')
            if out:
                h2('Output')
                pre(out)
            if err:
                h2('Errors')
                pre(err, Class = 'error')
        file_out.write_text(doc.render())

    def test(self, dir, strict = False, machine_speed = 1):
        logger.info('testing: {}'.format(shlex.quote(str(dir))))
        dir_build = dir / lab_assignment_constants.rel_dir_build
        dir_build_test = dir / lab_assignment_constants.rel_dir_build_test
        mkdir_fresh(dir_build_test)

        # Create policy file.
        policy_file = dir / 'policy-test'
        policy_file.write_text(policy([
        ]))

        for test_name, test_spec in self.tests.items():
            dir_test = dir_build_test / test_name
            dir_test.mkdir()

            cmd = list(java_cmd(
                test_spec.class_name,
                test_spec.args,
                security_policy = os.path.relpath(policy_file, dir_build),
                enable_assertions = test_spec.enable_assertions,
                options = java_options(self.java_version),
            ))
            (dir_test / 'cmd').write_text(shlex.join(cmd))
            if test_spec.input is not None:
                (dir_test / 'in').write_text(test_spec.input)
            try:
                with Timer() as t:
                    process = subprocess.run(
                        cmd,
                        cwd = dir_build,
                        timeout = test_spec.timeout / machine_speed,
                        input = test_spec.input.encode() if test_spec.input is not None else None,
                        stdout = (dir_test / 'out').open('wb'),
                        stderr = (dir_test / 'err').open('wb')
                    )
                (dir_test / 'ret').write_text(str(process.returncode))
                logger.info('test {} took {}s'.format(test_name, format_with_rel_prec(t.time, 3)))
            except subprocess.TimeoutExpired:
                (dir_test / 'timeout').write_text(str(t.time))
                logger.info('test {} timed out after {}s'.format(test_name, format_with_rel_prec(t.time, 3)))

            # This does not strictly belong here.
            # It should be called only in build_index.
            # The report should be saved in the analysis directory.
            LabAssignment.write_test_report(dir_build_test, test_name, dir_test / 'report.html')

            if strict:
                assert(LabAssignment.is_test_successful(dir_test))

    # Only tests submissions that do not have compilation errors.
    def submissions_test(self, dir, groups, strict = False, machine_speed = 1):
        logger.log(25, 'Testing...')
        assert(dir.exists())

        self.test(dir, strict = True, machine_speed = machine_speed)
        for group in groups:
            dir_group = self.group_dir(dir, group)
            if not (dir_group / lab_assignment_constants.rel_file_compilation_errors).exists():
                self.test(dir_group, strict = strict, machine_speed = machine_speed)

    def robograde(self, dir, dir_robograder, strict = False):
        logger.info('Robograding: {}'.format(shlex.quote(str(dir))))

        file_robograding = dir / lab_assignment_constants.rel_file_robograding
        file_robograding_errors = dir / lab_assignment_constants.rel_file_robograding_errors

        file_robograding.unlink(missing_ok = True)
        file_robograding_errors.unlink(missing_ok = True)

        class RobogradingException(Exception):
            def __init__(self, msg):
                self.msg = msg

        # Check for class name conflicts.
        dir_build = dir / lab_assignment_constants.rel_dir_build
        for file in dir_robograder.iterdir():
            if file.suffix == '.java':
                if (dir_build / file.name).exists():
                    raise RobogradingException(
                        'The submission contains a top-level Java file with '
                        'name {}, which is also used for robograding.'.format(shlex.quote(file.name))
                    )

        # Create policy file.
        policy_file = dir / 'policy-robograder'
        policy_file.write_text(policy([
            (os.path.relpath(dir_robograder, dir_build), [permission_all]),
        ]))

        # Run them.
        def f(java_name):
            cmd = list(java_cmd(
                java_name,
                security_policy = os.path.relpath(policy_file, dir_build),
                classpath = [os.path.relpath(dir_build, dir_build), os.path.relpath(dir_robograder, dir_build)],
                options = java_options(self.java_version),
            ))
            log_command(cmd, dir_build)
            if strict:
                process = subprocess.run(cmd, cwd = dir_build, stdout = subprocess.PIPE, encoding = 'utf-8')
                assert(process.returncode == 0)
            else:
                process = subprocess.run(cmd, cwd = dir_build, capture_output = True, encoding = 'utf-8')
                if process.returncode != 0:
                    raise RobogradingException('\n'.join([
                        'Running {} returned with {}.'.format(java_name, process.returncode),
                        'The error output was as follows:',
                        str(process.stderr),
                    ]))

            r = str(process.stdout)
            logger.debug('robograding output of {}:\n'.format(java_name) + r)
            return r

        try:
            robograder_output = '\n'.join(f(java_name) for java_name in self.robograders)
            file_robograding.write_text(robograder_output)
        except RobogradingException as e:
            robograder_error = e.msg
            file_robograding_errors.write_text(robograder_error)

    # Only tests submissions that do not have compilation errors.
    def submissions_robograde(self, dir, groups, robograde_model_solution = False, strict = False):
        assert(dir.exists())
        if self.robograders:
            logger.log(25, 'Robograding.')

            dir_build = dir / lab_assignment_constants.rel_dir_build
            dir_robograder = dir / lab_assignment_constants.rel_dir_robograder
            java_files = [file.name for file in self.dir_robograder.iterdir() if file.suffix == '.java']

            # Make output directory self-contained and check it is non-conflicting.
            dir_robograder.mkdir(exist_ok = True)
            for file in java_files:
                shutil.copy2(self.dir_robograder / file, dir_robograder)
                assert(not(dir_build / file).exists())

            # Compile test files.
            compile_java(
                (dir_robograder / file for file in java_files),
                force_recompile = True,
                strict = True,
                destination = dir_robograder,
                classpath = [dir_build, dir_robograder],
                options = javac_options + ['-implicit:none'],
            )

            if robograde_model_solution:
                self.robograde(dir, dir_robograder, strict = True)
            for group in groups:
                dir_group = self.group_dir(dir, group)
                if not (dir_group / lab_assignment_constants.rel_file_compilation_errors).exists():
                    self.robograde(dir_group, dir_robograder, strict = strict)

    def remove_class_files_submissions(self, dir, groups):
        for group in groups:
            self.remove_class_files(self.group_dir(dir, group))

    def build_index(self, dir, groups, deadline = None, goodwill_period = timedelta(minutes = 5), preview = True):
        logger.log(25, 'Writing overview index...')
        assert(dir.exists())
        doc = document()
        doc.title = 'Grading Over It'
        with doc.head:
            meta(charset = 'utf-8')
            style("""
.controls {
  margin-top: 5px;
  margin-bottom: 5px;
}
#results {
  border-collapse: collapse;
  border: 1px black solid;
}
#results th, #results td {
  border-top: 1px black solid;
  border-bottom: 1px black solid;
  border-left: 1px black solid;
  padding: 5px;
  vertical-align: top;
}
#results pre {
  font-size: smaller;
  margin: 0px;
  white-space: pre-wrap;
}
#results .files {
  border-collapse: collapse
}
#results .files td {
  border: 0px;
  padding: 0px;
  vertical-align: top;
  white-space: nowrap;
}
.same {
  opacity: 0.5;
}
.error {
  color: #af0000;
}
.hidden {
  display: none;
}
.to-load {
  background-color: #eeeeee;
}
""")
            with script(type = 'text/javascript'):
                raw("""

  function listSet(classList, _class, value) {
    classList[value ? 'add' : 'remove'](_class);
  }

  function getVisibility(row) {
    return !row.firstElementChild.classList.contains('to-load');
  }

  function setVisibility(row, visibility) {
    first = true;
    for (cell of row.getElementsByTagName('TD')) {
      listSet(cell.classList, 'to-load', !visibility);
      if (!first)
        listSet(cell.firstElementChild.classList, 'hidden', !visibility);
      first = false;
    }
  }

  function setVisibilityAll(visibility) {
    for (row of document.getElementById('results').getElementsByTagName('TBODY')[0].getElementsByTagName('TR'))
      setVisibility(row, visibility);
  }

  function handleClick(element, event) {
    if (event.eventPhase === Event.AT_TARGET) {
      while (element.nodeName !== 'TD')
        element = element.parentElement;
      row = element.parentElement
      if (getVisibility(row)) {
        if (element.previousElementSibling === null)
          setVisibility(row, false);
      } else
        setVisibility(row, true);
    }
  }
""")

        file_syntax_highlight_css = Path('syntax-highlight.css')
        shutil.copyfile(Path(__file__).parent / file_syntax_highlight_css, dir / file_syntax_highlight_css)

        if not len(groups) < 10:
            doc.body['onload'] = 'setVisibilityAll(false);'

        with doc.body.add(div(Class = 'controls')):
            button('Show all', onclick = 'setVisibilityAll(true);')
            text(' / ')
            button('Hide all', onclick = 'setVisibilityAll(false);')

        js_params = {
            'onclick': 'handleClick(this, event);'
        }

        def cell(*args, **kwargs):
            return div(*args, **kwargs, **js_params)

        row_data_dict = dict()
        for group in groups:
            logger.info('processing {}...'.format(self.group_set.str(group)))

            row_data = SimpleNamespace()
            row_data_dict[group] = row_data

            rel_dir_group = self.group_dir(Path(), group)
            rel_dir_group_analysis = rel_dir_group / lab_assignment_constants.rel_dir_analysis
            (dir / rel_dir_group_analysis).mkdir(exist_ok = True)
            dir_analysis = dir / rel_dir_group_analysis
            mkdir_fresh(dir_analysis)

            dir_group = self.group_dir(dir, group)
            filenames_current = sorted_directory_list(
                dir_group / lab_assignment_constants.rel_dir_current,
                filter = lambda f: f.is_file() and not f.name.startswith('.')
            ).keys()
            filenames = list(filenames_current) + list(set(self.files_solution) - set(filenames_current))

            current_submission = Assignment.current_submission(self.submissions[group])

            def build_files_table(xs, f):
                if not xs:
                    return None

                c = cell()
                table_body = c.add(table(Class = 'files')).add(tbody())
                for x in xs:
                    table_body.add(tr()).add(f(x))
                return c

            # Group number
            row_data.group = cell(a(
                self.group_number(group),
                href = self.submission_speedgrader_url(current_submission)
            ))

            # Late submission
            row_data.late = None
            parsed_deadline = self.parse_deadline(deadline)
            if parsed_deadline:
                time_diff = current_submission.submitted_at_date - parsed_deadline
                if time_diff >= goodwill_period:
                    row_data.late = cell(format_timespan(time_diff))

            # Submitted files
            row_data.files = cell()
            files_table_body = row_data.files.add(table(Class = 'files')).add(tbody())
            for filename in filenames:
                files_table_body.add(tr()).add(format_file(
                    dir,
                    filename,
                    rel_dir_group / lab_assignment_constants.rel_dir_current,
                    rel_dir_group_analysis / lab_assignment_constants.rel_dir_current,
                    file_syntax_highlight_css
                ))

            # Diffs to other files
            def build_diff_table(rel_base_dir, folder_name):
                return build_files_table(filenames, lambda filename: format_diff(
                    dir,
                    filename,
                    rel_base_dir / folder_name,
                    rel_dir_group / lab_assignment_constants.rel_dir_current,
                    rel_dir_group_analysis / folder_name,
                    '{}: compared to {}'.format(filename, folder_name)
                ))

            row_data.files_vs_previous = build_diff_table(
                rel_dir_group,
                lab_assignment_constants.rel_dir_previous
            ) if (dir_group / lab_assignment_constants.rel_dir_previous).exists() else None
            row_data.files_vs_problem = build_diff_table(Path(), lab_assignment_constants.rel_dir_problem)
            row_data.files_vs_solution = build_diff_table(Path(), lab_assignment_constants.rel_dir_solution)

            # Compilation errors
            file_compilation_errors = dir_group / lab_assignment_constants.rel_file_compilation_errors
            row_data.compilation_errors = cell(
                pre(file_compilation_errors.read_text(), Class = 'error')
            ) if file_compilation_errors.exists() else None

            # Tests
            if (dir_group / lab_assignment_constants.rel_dir_build_test).exists():
                (dir_analysis / lab_assignment_constants.rel_dir_build_test).mkdir()

                def handle_test(test_name):
                    rel_test_dir = rel_dir_group / Path(lab_assignment_constants.rel_dir_build_test) / test_name
                    r = a(test_name, href = rel_test_dir / lab_assignment_constants.rel_file_report)
                    if not LabAssignment.is_test_successful(dir / rel_test_dir):
                        r.set_attribute('class', 'error')
                    return td(r)

                test_names = self.tests.keys()
                row_data.tests = build_files_table(test_names, handle_test)
                row_data.tests_vs_solution = build_files_table(test_names, lambda test_name: format_diff(
                    dir,
                    'out',
                    Path(lab_assignment_constants.rel_dir_build_test) / test_name,
                    rel_dir_group / lab_assignment_constants.rel_dir_build_test / test_name,
                    rel_dir_group_analysis / lab_assignment_constants.rel_dir_build_test / test_name,
                    'Test {} output: compared to {}'.format(test_name, lab_assignment_constants.rel_dir_solution)
                ))
            else:
                row_data.tests = None
                row_data.tests_vs_solution = None

            # Robograding
            def f():
                for (file, attributes) in [
                    (dir_group / lab_assignment_constants.rel_file_robograding_errors, {'Class': 'error'}),
                    (dir_group / lab_assignment_constants.rel_file_robograding, {}),
                ]:
                    if file.exists():
                        return cell(pre(file.read_text(), **attributes))
            row_data.robograding = f()

            # Comments
            ungraded_comments = Assignment.ungraded_comments(self.submissions[group])
            row_data.new_comments = cell(
                pre('\n'.join(Assignment.format_comments(ungraded_comments)))
            ) if ungraded_comments else None

        #def build_index_files_entry(rel_base_dir, folder_name):
        #    return (
        #        'Vs. {}'.format(folder_name),
        #        lambda group: build_index_files(group, rel_base_dir(group), folder_name)
        #    )

        T = namedtuple('KeyData', ['title', 'style'], defaults = [None])

        # This took me more than 2 hours.
        def with_after(title, title_after):
            return T(th(
                div(
                    title + title_after,
                    style = 'white-space: pre; max-height: 0; visibility: hidden;'
                ),
                title,
                span(title_after, style = 'float: right; white-space: pre;')
            ))

        def following(title):
            return T(title, style = 'border-left-color: lightgrey;')

        keys = OrderedDict({
            'group': T('Group', style = 'text-align: center;'),
            'late': T('Late'),
            'files': with_after('Files', ' vs:'),
            'files_vs_previous': following(lab_assignment_constants.rel_dir_previous),
            'files_vs_problem': following(lab_assignment_constants.rel_dir_problem),
            'files_vs_solution': following(lab_assignment_constants.rel_dir_solution),
            'compilation_errors': T('Compilation errors'),
            'tests': with_after('Tests', ' vs:'),
            'tests_vs_solution': following(lab_assignment_constants.rel_dir_solution),
            'robograding': T('Robograding'),
            'new_comments': T('New comments'),
        })

        # remove empty columns
        for key in list(keys.keys()):
            non_empty = False
            for group, row_data in row_data_dict.items():
                non_empty |= row_data.__dict__[key] is not None
            if not non_empty:
                del keys[key]
            else:
                for group, row_data in row_data_dict.items():
                    if row_data.__dict__[key] is None:
                        row_data.__dict__[key] = cell()

        def handle(key_data, el):
            if key_data.style:
                el.set_attribute('style', key_data.style)

        results_table = doc.body.add(table(id = 'results'))
        header_row = results_table.add(thead()).add(tr())
        for key, key_data in keys.items():
            handle(key_data, header_row.add(th(key_data.title) if isinstance(key_data.title, str) else key_data.title))
        results_table_body = results_table.add(tbody())
        for group, row_data in row_data_dict.items():
            row = results_table_body.add(tr())
            for key, key_data in keys.items():
                handle(key_data, row.add(td(row_data.__dict__[key], **js_params)))

        file_index = dir / 'index.html'
        file_index.write_text(doc.render())
        if preview:
            webbrowser.open(file_index.resolve().as_uri())
