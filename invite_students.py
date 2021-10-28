#!/usr/bin/python3
import importlib
import logging

from course import Course
from this_dir import this_dir

logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)

for prefix in ['java', 'python']:
    logging.root.info(f'Handling {prefix} course')

    config = importlib.import_module('.'.join([prefix, 'gitlab_config']))
    course = Course(config)
    course.logger.setLevel(logging.DEBUG)
    
    course.canvas_course_refresh()
    course.canvas_group_set_refresh()
    course.invite_students_to_gitlab(this_dir / prefix / 'student_invitations')
