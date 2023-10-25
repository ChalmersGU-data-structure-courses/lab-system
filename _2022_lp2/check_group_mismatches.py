#!/usr/bin/env python3
from lp2.prelude import *

c.canvas_course_refresh()
c.canvas_group_set_refresh()
c.sync_students_to_gitlab(add = False, remove = False, restrict_to_known = False)
