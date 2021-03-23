import collections
import csv
import datetime
import dominate
import hashlib
import itertools
import logging
from pathlib import Path, PurePosixPath
import shlex

import canvas
import general

import gitlab_config as config

logging.basicConfig()
logging.getLogger().setLevel(logging.WARNING)

Format = collections.namedtuple('Format', field_names = ['extension', 'description'])

formats = [
#    Format(extension = 'txt', description = 'Text file'),
    Format(extension = 'docx', description = 'Word document'),
    Format(extension = 'odt', description = 'OpenDocument'),
    Format(extension = 'pdf', description = 'PDF, for reading'),
]

start = datetime.datetime.fromisoformat('2021-03-19 08:45+01:00')
duration = datetime.timedelta(hours = 4)
duration_scanning = datetime.timedelta(minutes = 30)
grace_period = datetime.timedelta(minutes = 0) # Canvas doesn't have second granularity.

extra_time_section = 'Students with extra time'
extra_time = 0.5

max_points = 18

def time_factor(has_extra_time = False):
    return 1 + (extra_time if has_extra_time else 0)

def due(has_extra_time = False):
    return start + time_factor(has_extra_time) * duration

def end(has_extra_time = False):
    return start + time_factor(has_extra_time) * (duration + duration_scanning + grace_period)

exam_dir = Path('/home/noname/DIT181/exam')

instance_dir = exam_dir / 'instances'

canvas_instance_dir = PurePosixPath('/Exam instances 2')

secret_salt = 'cypIjYzZbB4We0Mb'

def hash_salted(x):
    return hashlib.shake_256(bytes(x + secret_salt, encoding = 'utf-8')).hexdigest(length = 8)

# Make it less trivial to guess other people's exam files.
# Attackers can still iterate over all file ids.
def integration_id_with_hash(integration_id):
    return integration_id + '_' + hash_salted(integration_id)

def until_char(c, s):
    return ''.join(itertools.takewhile(lambda d: d != c, s))

def format_exam_name(integration_id, format):
    return 'exam-' + until_char('@', integration_id) + '.' + format.extension

use_cache = True

c = canvas.Canvas(config.canvas_url, auth_token = config.canvas_auth_token)

course = canvas.Course(c, config.canvas_course_id, use_cache = use_cache)
exam = canvas.Course(c, config.canvas_exam_course_id)

def add_extension(name, extension = None):
    name = str(name)
    return name if extension == None else str(name) + '.' + extension

import shutil
import random

def write_test_instances(course, dir):
    for format in formats:
        dir_format = dir / format.extension
        dir_format.mkdir()
        for user in course.user_details.values():
            r = random.Random(user.integration_id)
            i = r.choice(range(20))
            target = dir_format / add_extension(user.integration_id, format.extension)
            source = '/home/noname/DIT181/exam/{}/test.{}'.format(i, format.extension)
            shutil.copyfile(source, target)

# Make sure that exams are in correspondence to students.
def read_instances_format(course, format, dir):
    def helper():
        for file in dir.iterdir():
            if file.is_file():
                integration_id = file.stem
                assert integration_id in course.user_integration_id_to_id, 'stem of exam instance {} is not a student integration id'.format(shlex.quote(file.name))
                assert file.suffix == '.' + format.extension, 'file {} does not have suffix {}.'.format(file.name, format.extension)
                yield (course.user_integration_id_to_id[file.stem], file)

    instances = dict(helper())
    for user in course.user_details.values():
        assert user.id in instances, 'no exam instance of format {} found for student {} (integration id {})'.format(format.extension, course.user_str(user.id), user.integration_id)

    return instances

def read_instances(course, dir):
    by_format = dict((format.extension, read_instances_format(course, format, dir / format.extension)) for format in formats)

    def f(id):
        return dict((format.extension, by_format[format.extension][id]) for format in formats)
    return dict((id, f(id)) for id in course.user_details.keys())

#id = exam.get_dir_id(canvas_instance_dir, use_cache = False)
#if id != None:
#    print(id)
#    exam.delete_folder(id)

def get_extra_time_students(use_cache = False):
    section = exam.get_section(extra_time_section, use_cache = use_cache)
    students = exam.get_students_in_section(section.id, use_cache = use_cache)
    return frozenset(user.id for user in students)

def create_canvas_instance_folder(instances, extra_time_students):
    folder = exam.create_folder(canvas_instance_dir, hidden = 'true')
    def f():
        for user in exam.user_details.values():
            hashed_and_locked = exam.create_folder(
                canvas_instance_dir / integration_id_with_hash(user.integration_id),
                unlock_at = start,
                lock_at = end(user.id in extra_time_students),
            )

            def g():
                for format in formats:
                    file = instances[user.id][format.extension]
                    id = exam.post_file(file, hashed_and_locked.id, format_exam_name(user.integration_id, format))
                    yield (format.extension, id)
            yield (user.id, dict(g()))
    return dict(f())

instances = read_instances(exam, instance_dir)
extra_time_students = get_extra_time_students(use_cache = True)
#instances_on_canvas = create_canvas_instance_folder(instances, extra_time_students)



def print_folders():
    for x in exam.list_folders(use_cache = False):
        print('{}, {}: locked {}, hidden {}, unlock_at {}, lock_at {}'.format(x.id, x.full_name, x.locked, x.hidden, x.unlock_at, x.lock_at))

def delete_assignments():
    for a in exam.get_assignments(use_cache = False):
#        if a.name != 'Exam':
        exam.delete_assignment(a.id)

# Doesn't work. Why?
# Canvas API is cryptic in documentation for key assignment[assignment_overrides][] in editing an assignment:
# List of overrides for the assignment. If the assignment key is absent, any existing overrides are kept as is. If the assignment key is present, existing overrides are updated or deleted (and new ones created, as necessary) to match the provided list.
def update_assignment_times():
    for a in exam.get_assignments(include = ['overrides'], use_cache = False):
        if not a.overrides[0].student_ids:
            continue

        user_id = a.overrides[0].student_ids[0]
        user = exam.user_details[user_id]

        print(a.overrides[0].lock_at + ', ' + user.name)
        continue

        if 'Muntasir' in user.name:
            print(user.name)
            post_assignments(extra_time_students, instances_on_canvas, users = [user], overwrite_id = x.id)

def post_assignments(extra_time_students, instances_on_canvas, users = None, overwrite_id = None):
    from dominate.tags import strong, a, div, p, ul, li, span, style, td, th, thead, tr
    from dominate.util import raw, text

    if users == None:
        users = exam.user_details.values()

    def e():
        for user in users:
            def f(format):
                link = PurePosixPath('/') / 'courses' / str(exam.course_id) / 'files' / str(instances_on_canvas[user.id][format.extension])
                return li(a(format_exam_name(user.integration_id, format), href = str(link)), ' ({})'.format(format.description))
            description = div(
                p(strong('Note'), ': This exam is individualized! Your questions differ from those of other students, but are of equal difficulty.'),
                'Download your individual exam in one of the following formats:',
                ul(*[map(f, formats)]),
                p('Submit your solutions via file upload, preferably as a ', strong('single PDF file'), '. If you do not know how to convert your solutions to PDF, other formats are accepted as well. Please use separate pages for each question.'),
            )

            assignment = {
                'published': 'true',
                'name': 'Exam for {}'.format(user.name),
                'submission_types': ['online_upload'],
                'points_possible': max_points,
                'only_visible_to_overrides': True,
                'assignment_overrides': [{
                    'student_ids': [user.id],
                    'title': 'override title',
                    'unlock_at': start.isoformat(),
                    'lock_at': end(user.id in extra_time_students).isoformat(),
                    'due_at': due(user.id in extra_time_students).isoformat(),
                }],
                'description': description.render(pretty = False)
            }
            r = exam.edit_assignment(overwrite_id, assignment) if overwrite_id else exam.post_assignment(assignment).id
            yield (user.id, r)
    return dict(e())

submissions_dir = Path('/home/noname/DIT181/exam/submissions')
lookup_file = exam_dir / 'lookup.txt'

def download_submissions(dir, use_cache = True):
    for a in exam.get_assignments(include = ['overrides'], use_cache = use_cache):
        if not a.overrides[0].student_ids:
            continue

        user_id = a.overrides[0].student_ids[0]
        user = exam.user_details[user_id]

        submission = exam.get_submissions(a.id, use_cache = use_cache)[0]
        state = submission.workflow_state
        if state != 'unsubmitted' and user.integration_id == 'gusbrannsi@gu.se':
            dir_user = dir / user.integration_id
            general.mkdir_fresh(dir_user)
            for attachment in submission.attachments:
                exam.canvas.place_file(dir_user / canvas.Assignment.get_file_name(attachment), attachment)

            if len(submission.attachments) > 1:
                print(user.integration_id)

def write_lookup(course, submission_dir, lookup_file):
    lookup = dict((i, []) for i in range(20))
    for user in course.user_details.values():
        if (submissions_dir / user.integration_id).exists():
            r = random.Random(user.integration_id)
            i = r.choice(range(20))
            lookup[i].append(user)
    
    forward = dict((x.id, (i, j)) for (i, xs) in lookup.items() for (j, x) in enumerate(xs))
    with lookup_file.open('w') as file:
        csv.writer(file).writerows((i, j, course.user_details[id].integration_id, course.user_details[id].name) for (id, (i, j)) in forward.items())

def read_lookup(lookup_file):
    with lookup_file.open() as file:
        return list(csv.reader(file))

#x = post_assignments(extra_time_students, instances_on_canvas)
