#!/usr/bin/python3
#
# If you run this script in a loop, change the logging level
# to logging.WARNING and pipe the error output into a log file, e.g.
#   while [[ 1 ]]; do ./invite_students.py 2>>invite_students_log; sleep 300; done
# That way, the log file won't contain repeating redundant entries.

from prelude import *

import importlib
import logging

from course import Course
from lab import StudentConnectorIndividual, StudentConnectorGroupSet

logging.basicConfig(
    format = '%(asctime)s %(levelname)s %(module)s: %(message)s',
    datefmt = '%Y-%m-%d %H:%M:%S',
)
logging.getLogger().setLevel(25)  # 25: between INFO and WARNING

for c in courses:
    c.canvas_course_refresh()

for l in current_labs:
  if isinstance(l.student_connector, StudentConnectorGroupSet):
      l.student_connector.group_set.canvas_group_set_refresh()
  l.create_groups_from_canvas()
  l.create_group_projects(exist_ok = True)
  l.sync_students_to_gitlab(add = True, remove = True, restrict_to_known = True)
