import logging

from gitlab_config_personal import *
import course

import dat151.config as config

logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)

c = course.Course(config, 'dat151')

l = c.labs[1]

#l.sync_students_to_gitlab(add = True, remove = True)

#l.setup()
#l.repo_fetch_all()
#l.parse_request_tags(from_gitlab = False)
#l.parse_requests_and_responses(from_gitlab = False)
#l.process_requests()

#g = list(l.student_groups.values())[0]
