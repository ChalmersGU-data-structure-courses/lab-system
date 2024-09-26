import logging

from gitlab_config_personal import *
import course

import dat525.config as config_dat525
import tda417.config as config_tda417

import git_tools

logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)

dat525 = course.Course(config_dat525, 'dat525')
tda417 = course.Course(config_tda417, 'tda417')

dat525_3 = dat525.labs[3]
tda417_3 = tda417.labs[3]

#l = tda417_3
#g = l.groups[53]  # empty test group, empty as of Sep 24

#for g in l.groups.values():
#    g.hotfix_problem()

#l.sync_students_to_gitlab(add = True, remove = True)

#l.setup()
#l.repo_fetch_all()
#l.parse_request_tags(from_gitlab = False)
#l.parse_requests_and_responses(from_gitlab = False)
#l.process_requests()

#g = list(l.student_groups.values())[0]

# How to setup a new lab:
# 0. Make sure repository ~/labs is up to date (including robograder/robotester)
# 1. uncomment lab configuration in the config file
# 2. l = course_object.labs[lab_number]
# 3. l.create_initial_stuff_on_gitlab()
# 4. create java and python branches in primary repository (using sources from the labs repo)
# 5. point main branch to one of them (whatever should be the default)
# 6. start the event loop again, it should create repositories for each student/group
#    (alternative, call l.groups_create_desired()).
# 7. If lab has solution configured, "solve" the solution project:
#    * Upload a tag submission-solution-python for the solved Python version
#    * Upload a tag submission-solution-java for the solved Java version

# How to interact with the event loop:
# * Unit files are here:
#   - ~/.local/share/systemd/user/tda417.service
#   - ~/.local/share/systemd/user/dat525.service
# * After editing unit files, reload them using:
#     systemctl --user daemon-reload
# * Event loop can be controlled using:
#     systemctl --user start/stop/restart/status
# * Event loop log:
#     info level: journalctl --user-unit tda417
#     debug level: ~/lab-system/tda417/log/

# How to hotfix labs that are already shared with the students:
# Test this pull request: https://github.com/ChalmersGU-data-structure-courses/lab-system/pull/22
# 1. Call Lab.update_groups_problem to fast-forward the protected problem branches in the student groups.
# 2. Call Lab.merge_groups_problem_into_main to hotfix main branch in student projects.
