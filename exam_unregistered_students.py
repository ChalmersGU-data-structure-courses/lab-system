import canvas

import gitlab_config as config


use_cache = False

c = canvas.Canvas(config.canvas_url, auth_token = config.canvas_auth_token)

course = canvas.Course(c, config.canvas_course_id, use_cache = use_cache)
exam = canvas.Course(c, config.canvas_exam_course_id, use_cache = use_cache)

# Needs to be restricted to students.
#print(set(exam.user_name_to_id) - set(course.user_name_to_id))
#print(set(course.user_name_to_id) - set(exam.user_name_to_id))

#for x in set(exam.student_ids) - set(course.student_ids):
#    v = exam.user_details[x]
#    print(v.name + ': ' + v.integration_id)

for v in exam.students:
    if v.enrollments[0].enrollment_state == 'invited':
        print(v.name + ': ' + v.integration_id + (' ' + v.email if hasattr(v, 'email') else ''))

#old_course = canvas.Course(c, 10681, use_cache)
