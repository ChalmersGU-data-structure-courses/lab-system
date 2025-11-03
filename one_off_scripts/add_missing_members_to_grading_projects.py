import logging

from gitlab_config_personal import *
import course
import gitlab_tools

import dat151.config as config

logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)

c = course.Course(config, 'dat151')

l = c.labs[1]

l.setup()
l.parse_request_tags(from_gitlab = False)
l.parse_grading_merge_request_responses()
l.parse_requests_and_responses(from_gitlab = False)
l.process_requests()

def missing_members(g):
    desired = frozenset(x.id for x in g.members)
    actual = frozenset(x.id for x in gitlab_tools.list_all(g.grading_via_merge_request.project.lazy.members))
    if desired != actual:
        print(f'Difference in {g.name}:')
        print(f'  Desired: {desired}')
        print(f'  Actual: {actual}')
        g.grading_via_merge_request.add_students()

def missing_members_in_lab(l):
    for g in l.student_groups.values():
        if list(g.submissions()):
            missing_members(g)
    print('That is all.')

missing_members_in_lab(l)
