#!/usr/bin/env python3
import logging
from pathlib import Path
import sys

import gitlab

sys.path.append(str(Path('__file__').parent / '..'))

logging.basicConfig(
    format = '%(asctime)s %(levelname)s %(module)s: %(message)s',
    datefmt = '%Y-%m-%d %H:%M:%S',
    level = logging.WARNING,
)
logger = logging.getLogger(__name__)

import course
import gitlab_tools  # noqa: E402
import lp2.DAT525.config as config_525
import lp2.DAT038.config as config_038
import this_dir

c_525 = course.Course(config_525, this_dir.this_dir / 'lp2/DAT525')
c_038 = course.Course(config_038, this_dir.this_dir / 'lp2/DAT038')

for c in c_038:
  for user in c._gitlab_users.values():
      username = user.username
      if username.endswith('1') and not username.startswith('project'):
          cid = username.strip('1')
          print(f"    ('{cid}', '{username}'),")
