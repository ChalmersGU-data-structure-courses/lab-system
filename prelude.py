# ACTION to get started:
# * See README.md for general information.
# * Instantiate template/secrets.toml as secrets.toml.
# * Replace <course code> by sensible folder name.
# * Instantiate template/config.py as <course code>/config.py.
# * If you want to use systemd to run the event loop:
#   - Instantiate template/lab-system.service as <course code>/lab-system.service.
#   - Create a symlink to this in e.g. ~/.local/share/systemd/user.

import logging
from pathlib import Path

# pylint: disable=unused-import
from course import Course
from lab_interfaces import CourseAuth


logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)

auth = CourseAuth.from_secrets(Path("secrets.toml"))


# ACION: instantiate and uncomment below statements for concrete instance.
# pylint: disable=wrong-import-position
from dat516.config import course as config

print("Defined variables:")

c = Course(auth=auth, config=config, dir=Path("dat516"))
print(f"  c: {c}")

(lab1, lab2, lab3) = c.labs.values()
print(f"  lab1: {lab1}")
print(f"  lab2: {lab2}")
print(f"  lab3: {lab3}")

# Find group number from student name
from lab import Lab
def find_group_number(lab: Lab, name: str):
  for group in lab.groups.values():
    for member in group.members:
      if name in member.name:
        print('🟢', group.name, member.name)

# How to deploy a lab in the data structure course cluster:
# 1. Make sure repository ~/labs is up to date.
# 2. Run `make problem solution robotester-python` in the labs repository.
# 3. Uncomment lab configuration in the config file <course code>/config.py
# 4. Deploy the lab l: l.deploy_via_lab_sources_and_canvas()
# 5. To start from scratch: l.remove(force=True)

# How to interact with the event loop:
# * Unit files are here:
#   - ~/.local/share/systemd/user/lab-system.service
# * After editing unit files, reload them using:
#     systemctl --user daemon-reload
# * Event loop can be controlled using:
#     systemctl --user start/stop/restart/status
# * Event loop log:
#     info level: journalctl --user-unit lab-system
#     debug level: ~/lab-system/<course code>/log/

# How to hotfix labs that are already shared with the students:
# 1. Call Lab.update_groups_problem to fast-forward the protected problem branches in the student groups.
# 2. Call Lab.merge_groups_problem_into_main to hotfix main branch in student projects.

# Manual syncing of students from Canvas:
# l.sync_students_to_gitlab(add=True, remove=True)

# Manual processing of submissions:
# l.setup()
# l.initial_run()
