#!/usr/bin/env python3
import logging
from pathlib import Path
import sys
import time

sys.path.append(str(Path("__file__").parent / ".."))

import canvas.client_rest as canvas  # noqa: E402
import util.general  # noqa: E402

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(module)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.WARNING,
)
logger = logging.getLogger(__name__)

from gitlab_config_personal import canvas_auth_token  # noqa: E402

c = canvas.Canvas("chalmers.instructure.com", auth_token=canvas_auth_token)
course_id = 23356
desired_name = "LP3 Data structures and algorithms"
desired_course_code = "DIT182 and DAT495"

while True:
    details = c.get(["courses", course_id], use_cache=False)
    if not (
        details.name == desired_name and details.course_code == desired_course_code
    ):
        logger.warning(
            util.general.join_lines(
                [
                    "Course details changed:",
                    f"* name: {details.name}",
                    f"* course code: {details.course_code}",
                ]
            )
        )
        c.put(
            ["courses", course_id],
            {
                "course[name]": desired_name,
                "course[course_code]": desired_course_code,
            },
        )
    time.sleep(10)
