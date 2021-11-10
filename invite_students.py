#!/usr/bin/python3
#
# If you run this script in a loop, change the logging level
# to logging.WARNING and pipe the error output into a log file, e.g.
#   while [[ 1 ]]; do ./invite_students.py 2>>invite_students_log; sleep 600; done
# That way, the log file won't contain repeating redundant entries.

import importlib
import logging

from course import Course
from this_dir import this_dir

import java.gitlab_config as config_java
course_java = Course(config_java, dir = this_dir / 'java')

import python.gitlab_config as config_python
course_python = Course(config_python, dir = this_dir / 'python')

logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)

logging.root.info('Handling java course')
course_java.canvas_course_refresh()
course_java.canvas_group_set_refresh()
course_java.sync_students_to_gitlab(add = True, remove = True, restrict_to_known = True)

logging.root.info('Handling python course')
course_python.canvas_course_refresh()
course_python.canvas_group_set_refresh()
course_python.sync_students_to_gitlab(add = True, remove = True, restrict_to_known = True)


# for prefix in ['java', 'python']:
#     logging.root.info(f'Handling {prefix} course')

#     #print('.'.join([prefix, 'gitlab_config']))
#     #config = importlib.import_module('.'.join([prefix, 'gitlab_config']))
    
    
#     #course = Course(config)
#     # If you want to see debug messages only for the course module, use:
#     # course.logger.setLevel(logging.DEBUG)
    
#     course.canvas_course_refresh()
#     course.canvas_group_set_refresh()
#     course.sync_students_to_gitlab(add = True, remove = True, restrict_to_known = True)
