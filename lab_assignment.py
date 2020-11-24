import shutil
import subprocess

from general import print_error, print_json
from canvas import Canvas, Course, Groups, Assignment
from submission_fix_lib import load_submission_fixes

class LabAssignment(Assignment):
    def __init__(self, canvas, course_id, assignment_id, dir):
        super().__init__(canvas, course_id, assignment_id)
        self.dir = dir
        self.dir_problem = dir / 'problem'
        self.dir_solution = dir / 'solution'
        self.dir_test = dir / 'test'
        self.file_submission_fixes = dir / 'submission_fixes.py'

        if self.file_submission_fixes.is_file():
            r = load_submission_fixes(self.file_submission_fixes)
            self.name_handlers = r.name_handlers
            self.content_handlers = r.content_handlers
        else:
            self.name_handlers = None
            self.content_handlers = None

        self.solution_files = dict((f.name, f) for f in self.dir_solution.iterdir() if f.is_file())

    def unpack_submissions(self, dir_output, previous = False, copy_template = False, copy_tests = False, compile = False):
        dir_output.mkdir()

        unhandled_any = False
        suggestions = dict()

        for group, s in self.submissions.items():
            dir_group = dir_output / self.groups.group_details[group].name
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
                    if f.is_file() and f.suffix == '.java':
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
