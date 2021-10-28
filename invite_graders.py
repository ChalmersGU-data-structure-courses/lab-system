#!/usr/bin/python3
import logging

from course import Course
import java.gitlab_config as config
from this_dir import this_dir

logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)

# The Java and Python courses share a single graders group.
# This is managed by the Java course.
course = Course(config)
course.logger.setLevel(logging.DEBUG)

course.canvas_course_refresh()
course.invite_teachers_to_gitlab(this_dir / 'teacher_invitations')
