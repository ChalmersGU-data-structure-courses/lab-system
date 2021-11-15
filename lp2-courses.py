import logging

from course import Course
from this_dir import this_dir

logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)

import java.gitlab_config as config_java
course_java = Course(config_java, dir = this_dir / 'java')

import python.gitlab_config as config_python
course_python = Course(config_python, dir = this_dir / 'python')
