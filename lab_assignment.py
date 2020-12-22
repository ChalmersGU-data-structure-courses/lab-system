from collections import namedtuple, OrderedDict
from datetime import datetime, timedelta
import itertools
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
from dominate.tags import *
from dominate.util import raw, text

from general import compose_many, from_singleton, ilen, Timer, print_error, print_json, mkdir_fresh, exec_simple, link_dir_contents, add_suffix, modify, format_with_rel_prec, format_timespan, sorted_directory_list
from canvas import Canvas, Course, Assignment
import lab_assignment_constants
import submission_fix_lib
import test_lib

logger = logging.getLogger("lab_assignment")

def diff_cmd(file_0, file_1):
    return ['diff', '--text', '--ignore-blank-lines', '--ignore-space-change', '--strip-trailing-cr', '-U', '1000000', '--'] + [file_0, file_1]

def diff2html_cmd(file_input, file_output, highlight):
    return ['diff2html', '--style', 'side', '--highlightCode', str(bool(highlight)).lower(), '--input', 'file', '--file', file_output, '--', file_input]

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

    return sum(not any ([line.startswith(c) for c in ['+', '-']]) for line in diff_lines) / len(diff_lines)

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

# Apparently, '-g' is needed to make sure exceptions properly reference names.
def javac_cmd(files):
    return ['javac', '-d', '.', '-g'] + list(files)

def java_cmd(file_security_policy, enable_assertions, class_name, args):
    cmd = ['java']
    if file_security_policy:
        cmd += ['-D' + 'java.security.manager', '-D' + 'java.security.policy' + '==' + shlex.quote(str(file_security_policy))]
    if enable_assertions:
        cmd += ['-ea']
    cmd.append(class_name)
    cmd.extend(args)
    return cmd

# Unless forced, only recompiles if necessary: missing or outdated class-files.
# On success, returns None.
# On failure, returns compile errors as string.
def compile_java(dir, files, force_recompile = False, strict = False):
    def is_up_to_date(file_java):
        file_class = file_java.with_suffix('.class')
        return file_class.exists() and os.path.getmtime(file_class) > os.path.getmtime(file_java)

    if not all(map(is_up_to_date, files)):
        logger.log(logging.DEBUG, 'Not all class files existing or up to date; (re)compiling.')
        cmd = javac_cmd(file.relative_to(dir) for file in files)
        process = subprocess.run(cmd, cwd = dir, stderr = subprocess.PIPE, encoding = 'utf-8')
        if process.returncode != 0:
            print_error('Encountered compilation errors in {}:'.format(shlex.quote(str(dir))))
            print_error(process.stderr)
            assert(not strict)
            return process.stderr
    return None

def format_file(root, name, rel_dir, rel_dir_formatting, rel_css):
    (root / rel_dir_formatting).mkdir(exist_ok = True)
    cell = td()
    if (root / rel_dir / name).exists():
        result_name = highlight_file(root / rel_dir, root / rel_dir_formatting, name, os.path.relpath(rel_css, rel_dir_formatting))
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
                modify(root / rel_file_diff_formatted, lambda content: content
                    .replace('<title>Diff to HTML by rtfpessoa</title>', title(diff_title, __pretty = False).render())
                    .replace('<h1>Diff to HTML by <a href="https://github.com/rtfpessoa">rtfpessoa</a></h1>', h1(diff_title, __pretty = False).render())
                )
                cell.add(a(f'{100*similarity:.0f}% same', href = rel_file_diff_formatted))
    return cell

class LabAssignment(Assignment):
    @staticmethod
    def parse_tests(file):
        return exec_simple(file).tests if file.exists() else []

    def __init__(self, course, dir, use_name_handlers = True, use_content_handlers = True, use_cache = True):
        if isinstance(dir, int):
            dir = Path(__file__).parent.parent / 'lab{}'.format(dir)

        self.dir = dir
        self.name = (dir / 'name').read_text()
        super().__init__(course, self.name, use_cache = use_cache)

        self.dir_problem = dir / lab_assignment_constants.rel_dir_problem
        self.dir_solution = dir / lab_assignment_constants.rel_dir_solution
        self.dir_test = dir / lab_assignment_constants.rel_dir_test

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
        self.deadlines = [datetime.fromisoformat(line) for line in (dir / lab_assignment_constants.rel_file_deadlines).read_text().splitlines()]

        # new-style tests
        file_tests = self.dir_test / lab_assignment_constants.rel_file_tests
        self.tests = test_lib.parse_tests(file_tests) if file_tests.exists() else None

        file_tests = self.dir_test / lab_assignment_constants.rel_file_tests_java
        self.tests_java = LabAssignment.parse_tests(file_tests) if file_tests.exists() else None

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
        assert(deadline == None)
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
    #     logger.log(logging.INFO, 'unpacking: {}'.format(shlex.quote(str(dir))))
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
    #     files = Assignment.get_files(submissions, Assignment.name_handler(self.files_solution, self.name_handlers, unhandled_warn))
    #     file_mapping = self.create_submission_dir(dir, submissions[-1], files, write_ids = write_ids, content_handlers = self.content_handlers)

    def unpack_linked(self, dir_files, dir, rel_dir_files, submissions, unhandled = None):
        logger.log(logging.INFO, 'unpacking: {}'.format(shlex.quote(str(dir))))
        unhandled_any = False
        dir.mkdir()

        def unhandled_warn(id, name):
            nonlocal unhandled
            name_unhandled = name + '.unhandled'
            if unhandled != None:
                unhandled.append((id, name, dir / name_unhandled))
            return name_unhandled

        files = Assignment.get_files(submissions, Assignment.name_handler(self.files_solution, self.name_handlers, unhandled_warn))
        file_mapping = self.create_submission_dir_linked(dir_files, dir, rel_dir_files, submissions[-1], files, content_handlers = self.content_handlers)

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
            suggestions.append('is_problem_file' if file_problem.read_bytes() == file.read_bytes() else 'is_modified_problem_file')
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
                dir_group_submission = dir_group / rel_dir
                if submissions:
                    #self.unpack(dir_group_submission, submissions, unhandled = unhandled if not previous else None, write_ids = write_ids)
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
            print_error('You can find them by running: find {}/*/{} -name \'*.unhandled\''.format(shlex.quote(str(dir)), shlex.quote(lab_assignment_constants.rel_dir_current)))
            print_error('Add (without comments) and complete the below \'name_handlers\' in \'{}\' in the lab directory.'.format(lab_assignment_constants.rel_file_submission_fixes))
            print_error('Remember to push your changes so that your colleagues benefit from your fixes.')
            for id, name, file in unhandled:
                suggestion = self.name_handler_suggestion(name, file)
                print_error('    # {}'.format(shlex.quote(str(file))))
                print_error('    {}: {},'.format(id, suggestion))
            exit(1)

    def prepare_build(self, dir, dir_problem, rel_dir_submission):
        logger.log(logging.INFO, 'preparing build directory: {}'.format(shlex.quote(str(dir))))
        dir_build = dir / lab_assignment_constants.rel_dir_build
        dir_submission = dir / rel_dir_submission

        # Link the problem files.
        mkdir_fresh(dir_build)
        link_dir_contents(dir_problem, dir_build)

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
        if not dir.samefile(self.dir):
            shutil.copytree(self.dir_problem, dir / lab_assignment_constants.rel_dir_problem, dirs_exist_ok = True)
            shutil.copytree(self.dir_solution, dir / lab_assignment_constants.rel_dir_solution, dirs_exist_ok = True)

        self.prepare_build(dir, dir / lab_assignment_constants.rel_dir_problem, lab_assignment_constants.rel_dir_solution)
        for group in groups:
            self.prepare_build(self.group_dir(dir, group), dir / lab_assignment_constants.rel_dir_problem, lab_assignment_constants.rel_dir_current)

    # Return value indicates success.
    def compile(self, dir, dir_problem, rel_dir_submission, strict = True):
        logger.log(logging.INFO, 'compiling: {}'.format(shlex.quote(str(dir))))
        dir_build = dir / lab_assignment_constants.rel_dir_build
        dir_submission = dir / rel_dir_submission

        # Compile java files.
        files_java = [dir_build / f.name for d in [dir_problem, dir_submission] for f in d.iterdir() if f.suffix == '.java']
        compilation_errors = compile_java(dir_build, files_java, strict = False)
        if compilation_errors != None:
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

        r = self.compile(dir, dir / lab_assignment_constants.rel_dir_problem, lab_assignment_constants.rel_dir_solution, strict = True) # solution files must compile
        for group in groups:
            r &= self.compile(self.group_dir(dir, group), dir / lab_assignment_constants.rel_dir_problem, lab_assignment_constants.rel_dir_current, strict = False)
        if not r and strict:
            print_error('There were compilation errors.')
            print_error('Investigate if any of them are due to differences in the students\' compilation environment, for example: package declarations, unresolved imports.')
            print_error('If so, add appropriate handlers to \'content_handlers\' in \'{}\' to fix them persistently.'.format(lab_assignment_constants.rel_file_submission_fixes))
            print_error('For this, you must know the Canvas ids of the files to edit.')
            print_error('These can be learned by activating the option to write ids.')
            print_error('Remember to push your changes so that your colleagues benefit from your fixes.')
            print_error('You need to unpack the submissions again for your fixes to take effect.')
            print_error('If there are still unresolved compilation errors, you may allow them in this phase (they will be reported in the overview index).')
            exit(1)
        return r

    def remove_class_files(self, dir):
        logger.log(logging.INFO, 'removing class files: {}'.format(shlex.quote(str(dir))))
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
        return not LabAssignment.parse_float_from_file(dir / 'timeout') and LabAssignment.parse_int_from_file(dir / 'ret') == 0

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
            if timeout != None:
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

    def test(self, dir, policy = None, strict = False, machine_speed = 1):
        logger.log(logging.INFO, 'testing: {}'.format(shlex.quote(str(dir))))
        dir_build = dir / lab_assignment_constants.rel_dir_build

        dir_build_test = dir / lab_assignment_constants.rel_dir_build_test
        mkdir_fresh(dir_build_test)

        for test_name, test_spec in self.tests.items():
            dir_test = dir_build_test / test_name
            dir_test.mkdir()

            cmd = java_cmd(
                Path('..') / policy if policy else None,
                test_spec.enable_assertions,
                test_spec.class_name,
                test_spec.args
            )
            (dir_test / 'cmd').write_text(shlex.join(cmd))
            if test_spec.input != None:
                (dir_test / 'in').write_text(test_spec.input)
            try:
                with Timer() as t:
                    process = subprocess.run(
                        cmd,
                        cwd = dir_build,
                        timeout = test_spec.timeout / machine_speed,
                        input = test_spec.input.encode() if test_spec.input != None else None,
                        stdout = (dir_test / 'out').open('wb'),
                        stderr = (dir_test / 'err').open('wb')
                    )
                (dir_test / 'ret').write_text(str(process.returncode))
                logger.log(logging.INFO, 'test {} took {}s'.format(test_name, format_with_rel_prec(t.time, 3)))
            except subprocess.TimeoutExpired:
                (dir_test / 'timeout').write_text(str(test_spec.timeout))
                logger.log(logging.INFO, 'test {} timed out after {}s'.format(test_name, format_with_rel_prec(test_spec.timeout, 3)))

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

        shutil.copyfile(Path(__file__).parent / lab_assignment_constants.rel_file_java_policy, dir / lab_assignment_constants.rel_file_java_policy)
        self.test(dir, Path(lab_assignment_constants.rel_file_java_policy), strict = True, machine_speed = machine_speed)
        for group in groups:
            dir_group = self.group_dir(dir, group)
            if not (dir_group / lab_assignment_constants.rel_file_compilation_errors).exists():
                self.test(dir_group, policy = Path('..') / lab_assignment_constants.rel_file_java_policy, strict = strict, machine_speed = machine_speed)

    def pregrade(self, dir, dir_test, rel_dir_submission, strict = True):
        logger.log(logging.INFO, 'Pregrading: {}'.format(shlex.quote(str(dir))))
        dir_build = dir / lab_assignment_constants.rel_dir_build
        dir_submission = dir / rel_dir_submission
        dir_test_java = dir_test / 'java'

        # Link the testing files.
        files_java = link_dir_contents(dir_test_java, dir_build)

        # Compile java files.
        compile_java(dir_build, files_java, strict = True)

        # Run them.
        def f(java_name):
            cmd = ['java', java_name]
            process = subprocess.run(cmd, cwd = dir_build, stdout = subprocess.PIPE, encoding = 'utf-8')
            if strict:
                assert(process.returncode == 0)
            r = str(process.stdout)
            logger.log(logging.DEBUG, 'pregrading output of {}:\n'.format(java_name) + r)
            return r

        (dir / lab_assignment_constants.rel_file_pregrading).write_text('\n'.join(f(java_name) for java_name in self.tests_java))

    # Only tests submissions that do not have compilation errors.
    def submissions_pregrade(self, dir, groups, strict = True):
        assert(dir.exists())
        if self.tests_java:
            logger.log(25, 'Pregrading.')

            # make output directory self-contained
            if not dir.samefile(self.dir):
                shutil.copytree(self.dir_test, dir / lab_assignment_constants.rel_dir_test, dirs_exist_ok = True)

            self.pregrade(dir, dir / lab_assignment_constants.rel_dir_test, lab_assignment_constants.rel_dir_solution, strict = strict)
            for group in groups:
                dir_group = self.group_dir(dir, group)
                if not (dir_group / lab_assignment_constants.rel_file_compilation_errors).exists():
                    self.pregrade(dir_group, dir / lab_assignment_constants.rel_dir_test, lab_assignment_constants.rel_dir_current, strict = strict)

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
            logger.log(logging.INFO, 'processing {}...'.format(self.group_set.str(group)))

            row_data = SimpleNamespace()
            row_data_dict[group] = row_data

            rel_dir_group = self.group_dir(Path(), group)
            rel_dir_group_analysis = rel_dir_group / lab_assignment_constants.rel_dir_analysis
            (dir / rel_dir_group_analysis).mkdir(exist_ok = True)
            dir_analysis = dir / rel_dir_group_analysis
            mkdir_fresh(dir_analysis)

            dir_group = self.group_dir(dir, group)
            filenames_current = sorted_directory_list(dir_group / lab_assignment_constants.rel_dir_current, filter = lambda f: f.is_file() and not f.name.startswith('.')).keys()
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
            row_data.group = cell(a(self.group_number(group), href = self.submission_speedgrader_url(current_submission)))

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
                files_table_body.add(tr()).add(format_file(dir, filename, rel_dir_group / lab_assignment_constants.rel_dir_current, rel_dir_group_analysis / lab_assignment_constants.rel_dir_current, file_syntax_highlight_css))

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

            row_data.files_vs_previous = build_diff_table(rel_dir_group, lab_assignment_constants.rel_dir_previous) if (dir_group / lab_assignment_constants.rel_dir_previous).exists() else None
            row_data.files_vs_problem = build_diff_table(Path(), lab_assignment_constants.rel_dir_problem)
            row_data.files_vs_solution = build_diff_table(Path(), lab_assignment_constants.rel_dir_solution)

            # Compilation errors
            file_compilation_errors = dir_group / lab_assignment_constants.rel_file_compilation_errors
            row_data.compilation_errors = cell(pre(file_compilation_errors.read_text(), Class = 'error')) if file_compilation_errors.exists() else None

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

            # Pregrading
            file_pregrading = dir_group / lab_assignment_constants.rel_file_pregrading
            row_data.pregrading = cell(pre(file_pregrading.read_text())) if file_pregrading.exists() else None

            # Comments
            ungraded_comments = Assignment.ungraded_comments(self.submissions[group])
            row_data.new_comments = cell(pre('\n'.join(Assignment.format_comments(ungraded_comments)))) if ungraded_comments else None

        def build_index_files_entry(rel_base_dir, folder_name):
            return ('Vs. {}'.format(folder_name), lambda group: build_index_files(group, rel_base_dir(group), folder_name))

        T = namedtuple('KeyData', ['title', 'style'], defaults = [None])

        # This took me more than 2 hours.
        def with_after(title, title_after):
            return T(th(div(title + title_after, style = 'white-space: pre; max-height: 0; visibility: hidden;'), title, span(title_after, style = 'float: right; white-space: pre;')))

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
            'pregrading': T('Pregrading'),
            'new_comments': T('New comments'),
        })

        # remove empty columns
        for key in list(keys.keys()):
            non_empty = False
            for group, row_data in row_data_dict.items():
                non_empty |= row_data.__dict__[key] != None
            if not non_empty:
                del keys[key]
            else:
                for group, row_data in row_data_dict.items():
                    if row_data.__dict__[key] == None:
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
