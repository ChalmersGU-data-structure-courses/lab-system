import canvas
import csv
import functools
import general
import gitlab_config as config
import gspread
import hashlib
import itertools
import logging
import operator
import PyPDF2
import shlex
import subprocess

from . import allocate_versions
from . import instantiate_template
from google_tools.drive import Drive
import google_tools.general

logger = logging.getLogger('exam.canvas')

class Exam:
    def __init__(self, exam_config):
        self.exam_config = exam_config

        x = frozenset(question for (question, _) in self.exam_config.question_randomizers)
        self.randomized_questions = [q for q in self.exam_config.questions if self.exam_config.question_key(q) in x]

        self.exam_formats = Drive.mime_types_document.keys()

    @functools.cached_property
    def canvas(self):
        return canvas.Canvas(self.exam_config.canvas_url, auth_token = config.canvas_auth_token)

    def get_course(self, use_cache):
        return canvas.Course(self.canvas, self.exam_config.canvas_room, use_cache = use_cache)

    @functools.cached_property
    def course(self):
        return self.get_course(use_cache = True)

    def refresh_course(self):
        self.course = self.get_course(use_cache = False)

    @functools.cached_property
    def allocations(self):
        return allocate_versions.read(self.exam_config.allocations_file)

    @functools.cached_property
    def allocation_id_lookup(self):
        return dict((student, id) for (id, (student, _)) in self.allocations.items())

    def allocate_students(self):
        self.allocations = allocate_versions.allocate(
            [user.sis_user_id for user in self.course.user_details.values()],
            dict((self.exam_config.question_key(q), self.exam_config.max_versions) for q in self.randomized_questions),
            seed = self.exam_config.allocation_seed,
        )
        general.clear_cached_property(self, 'allocation_id_lookup')
        allocate_versions.write(
            self.exam_config.allocations_file,
            self.allocations,
            lambda id: self.course.user_by_sis_id[id].name
        )

    def format_id(self, id):
        return general.format_with_leading_zeroes(id, len(self.allocations))

    def format_version(self, version):
        return general.format_with_leading_zeroes(version, self.exam_config.max_versions)

    def instantiate_template(self, share_dir = None, share_url = None, solution = False):
        self.exam_config.instance_dir.mkdir(exist_ok = True)
        instantiate_template.generate(
            self.exam_config.instance_dir,
            google_tools.general.get_token_for_scopes(['drive', 'documents']),
            exam_id = self.exam_config.exam_id,
            solution_id = self.exam_config.solution_id,
            questions = self.exam_config.question_randomizers,
            secret_salt = self.exam_config.secret_salt,
            student_versions = dict(
                (self.format_id(id), versions)
                for id, (student, versions) in self.allocations.items()
            ),
            solution = solution,
            output_types = ['pdf'] if solution else self.exam_formats,
            share_dir = share_dir,
            share_url = share_url,
        )

    def get_extra_time_students(self, use_cache = False):
        section = self.course.get_section(self.exam_config.canvas_extra_time_section, use_cache = use_cache)
        students = self.course.get_students_in_section(section.id, use_cache = use_cache)
        return frozenset(user.id for user in students)

    @functools.cached_property
    def extra_time_students(self):
        return self.get_extra_time_students(use_cache = True)

    def refresh_extra_time_students(self):
        self.extra_time_students = self.get_extra_time_students(use_cache = False)

    def time_factor(self, has_extra_time = False):
        return self.exam_config.canvas_extra_time if has_extra_time else 1

    def start(self, has_extra_time = False):
        return self.exam_config.canvas_start

    def due(self, has_extra_time = False):
        return self.exam_config.canvas_start + self.time_factor(has_extra_time) * self.exam_config.canvas_duration

    def end(self, has_extra_time = False):
        return self.exam_config.canvas_start + self.time_factor(has_extra_time) * (self.exam_config.canvas_duration + self.exam_config.canvas_duration_scanning + self.exam_config.canvas_grace_period)

    def create_canvas_instance_folder(self):
        self.course.create_folder(self.exam_config.canvas_instance_dir, hidden = 'true')

    def delete_canvas_instance_folder(self):
        self.course.delete_folder(self.exam_config.canvas_instance_dir)

    @staticmethod
    def exam_or_solution(solution = False):
        return 'solution' if solution else 'exam'

    def exam_file_name(self, id, extension, solution = False):
        s = Exam.exam_or_solution(solution)
        formatted_id = self.format_id(id)
        return f'{s}-version-{formatted_id}.{extension}'

    def salted_hash(self, x):
        return hashlib.shake_256(bytes(self.exam_config.secret_salt + '$' + x, encoding = 'utf-8')).hexdigest(length = 8)

    # Make it less trivial to guess other people's exam files.
    # Attackers can still iterate over all file ids.
    def with_salted_hash(self, s):
        return s + '_' + self.salted_hash(s)

    def instance_folder_name(self, user):
        return self.with_salted_hash(user.sis_user_id + '_' + user.name)

    def instance_folder_path(self, user):
        return self.exam_config.canvas_instance_dir / self.instance_folder_name(user)

    def upload_instance(self, user, delete_old = True, solution = False):
        s = Exam.exam_or_solution(solution)        
        logger.log(logging.INFO, f'Uploading {s} instance for {self.course.user_str(user.id)}...')

        folder = self.course.get_folder_by_path(self.instance_folder_path(user), use_cache = False)
        if folder != None and delete_old:
            self.canvas.delete(['folders', folder.id])
            folder = None
        if folder == None:
            folder = self.course.create_folder(
                canvas_dir = self.instance_folder_path(user),
                locked = True,
            )

        id = self.allocation_id_lookup[user.sis_user_id]
        for format in ['pdf'] if solution else self.exam_formats:
            file = general.add_suffix(self.exam_config.instance_dir / self.format_id(id) / s, '.' + format)
            self.course.post_file(file, folder.id, self.exam_file_name(id, format, solution = solution))

    def upload_instances(self, users = None, delete_old = True, solution = False):
        '''
        If delete_old is false, the old instance files are replaced.
        This automatically updates the links in already created assignments to point to the new files.
        '''
        if users == None:
            users = self.course.user_details.values()

        for user in users:
            self.upload_instance(user, delete_old = delete_old, solution = solution)

    def get_assignments(self, use_cache = False):
        def f(assignment):
            if assignment.overrides[0].student_ids:
                user_id = assignment.overrides[0].student_ids[0]
                user = self.course.user_details[user_id]
                yield (user_id, assignment)

        return dict(
            x
            for assignment in self.course.get_assignments(include = ['overrides'], use_cache = use_cache)
            for x in f(assignment)
        )

    @functools.cached_property
    def assignments(self):
        return self.get_assignments(use_cache = False)

    def delete_assignments(self, use_cache = False):
        for user_id, assignment in self.get_assignments(use_cache = use_cache).items():
            logger.log(logging.INFO, f'Deleting exam assignment for {self.course.user_str(user_id)}...')
            self.course.delete_assignment(assignment.id)

    def create_assignment(self, user, publish = True, update = False):
        logger.log(logging.INFO, f'Creating exam assignment for {self.course.user_str(user.id)}...')

        folder = self.course.get_folder_by_path(self.instance_folder_path(user))
        files = self.course.get_files(folder.id)
        has_extra_time = user.id in self.extra_time_students

        id = self.allocation_id_lookup[user.sis_user_id]
        def resource_for_format(extension):
            name = self.exam_file_name(id, extension)
            link = self.course.get_file_link(files[name].id)
            return (name, link)
        
        self.course.edit_folder(
            id = folder.id,
            locked = False,
            unlock_at = self.start(has_extra_time),
            lock_at = self.end(has_extra_time),
        )

        # We use end time for due time.
        # Students were confused about the earlier due time before and thought their submissions were late.
        assignment = {
            'published': publish,
            'name': 'Exam for {}'.format(user.name),
            'submission_types': ['online_upload'],
            'points_possible': self.exam_config.canvas_max_points,
            'post_manually': False,
            'only_visible_to_overrides': True,
            'assignment_overrides': [{
                    'student_ids': [user.id],
                    'title': 'override title',
                    'unlock_at': (self.start(has_extra_time) - self.exam_config.canvas_early_assignment_unlock).isoformat(),
                    'lock_at': self.end(has_extra_time).isoformat(),
                    'due_at': self.end(has_extra_time).isoformat(),
                }],
                'description': self.exam_config.canvas_assignment_description(resource_for_format)
            }

        if update:
            r = self.course.edit_assignment(self.assignments[user.id].id, assignment)
        else:
            r = self.course.post_assignment(assignment)
        return r

    def create_assignments(self, users = None, publish = True, update = False):
        '''
        If update is True, update existing assignments instead of creating new ones.
        '''
        if users == None:
            assignments = self.get_assignments()
            users = [user for user in self.course.user_details.values() if not user.id in assignments]

        for user in users:
            self.create_assignment(user, publish = publish, update = update)

    def set_instances_availability(self):
        for user in self.course.user_details.values():
            folder = self.course.get_folder_by_path(self.instance_folder_path(user))
            has_extra_time = user.id in self.extra_time_students
            self.course.edit_folder(
                id = folder.id,
                locked = False,
                unlock_at = self.start(has_extra_time),
                lock_at = self.end(has_extra_time),
            )

    def download_submissions(self, use_cache = False):
        self.exam_config.submissions_dir.mkdir(exist_ok = True)

        for (user_id, assignment) in self.get_assignments(use_cache = use_cache).items():
            if not assignment.overrides[0].student_ids:
                logger.log(logging.WARNING, f'Assignment {assignment.name} has no assigned student (typical cause: student unregistered from Canvas exam course).')
                continue

            user_id = assignment.overrides[0].student_ids[0]
            user = self.course.user_details[user_id]
            id = self.allocation_id_lookup[user.sis_user_id]
            logger.log(logging.INFO, f'Downloading latest submission for {assignment.name}')

            submission = self.course.get_submissions(assignment.id, use_cache = use_cache)[0]
            state = submission.workflow_state
            if state != 'unsubmitted':
                dir_submission = self.exam_config.submissions_dir / self.format_id(id)
                general.mkdir_fresh(dir_submission)
                for attachment in submission.attachments:
                    self.canvas.place_file(dir_submission / canvas.Assignment.get_file_name(attachment), attachment)
                if len(submission.attachments) != 1:
                    logger.log(logging.WARNING, f'Submission with not exactly one file: allocation id {self.format_id(id)}, {self.course.user_str(user.id)}')

    def list_submissions(self):
        for id in self.allocations:
            dir_submission = self.exam_config.submissions_dir / self.format_id(id)
            if dir_submission.exists():
                yield (id, dir_submission / 'submission.pdf')

    @functools.cached_property
    def submissions(self):
        return list(self.list_submissions())

    def normalize_submission(self, id):
        dir_submission = self.exam_config.submissions_dir / self.format_id(id)
        files = list(dir_submission.iterdir())
        if len(files) == 1:
            file = files[0]
            if file.suffix == '.pdf':
                file.rename(file.with_name('submission.pdf'))
                return

        logger.log(logging.WARNING, f'Could not normalize submission {self.format_id(id)}.')

    def normalize_submissions(self):
        for id, _ in self.submissions:
            self.normalize_submission(id)
        general.clear_cached_property(self, 'submissions')

    @staticmethod
    def format_range(range, adjust = False):
        (a, b) = range
        return f'{a + 1}-{b}'

    @staticmethod
    def parse_range(s):
        (a, b) = map(int, s.split('-'))
        return (a - 1, b)

    @staticmethod
    def format_ranges(ranges, adjust = False):
        if not ranges:
            return 'missing'
        return ','.join(map(lambda range: Exam.format_range(range, adjust = adjust), ranges))

    @staticmethod
    def parse_ranges(s):
        if s == 'missing':
            return []
        return list(map(Exam.parse_range, s.split(',')))

    def find_question_occurrences(self, file):
        logger.log(logging.INFO, f'Finding question title occurrences in {shlex.quote(str(file))}...')
        pdf = PyPDF2.PdfFileReader(str(file), strict = False)
        num_pages = pdf.getNumPages()
        keywords = dict((q, self.exam_config.question_name(q)) for q in self.exam_config.questions)

        def f(i):
            text = subprocess.run(
                ['pdftotext', '-f', str(i + 1), '-l', str(i + 1), str(file), '-'],
                stdout = subprocess.PIPE,
                encoding = 'utf-8',
                check = True
            ).stdout.strip()
            return [(q, i == 0) for (i, q) in general.find_all_many(keywords, text)]
        return [f(i) for i in range(num_pages)]

    @staticmethod
    def guess_selectors(questions, occurrences):
        r = dict((q, []) for q in questions)
        q_current = None
        s = None

        def start(i, q):
            nonlocal s, q_current
            s = i
            q_current = q

        def end(i):
            nonlocal s
            if s != None:
                r[q_current].append((s, i))
                s = None

        for i, qs in enumerate(occurrences):
            for (q, top) in qs:
                end(i if top else i + 1)
                start(i, q)

        end(len(occurrences))
        return r

    def guess_selector_info(self, file):
        occurrences = self.find_question_occurrences(file)
        if not list(itertools.chain.from_iterable(occurrences)):
            return ('enter', dict())

        selectors = Exam.guess_selectors(self.exam_config.questions, occurrences)
        starts_at_beginning = occurrences[0] and occurrences[0][0][1] == True
        questions_on_own_pages = all(not xs or xs[0][1] == True for xs in occurrences)
        starts_with_first_question = self.exam_config.questions or occurrences[0][0][0] == self.exam_config.questions[0]
        has_single_ranges = all(len(ranges) <= 1 for ranges in selectors.values())
        has_all_questions = all(len(ranges) >= 1 for ranges in selectors.values())

        verdict = 'standard' if all([
            starts_at_beginning,
            questions_on_own_pages,
            starts_with_first_question,
            has_single_ranges,
            has_all_questions,
        ]) else 'check'
        return (verdict, selectors)

    @functools.cached_property
    def solution_selectors(self):
        def f(id, _):
            solution_file = self.exam_config.instance_dir / self.format_id(id) / 'solution.pdf'
            (verdict, selectors) = self.guess_selector_info(solution_file)
            assert verdict == 'standard'
            return (id, selectors)

        return dict(itertools.starmap(f, self.submissions))

    def guess_selector_infos(self, dir):
        return dict(
            (id, self.guess_selector_info(file))
            for (id, file) in self.submissions
        )

    def read_selector_infos(self):
        lines = general.read_without_comments(self.exam_config.selectors_file)
        return dict(
            (int(entry['id']), (entry['type'], dict((int(k), Exam.parse_ranges(v)) for (k, v) in entry.items() if k.isdigit() if v != None)))
            for entry in csv.DictReader(lines, dialect = csv.excel_tab)
        )

    @functools.cached_property
    def selector_infos(self):
        return self.read_selector_infos()

    def write_selector_infos(self, selector_infos):
        with self.exam_config.selectors_file.open('w') as file:
            out = csv.DictWriter(file, fieldnames = ['id', 'type'] + list(map(str, self.exam_config.questions)), dialect = csv.excel_tab)
            out.writeheader()
            for (id, (type, selectors)) in selector_infos.items():
                out.writerow({'id': id, 'type': type} | dict((str(k), Exam.format_ranges(v)) for (k, v) in selectors.items()))
        self.selector_infos = selector_infos

    def check_selector_infos(self):
        for (id, _) in self.submissions:
            (type, selectors) = self.selector_infos[id]
            assert type in ['standard', 'okay', 'manual']

    def prepare_grading_table(self, out_path, fill_in_missing_questions = False):
        with out_path.open('w') as file:
            out = csv.writer(file)

            def process(
                id,
                question_score,
                question_version,
                question_feedback,
                question_comments
            ):
                def f():
                    yield id
                    for q in self.exam_config.questions:
                        yield question_score(q)
                        if q in self.randomized_questions:
                            yield(question_version(q))
                        yield question_feedback(q)
                        yield question_comments(q)
                out.writerow(list(f()))

            process(
                None,
                self.exam_config.question_name,
                lambda _: None,
                lambda _: None,
                lambda _: None,
            )

            process(
                'ID',
                lambda _: 'Score',
                lambda _: 'Version',
                lambda _: 'Feedback',
                lambda _: 'Comments',
            )

            for (id, _) in self.submissions:
                (student, versions) = self.allocations[id]

                def question_score(q):
                    if fill_in_missing_questions and self.selector_infos[id][1][q] == []:
                        return '-'
                    return None

                process(
                    id,
                    question_score,
                    lambda q: versions[self.exam_config.question_key(q)],
                    lambda _: None,
                    lambda _: None,
                )

    @staticmethod
    def extract_from_pdf(source, target, ranges):
        if ranges:
            cmd = ['pdfjam', '--keepinfo', '--outfile', str(target), str(source), Exam.format_ranges(ranges, adjust = True)]
            logger.log(logging.INFO, shlex.join(cmd))
            subprocess.run(cmd, check = True)

    def extract_question_submission(self, dir, file, id, q):
        Exam.extract_from_pdf(file, dir / (self.format_id(id) + '.pdf'), self.selector_infos[id][1][q])

    def package_question(self, dir, q, include_solutions):
        logger.log(logging.INFO, f'Packaging question {q}...')
        for (id, file) in self.submissions:
            self.extract_question_submission(dir, file, id, q)

    def package_randomized_question(self, dir, q, include_solutions):
        logger.log(logging.INFO, f'Packaging question {q} (randomized)...')
        for (id, file) in self.submissions:
            version = self.allocations[id][1][self.exam_config.question_key(q)]
            dir_version = dir / ('version-' + self.format_version(version))
            if not dir_version.exists():
                dir_version.mkdir()
                if include_solutions:
                    Exam.extract_from_pdf(
                        self.exam_config.instance_dir / self.format_id(id) / 'solution.pdf',
                        dir_version / 'solution.pdf',
                        self.solution_selectors[id][q]
                    )
            self.extract_question_submission(dir_version, file, id, q)

    def package_submissions(self, include_solutions = True):
        dir = self.exam_config.submissions_packaged_dir
        general.mkdir_fresh(dir)
        for q in self.exam_config.questions:
            dir_question = dir / self.exam_config.question_key(q)
            dir_question.mkdir()
            f = self.package_randomized_question if q in self.randomized_questions else self.package_question
            f(dir_question, q, include_solutions)

    @functools.cached_property
    def gradings(self):
        worksheet = gspread.oauth().open_by_key(self.exam_config.grading_sheet).get_worksheet(0)
        rows = worksheet.get_all_values() #value_render_option = 'FORMULA'
        grading_lookup = self.exam_config.GradingLookup(self.exam_config.grading_rows_headers(rows))

        def process_row(row):
            v = row[grading_lookup.id()]
            if v:
                id = int(v)

                def process_question(q):
                    score = self.exam_config.parse_score(row[grading_lookup.score(q)])
                    feedback = row[grading_lookup.feedback(q)]
                    return (score, feedback)

                yield (id, dict((q, process_question(q)) for q in self.exam_config.questions))

        return dict(x for row in self.exam_config.grading_rows_data(rows) for x in process_row(row))

    def write_grading_report_for_users(self, output, users):
        def row(user):
            output = [user.sis_user_id, user.sortable_name]
            output.append('{:.5g}'.format(self.exam_config.points_basic(grading)) if grading else '-')
            output.append('{:.5g}'.format(self.exam_config.points_advanced(grading)) if grading else '-')
            output.append('{result.grade}'.format(self.exam_config.grade(grading)) if grading else '-')
            return output

        with output.open('w') as file:
            out = csv.DictWriter(file, fieldnames = ['ID', 'Name'] + [key for (key, _) in self.exam_config.grading_report_columns])
            out.writeheader()
            for user in users:
                id = self.allocation_id_lookup.get(user.sis_user_id)
                grading = self.gradings.get(id) if id != None else None
                def f():
                    yield ('ID', user.sis_user_id)
                    yield ('Name', user.name)
                    for (key, h) in self.exam_config.grading_report_columns:
                        yield (key, h(grading) if grading else None)
                out.writerow(dict(f()))

    def write_grading_report(self, output, include_non_allocations = True, include_non_submissions = True):
        def include(user):
            id = self.allocation_id_lookup.get(user.sis_user_id)
            if id == None:
                return include_non_allocations

            grading = self.gradings.get(id)
            if grading == None:
                return include_non_submissions

            return True

        students = [user for user in self.course.user_details.values() if include(user)]
        students.sort(key = operator.attrgetter('sortable_name'))
        self.write_grading_report_for_users(output, students)

    def upload_grading(self, user, replace_author_name = None):
        logger.log(logging.INFO, f'Uploading grading for {self.course.user_str(user.id)}...')

        id = self.allocation_id_lookup.get(user.sis_user_id)
        if id == None:
            logger.log(logging.INFO, f'No allocation.')
            return

        grading = self.gradings.get(id)
        if not grading:
            logger.log(logging.INFO, f'No grading.')
            return

        assignment = self.assignments[user.id]
        folder = self.course.get_folder_by_path(self.instance_folder_path(user))
        files = self.course.get_files(folder.id)

        def resource(solution):
            name = self.exam_file_name(id, 'pdf', solution = solution)
            link = self.course.get_file_link(files[name].id, absolute = True)
            return (name, link)

        self.course.edit_folder(
            id = folder.id,
            locked = False,
            unlock_at = None,
            lock_at = None,
        )

        submission = general.from_singleton(self.course.get_submissions(assignment.id, use_cache = False))
        assert submission.workflow_state != 'unsubmitted'
        if replace_author_name or submission.workflow_state != 'graded':
            if replace_author_name:
                for comment in submission.submission_comments:
                    if comment.author_name == replace_author_name:
                        self.canvas.delete(self.course.endpoint + ['assignments', assignment.id, 'submissions', user.id, 'comments', comment.id])
            endpoint = self.course.endpoint + ['assignments', assignment.id, 'submissions', user.id]
            params = {
                'comment[text_comment]': self.exam_config.grading_feedback(grading, resource),
                'submission[posted_grade]': self.exam_config.grading_score(grading),
            }
            print(self.exam_config.grading_score(grading))
            print(self.exam_config.grading_feedback(grading, resource))
            self.canvas.put(endpoint, params = params)

    def upload_gradings(self, users = None, replace_author_name = None):
        if users == None:
            users = self.course.user_details.values()

        for user in users:
            self.upload_grading(user, replace_author_name = replace_author_name)

