# Special import for git python.
import os
os.environ['GIT_PYTHON_TRACE'] = '1'
import git

from course import *
from lab import *

logger = logging.getLogger('robograder')

logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)

import gitlab_config
course = Course(gitlab_config)

lab1 = Lab(course, 1, bare = True)
lab2 = Lab(course, 2, bare = True)
lab3 = Lab(course, 3, bare = True)

lab2.print_unhandled_tests()
lab2.update_grading_repo()
lab2.robograde_tests()
lab2.print_handled_tests()

lab1.update_submissions_and_gradings()
lab2.update_submissions_and_gradings()
lab3.update_submissions_and_gradings()
