import logging

from gitlab_config_personal import *
import course

import dat525.config as config_dat525
import tda417.config as config_tda417

logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)

dat525 = course.Course(config_dat525, 'dat525')
tda417 = course.Course(config_tda417, 'tda417')

dat525_1 = dat525.labs[1]
tda417_1 = tda417.labs[1]

#l.sync_students_to_gitlab(add = True, remove = True)

#l.setup()
#l.repo_fetch_all()
#l.parse_request_tags(from_gitlab = False)
#l.parse_requests_and_responses(from_gitlab = False)
#l.process_requests()

#g = list(l.student_groups.values())[0]

# How to setup a new lab:
# 1. uncomment lab configuration in the config file
# 2. l = course_object.labs[lab_number]
# 3. l.gitlab_group.create()
# 4. l.official_project.create() (creates primary repository)
# 5. l.grading_project.create() (creates collection repository)
# 6. create java and python branches in primary repository (using sources from the labs repo)
# 7. point main branch to one of them (whatever should be the default)
# 8. start the event loop again, it should create repositories for each student/group
#    (alternative, call l.groups_create_desired()).
# 9. if lab has solution configured, "solve" the solution project
