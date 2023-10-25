import logging

from gitlab_config_personal import *
import course

import lp2.DAT038.config as config_038
import lp2.DAT525.config as config_525

logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)

# DAT038
c_038 = course.Course(config_038, 'lp2/DAT038')

# DAT525
c_525 = course.Course(config_525, 'lp2/DAT525')

courses = [c_525, c_038]

l1_525 = c_525.labs[1]
l1_038 = c_038.labs[1]

current_labs = [l1_525, l1_038]
#l.sync_students_to_gitlab(add = True, remove = True)

#l.setup()
#l.repo_fetch_all()
#l.parse_request_tags(from_gitlab = False)
#l.parse_requests_and_responses(from_gitlab = False)
#l.process_requests()

#g = list(l.student_groups.values())[0]
