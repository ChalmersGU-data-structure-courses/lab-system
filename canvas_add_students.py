import logging

import canvas.client_rest as canvas

from gitlab_config_personal import canvas.client_rest as canvas_auth_token

logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)


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

canvas_chalmers = canvas.Canvas('chalmers.instructure.com', auth_token = canvas_auth_token)
canvas_gu = canvas.Canvas('canvas.gu.se', auth_token = canvas_auth_token)

source_course = canvas.Course(canvas_gu, 65179, use_cache = False)
target_course = canvas.Course(canvas_chalmers, 23356, use_cache = False)

s = target_course.get_section('Added Manually')

for student in source_course.students:
    chalmers_id = id_chalmers_from_gu(student.id)
    if chalmers_id in target_course.user_details:
        print(f'{student.name} is already in course.')
    else:
        print(f'Adding {student.name} to course...')
        add_user(target_course, s.id, chalmers_id)
