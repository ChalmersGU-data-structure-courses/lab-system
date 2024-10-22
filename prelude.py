import logging

from gitlab_config_personal import *
import course

logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)

# ACTION to get started:
# * See README.md for general information.
# * Replace <course code> by sensible folder name.
# * Instantiate gitlab_config.py.template as <course code>/config.py.
# * If you want to use systemd to run the event loop:
#   Instantiate systemd_unit_file.service.template as e.g. <course code>/lab-system.service.

import lp2.config as config
c = course.Course(config, 'lp2')
l = c.labs[1]

# How to deploy a new lab:
# 1. Make sure repository ~/labs is up to date.
# 2. Run `make problem solution` in the labs repository.
# 3  Uncomment lab configuration in the config file lp2/config.py
# 4. Deploy the lab l: l.deploy()
# 5. To start from scratch: l.gitlab_group.delete().

# How to interact with the event loop:
# * Unit files are here:
#   - ~/.local/share/systemd/user/lab-system.service
# * After editing unit files, reload them using:
#     systemctl --user daemon-reload
# * Event loop can be controlled using:
#     systemctl --user start/stop/restart/status
# * Event loop log:
#     info level: journalctl --user-unit lab-system
#     debug level: ~/lab-system/lp2/log/

# How to hotfix labs that are already shared with the students:
# 1. Call Lab.update_groups_problem to fast-forward the protected problem branches in the student groups.
# 2. Call Lab.merge_groups_problem_into_main to hotfix main branch in student projects.

# Manual syncing of students from Canvas:
#l.sync_students_to_gitlab(add = True, remove = True)

# Manual processing of submissions:
#l.setup()
#l.repo_fetch_all()
#l.parse_request_tags(from_gitlab = False)
#l.parse_requests_and_responses(from_gitlab = False)
#l.process_requests()
