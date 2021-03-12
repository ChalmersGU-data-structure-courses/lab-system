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
lab3 = Lab(course, 4, bare = True)

lab2.print_unhandled_tests()
lab2.update_grading_repo()
lab2.robograde_tests()

lab3.print_unhandled_tests()
lab3.update_grading_repo()
lab3.robograde_tests()

lab4.print_unhandled_tests()
lab4.update_grading_repo()
lab4.robograde_tests()

lab1.update_submissions_and_gradings()
lab2.update_submissions_and_gradings()
lab3.update_submissions_and_gradings()
lab4.update_submissions_and_gradings()
