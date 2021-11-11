import logging

from course import Course
from this_dir import this_dir

logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)

import java.gitlab_config as config_java
course_java = Course(config_java, dir = this_dir / 'java')

import python.gitlab_config as config_python
course_python = Course(config_python, dir = this_dir / 'python')



# for lab in course_java.labs.values():
#     print(".");
#     for group in course_java.groups:
#         course_python.configure_student_project(lab.student_group(group).project.get)

# print("\n");
        
# for lab in course_python.labs.values():
#     print(".")
#     for group in course_python.groups:
#         course_python.configure_student_project(lab.student_group(group).project.get)
