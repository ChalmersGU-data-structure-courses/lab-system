#!/usr/bin/env python3
import logging
from pathlib import Path
import sys

sys.path.append(str(Path('__file__').parent / '..'))

import canvas  # noqa: E402

logging.basicConfig(
    format = '%(asctime)s %(levelname)s %(module)s: %(message)s',
    datefmt = '%Y-%m-%d %H:%M:%S',
    level = logging.WARN,
)
logger = logging.getLogger(__name__)

def id_chalmers_from_gu(id):
    return 122370000000000000 + id

def add_user(course, section_id, user_id):
    params = {
        'enrollment[user_id]': user_id,
        'enrollment[course_section_id]': section_id,
        'enrollment[type]': 'StudentEnrollment',
        'enrollment[enrollment_state]': 'active',
        'enrollment[notify]': 'true',
    }
    course.canvas.post(course.endpoint + ['enrollments'], params = params)

from gitlab_config_personal import canvas_auth_token  # noqa: E402
canvas_chalmers = canvas.Canvas('chalmers.instructure.com', auth_token = canvas_auth_token)
canvas_gu = canvas.Canvas('canvas.gu.se', auth_token = canvas_auth_token)

source_course = canvas.Course(canvas_gu, 65179, use_cache = False)
target_course = canvas.Course(canvas_chalmers, 23356, use_cache = False)

s = target_course.get_section('Added Manually')

for student in source_course.students:
    chalmers_id = id_chalmers_from_gu(student.id)
    if chalmers_id in target_course.user_details:
        logger.debug(f'{student.name} is already in course.')
    else:
        logging.warn(f'Adding {student.name} to course')
        add_user(target_course, s.id, chalmers_id)
