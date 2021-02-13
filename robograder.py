# Special import for git python.
import os
os.environ['GIT_PYTHON_TRACE'] = '1'
import git

from course import *
from lab import *

logger = logging.getLogger('robograder')

logging.basicConfig()
logger.setLevel(logging.DEBUG)

import gitlab_config
course = Course(gitlab_config)
lab = Lab(course, 2)

lab.print_unhandled_tests()

lab.update_grading_repo()
lab.robograde_tests()

lab.print_handled_tests()
