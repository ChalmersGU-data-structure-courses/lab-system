from collections import OrderedDict
from pathlib import Path
import os.path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace

from dominate import document
from dominate.tags import *
from dominate.util import raw, text

from general import print_error, print_json, mkdir_fresh, exec_simple, link_dir_contents, add_suffix, modify
from canvas import Canvas, Course, Groups, Assignment
from submission_fix_lib import load_submission_fixes

def sorted_filenames(dir):
    return sorted(list(file.name for file in dir.iterdir() if file.is_file()))

def diff_cmd(file_0, file_1):
    return ['diff', '--text', '--ignore-blank-lines', '--ignore-space-change', '--strip-trailing-cr', '-U', '1000000', '--'] + [file_0, file_1]

def diff2html_cmd(file_input, file_output, highlight):
    return ['diff2html', '--style', 'side', '--highlightCode', str(bool(highlight)).lower(), '--input', 'file', '--file', file_output, '--', file_input]

def highlights_cmd(file_input):
    return ['highlights', file_input]

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
    # static
    rel_dir_problem = 'problem'
    rel_dir_solution = 'solution'
    rel_dir_test = 'test'

    # static
    rel_dir_current = 'current'
    rel_dir_previous = 'previous'
    rel_dir_build = 'build'

    # static
    rel_dir_compilation_errors = 'complication-errors.txt'

    def __init__(self, canvas, course_id, assignment_id, dir):
        super().__init__(canvas, course_id, assignment_id)
        self.dir = dir
        self.dir_problem = dir / LabAssignment.rel_dir_problem
        self.dir_solution = dir / LabAssignment.rel_dir_solution
        self.dir_test = dir / LabAssignment.rel_dir_test
        self.file_submission_fixes = dir / 'submission_fixes.py'

        if self.file_submission_fixes.is_file():
            r = load_submission_fixes(self.file_submission_fixes)
            self.name_handlers = r.name_handlers
            self.content_handlers = r.content_handlers
        else:
            self.name_handlers = None
            self.content_handlers = None

        self.solution_files = dict((f.name, f) for f in self.dir_solution.iterdir() if f.is_file())

    # Only works if groups follow a uniform naming scheme with varying number at end of string.
    def group_from_number(self, group_number):
        return self.groups.group_name_to_id[self.groups.group_prefix + str(group_number)]

    def group_dir(self, dir_output, group):
        return dir_output / self.groups.group_details[group].name

    def group_number(self, group):
        numbers = [s for s in self.groups.group_str(group).split() if s.isdigit()]
        assert(len(numbers) == 1)
        return int(numbers[0])

    def parse_group(self, x):
        if isinstance(x, int):
            return x
        assert(isinstance(x, str))
        if x.isdigit():
            x = self.groups.group_prefix + x
        return self.groups.group_name_to_id[x]

    def parse_groups(self, groups = None):
        return map(self.parse_group, groups) if groups != None else self.submissions.keys()

    @staticmethod
    def is_to_be_graded(s):
        x = Assignment.last_graded_submission(s)
        if x and x.grade == 'complete':
            return False

        return Assignment.current_submission(s).workflow_state == 'submitted'

    def get_ungraded_submissions(self):
        return [group for group, s in self.submissions.items() if LabAssignment.is_to_be_graded(s)]

    def unpack_submission(self, dir, submissions, write_ids = False):
        unhandled_any = False
        if submissions:
            dir.mkdir()

            def unhandled_warn(id, name):
                unhandled_any = True
                template_file = self.dir_problem / name
                name_unhandled = name + '.unhandled'
                suggestion = None
                if template_file.is_file():
                    suggestion = 'is_template_file' if template_file.read_text() == submitted_file.read_text() else 'is_modified_template_file';
                    print_error('    {}: {}, # {}', id, suggestion, dir / name)
                    return name_unhandled

            files = Assignment.get_files(submissions, Assignment.name_handler(self.solution_files, self.name_handlers, unhandled_warn))
            file_mapping = self.create_submission_dir(dir, submissions[-1], files, write_ids = write_ids, content_handlers = self.content_handlers)

        return unhandled_any

    def unpack_submissions(self, dir, groups = None, with_previous = True, write_ids = False):
        mkdir_fresh(dir)

        values = [False]
        if with_previous:
            values.append(True)

        unhandled_any = False
        for group in self.parse_groups(groups):
            dir_group = self.group_dir(dir, group)
            dir_group.mkdir()
            for previous in values:
                submissions = Assignment.get_submissions(self.submissions[group], previous)
                dir_group_submission = dir_group / (LabAssignment.rel_dir_previous if previous else LabAssignment.rel_dir_current)
                unhandled_any |= self.unpack_submission(dir_group_submission, submissions, write_ids = write_ids)

        if unhandled_any:
            print_error('There were unhandled files.')
            exit(1)

    def build_submissions(self, dir, groups = None):
        # make output directory self-contained
        if not dir.samefile(self.dir):
            shutil.copytree(self.dir_problem, dir / LabAssignment.rel_dir_problem, dirs_exist_ok = True)
            shutil.copytree(self.dir_solution, dir / LabAssignment.rel_dir_solution, dirs_exist_ok = True)
            if self.dir_test.exists():
                shutil.copytree(self.dir_test, dir / LabAssignment.rel_dir_test, dirs_exist_ok = True)

        for group in self.parse_groups(groups):
            dir_group = self.group_dir(dir, group)
            dir_submission = dir_group / LabAssignment.rel_dir_current
            dir_build = dir_group / LabAssignment.rel_dir_build
            mkdir_fresh(dir_build)

            # Link the problem files.
            link_dir_contents(dir / LabAssignment.rel_dir_problem, dir_build)

            # Copy the submitted files.
            for file in dir_submission.iterdir():
                if not file.name.startswith('.'):
                    target = dir_build / file.name
                    if target.is_dir():
                        print_error('current submission of {} contains a file {}, but this is a directory in the problem directory'.format(self.groups.group_str(group), file.name))
                        exit(1)
                    if target.is_file():
                        target.unlink()
                    shutil.copy(file, target)

            # Compile java files.
            files_java = list(f for f in dir_build.iterdir() if f.suffix == '.java')
            cmd = ['javac'] + [x.name for x in files_java]
            print('Compiling {}...: {}'.format(self.groups.group_str(group), cmd))
            process = subprocess.run(cmd, cwd = dir_build, stderr = subprocess.PIPE, encoding = 'utf-8')
            if process.returncode != 0:
                print_error(process.stderr)
                (dir_group / LabAssignment.rel_dir_compilation_errors).write_text(process.stderr)

    def remove_class_files(self, dir, groups = None):
        for group in self.parse_groups(groups):
            dir_group = self.group_dir(dir, group)
            dir_build = dir_group / LabAssignment.rel_dir_build
            for file in dir_build.iterdir():
                if file.suffix == '.class':
                    file.unlink()

    def build_index(self, dir, groups = None, with_previous = True, preview = True):
        doc = document()
        doc.title = 'Grading Overview'
        with doc.head:
            meta(charset = 'utf-8')
            style("""\
.results { border-collapse: collapse }
.results th, .results td { border: 1px black solid; padding: 5px; vertical-align: top }
.results pre { font-size: smaller; margin: 0px; white-space: pre-wrap }
.files { border-collapse: collapse }
.files td { border : 0px; padding: 0px; vertical-align: top white-space: nowrap }
.same { opacity: 0.5 }
.error { color: #af0000}
""")

        rel_view = '_view'
        rel_css = Path('syntax-highlight.css')

        row_data_dict = dict()
        for group in self.parse_groups(groups):
            print('Processing {}...'.format(self.groups.group_str(group)))

            row_data = SimpleNamespace()
            row_data_dict[group] = row_data

            rel_dir_group = self.group_dir(Path('.'), group)
            rel_view_folder = rel_dir_group / rel_view
            (dir / rel_view_folder).mkdir(exist_ok = True)

            dir_group = self.group_dir(dir, group)
            filenames_current = sorted_filenames(dir_group / LabAssignment.rel_dir_current)
            filenames_solution = sorted_filenames(self.dir_solution)
            filenames = filenames_current + list(set(filenames_solution) - set(filenames_current))

            # Group number
            row_data.group = td(str(self.group_number(group)))

            # Submitted files
            cell = td()
            row_data.files = cell
            files_table_body = cell.add(table(Class = 'files')).add(tbody())
            for filename in filenames:
                files_table_body.add(tr()).add(format_file(dir, filename, rel_dir_group / LabAssignment.rel_dir_current, rel_view_folder / LabAssignment.rel_dir_current, rel_css))

            # Diffs to other files
            def build_diff_table(rel_base_dir, folder_name):
                cell = td()
                files_table_body = cell.add(table(Class = 'files')).add(tbody())
                for filename in filenames:
                    files_table_body.add(tr()).add(format_diff(dir, filename, rel_base_dir / folder_name, rel_dir_group / LabAssignment.rel_dir_current, rel_view_folder / folder_name, '{}: compared to {}'.format(filename, folder_name)))
                return cell

            row_data.files_vs_problem = build_diff_table(Path(), LabAssignment.rel_dir_problem)
            row_data.files_vs_solution = build_diff_table(Path(), LabAssignment.rel_dir_solution)
            if with_previous:
                row_data.files_vs_previous = build_diff_table(rel_dir_group, LabAssignment.rel_dir_previous)

            # Compilation errors
            file_compilation_errors = dir_group / LabAssignment.rel_dir_compilation_errors
            if file_compilation_errors.exists():
                cell = td()
                cell.add(pre(file_compilation_errors.read_text(), Class = 'error'))
                row_data.compilation_errors = cell
            else:
                row_data.compilation_errors = None

            # Comments
            ungraded_comments = Assignment.ungraded_comments(self.submissions[group])
            if ungraded_comments:
                cell = td()
                cell.add(pre('\n'.join(Assignment.format_comments(ungraded_comments))))
                row_data.new_comments = cell
            else:
                row_data.new_comments = None

        def build_index_files_entry(rel_base_dir, folder_name):
            return ('Vs. {}'.format(folder_name), lambda group: build_index_files(group, rel_base_dir(group), folder_name))

        keys = OrderedDict({
            'group': 'Group',
            'files': 'Files',
            'files_vs_problem': 'vs. problem',
            'files_vs_solution': 'vs. solution',
            'files_vs_previous': 'vs. previous',
            'compilation_errors': 'Compilation errors',
            'new_comments': 'New comments',
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
                        row_data.__dict__[key] = td()

        results_table = doc.body.add(table(Class = 'results'))
        with results_table.add(thead()).add(tr()):
            for key in keys:
                th(keys[key])
        results_table_body = results_table.add(tbody())
        for group, row_data in row_data_dict.items():
            row = results_table_body.add(tr())
            for key in keys:
                row.add(row_data.__dict__[key])

        file_index = dir / 'index.html'
        file_index.write_text(doc.render())
        if preview:
            subprocess.run(['firefox', file_index])






    def unpack_submissions_old(self, dir_output, previous = False, unpack = True, copy_template = False, copy_tests = False, compile = False, run_tests = False):
        dir_output.mkdir(exist_ok = True)
#        dir_output.mkdir()

        file_mappings = dict()
        if unpack:
            suggestions = dict()
            unhandled_any = False
            for group, s in self.submissions.items():
                dir_group = self.group_dir(dir_output, group)
                if copy_template:
                    shutil.copytree(self.dir_problem, dir_group, symlinks = True, copy_function = shutil.copy)

                unhandled = dict()
                def unhandled_warn(id, name):
                    unhandled[id] = name
                    return name + '.unhandled'

                submissions = s.submissions
                n = first_ungraded(submissions) if previous else len(submissions)
                files = Assignment.get_files(submissions[:n], Assignment.name_handler(self.solution_files, self.name_handlers, unhandled_warn))
                file_mapping = self.create_submission_dir(dir_group, submissions[n - 1], files, write_ids = True, content_handlers = self.content_handlers)
                file_mappings[group] = file_mapping
                for id, name in unhandled.items():
                    unhandled_any = True
                    submitted_file = file_mapping.get(id)
                    if submitted_file:
                        print_error('Unhandled file with id {}: {}'.format(id, str(submitted_file)))
                        template_file = self.dir_problem / name
                        if template_file.is_file() and template_file.read_text() == submitted_file.read_text():
                            suggestions[id] = 'is_template_file'

                if self.dir_test.is_dir() and copy_tests:
                    for file in self.dir_test.iterdir():
                        if file.is_file() and file.suffix == '.java':
                            shutil.copyfile(file, dir_group / file.name)

            if unhandled_any:
                print_error('There were unhandled files.')
                if suggestions:
                    print_error('Suggested name handlers:')
                    for id, suggestion in suggestions.items():
                        print_error('    {}: {},'.format(id, suggestion))
                exit(1)

        if copy_template and compile:
            print('Compiling...')
            for group, s in self.submissions.items():
                dir_group = dir_output / self.groups.group_details[group].name
                files_java = list(f for f in dir_group.iterdir() if f.suffix == '.java' if not f.name.startswith('.'))
    
                # Compile java files
                cmd = ['javac'] + [x.name for x in files_java]
                print('Compiling {}: {}'.format(self.groups.group_str(group), cmd))
                process = subprocess.run(cmd, cwd = dir_group) #, capture_output = True)

        if run_tests:
            print('Testing...')
            for group, s in self.submissions.items():
                dir_group = dir_output / self.groups.group_details[group].name
                tests = exec_simple(self.dir_test / 'tests_java.py').tests
                outputs = list()
                for test in tests:
                    cmd = ['java', test]
                    print('Testing {}: {}'.format(self.groups.group_str(group), cmd))
                    process = subprocess.run(cmd, cwd = dir_group, stdout = subprocess.PIPE, encoding = 'utf-8')
                    outputs.append(process.stdout)
                (dir_group / 'grading.txt').write_text('\n'.join(outputs))

        return file_mappings
