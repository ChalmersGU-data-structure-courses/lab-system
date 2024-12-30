#!/usr/bin/env python3
import logging
from pathlib import Path

import gitlab

import course
import gitlab_.tools  # noqa: E402
from util.this_dir import this_dir


logging.basicConfig(
    format="%(asctime)s %(levelname)s %(module)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.WARNING,
)
logger = logging.getLogger(__name__)

# pylint: disable-next=consider-using-from-import,wrong-import-position
import lp3.config as config


c = course.Course(config, this_dir / "lp3")

for user in c._gitlab_users.values():
    username = user.username
    if username.endswith("1") and not username.startswith("project"):
        cid = username.strip("1")
        print(f"    ('{cid}', '{username}'),")
