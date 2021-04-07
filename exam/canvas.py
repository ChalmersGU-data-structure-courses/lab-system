import canvas
import functools
import general
import gitlab_config as config
import logging
import hashlib

import exam._2021_04_07_dat038_tdaa417_reexam.data as exam_config
import exam.allocate_versions
import exam.instantiate_template
from google_tools.drive import Drive
import google_tools.general

logger = logging.getLogger('exam.canvas')

class Exam:
    def __init__(self, exam_config):
        self.exam_config = exam_config
        self.randomized_questions = general.unique_list(question for (question, _) in self.exam_config.question_randomizers)
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
        return exam.allocate_versions.read(self.exam_config.allocations_file)

    @functools.cached_property
    def allocation_id_lookup(self):
        return dict((student, id) for (id, (student, _)) in self.allocations.items())

    def allocate_students(self):
        self.allocations = exam.allocate_versions.allocate(
            [user.sis_user_id for user in self.course.user_details.values()],
            dict((question, self.exam_config.max_versions) for question in self.randomized_questions),
            seed = 24782,
        )
        general.clear_cached_property('allocation_id_lookup')
        exam.allocate_versions.write(
            self.exam_config.allocations_file,
            self.allocations,
            lambda id: self.course.user_by_sis_id[id].name
        )

    def format_id(self, id):
        num_digits = len(str(len(self.allocations) - 1))
        return f'{id:0{num_digits}}'

    def instantiate_template(self, share_dir = None, share_url = None, solution = False):
        self.exam_config.instance_dir.mkdir(exist_ok = True)
        exam.instantiate_template.generate(
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
            output_types = ['pdf'] if solution else exam_formats,
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

    def exam_file_name(self, id, extension, solution = False):
        s = 'solution' if solution else 'exam'
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

    def upload_instance(user):
        logger.log(logging.INFO, f'Creating exam assignment for {course.user_str(user.id)}...')

        old_folder_id = self.course.get_folder_by_path(folder_name, use_cache = False)
        if old_folder_id != None:
            self.canvas.delete(['folders', old_folder_id])
        folder = self.course.create_folder(
            canvas_dir = self.instance_folder_path(user),
            locked = True,
        )

        id = self.allocation_id_lookup[user.sis_user_id]
        for format in self.exam_formats:
            file = general.add_suffix(self.exam_config.instance_dir / self.format_id(id) / 'exam', '.' + format)
            self.course.post_file(file, folder.id, self.exam_file_name(id, format))

    def upload_instances(users = None):
        if users == None:
            users = self.course.user_details.values()

        for user in users:
            self.upload_instance(user)

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

    def delete_assignments(self, use_cache = False):
        for user_id, assignment in self.get_assignments(use_cache = use_cache).items():
            logger.log(logging.INFO, f'Deleting exam assignment for {course.user_str(user_id)}...')
            self.course.delete_assignment(assignment.id)

    def create_assignment(self, user, publish = True):
        logger.log(logging.INFO, f'Creating exam assignment for {course.user_str(user.id)}...')

        folder = self.course.get_folder_by_path(self.instance_folder_path(user))
        has_extra_time = user.id in self.extra_time_students
        files = self.course.get_files(folder.id)

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
        return self.course.post_assignment(assignment)

    def create_assignments(self, users = None, publish = True):
        if users == None:
            assignments = self.get_assignments()
            users = [user for user in self.course.user_details.values() if not user.id in assignments]

        for user in users:
            self.create_assignment(user, publish = publish)

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

from pathlib import Path

share_dir = Path('/home/noname/DIT181/exam/uxul')
share_url = 'http://uxul.org/~noname/exam/'

e = Exam(exam_config)

#e.delete_canvas_instance_folder()
#e.create_canvas_instance_folder()
#e.upload_instances()
