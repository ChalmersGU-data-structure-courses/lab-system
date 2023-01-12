import datetime
import itertools
import logging
from pathlib import Path

import gitlab

from gql.transport.requests import RequestsHTTPTransport
from gql.dsl import dsl_gql, DSLSchema, DSLQuery, DSLInlineFragment

from gitlab_config_personal import canvas_auth_token, gitlab_private_token
import gitlab_tools

import canvas
import canvas_gql
import general
import gitlab_gql
import print_parse


#logging.basicConfig()
#logging.getLogger().setLevel(logging.DEBUG)

#c = canvas.Canvas('chalmers.instructure.com')
#client = canvas_gql.Client(c)

client = gitlab_gql.Client('git.chalmers.se', gitlab_private_token)

#c = canvas.Canvas('canvas.gu.se')


full_paths = [
    f'courses/dat151/group/{i:02d}/lab-2'
    for i in range(1, 28)
]

project_ids = [7208 + i for i in range(165)]

# with general.timing('retrieve_projects_members'):
#    print(client.retrieve_projects_members(project_ids))

gl = gitlab.Gitlab(
    'https://git.chalmers.se/',
    private_token = gitlab_private_token,
)
gl.auth()

with general.timing('issues'):
    x = list(client.retrieve_issues_in_project('courses/lp2-data-structures/groups/97/lab-3-python'))
    #x = list(client.f('courses/lp2-data-structures/groups', 'lab-3-python'))


# with general.timing('all users via REST one page'):
#    y = gl.users.list(order = 'id', sort = 'asc', asd = 3, page = 0, per_page = 100, get_all = False)

# with general.timing('all users via REST with get_all'):
#    r = gl.users.list(per_page = 100, get_all = True)

# with general.timing('all users via REST all pages'):
#    for i in itertools.count():
#       r = gl.users.list(page = i, per_page = 100, get_all = False)
#       if not r:
#          break
#    print(f'{i} pages')

# with general.timing('retrieve_all_users'):
#     client.retrieve_all_users()

# with general.timing('retrieve_all_users'):
#     client.retrieve_all_users()

# with general.timing('retrieve_all_users'):
#     client.retrieve_all_users()

# with general.timing('retrieve_all_users'):
#     client.retrieve_all_users()

# with general.timing('retrieve_all_users_from'):
#     users = list(client.retrieve_all_users_from())
#     print(len(users))

# with general.timing('retrieve_all_users_from'):
#    x = datetime.datetime.now()
#    client.retrieve_all_users_from(last_requested = x)

# with general.timing('members via REST'):
#     for g in range(1, 101):
#         gitlab_tools.list_all(gl.projects.get(
#             f'courses/lp2-data-structures/groups/{g:02d}/lab-1-java',
#             lazy = True,
#         ).members_all)

# with general.timing('queued query_project_members_direct'):
#     results = {
#         full_path: client.queue_query(client.query_project_members_direct(full_path))
#         for full_path in full_paths
#     }
#     client.flush_queue()
#     for (full_path, r) in results.items():
#         print(f'{full_path}: {r()}')

#r = client.q()
#print(r)


#result = client.client.execute(client.q())
#print(result)

# with general.timing('canvas.Course'):
#     x = canvas.Course(c, 21130, False)

# with general.timing('retrieve_course_users'):
#     x = client.retrieve_course_users(21130)

# with general.timing('CourseUsers'):
#     y = canvas_gql.CourseUsers(x)

# course_id = 20885
# group_set_name = 'Lab groups'

# with general.timing('retrieve_group_set_groups_and_members + GroupSet'):
#     a = canvas_gql.GroupSet((group_set_id, group_set_name, client.retrieve_group_set_groups_and_members(group_set_id)))

# with general.timing('retrieve_course_group_sets'):
#     group_sets = print_parse.from_dict(client.retrieve_course_group_sets(course_id))
#     group_set_id = group_sets.parse(group_set_name)

# with general.timing('retrieve_group_set_with_groups_and_members_via_name_in_course'):
#     b = canvas_gql.GroupSet(client.retrieve_group_set_with_groups_and_members_via_name_in_course(course_id, group_set_name))

# with general.timing('Course + GroupSet'):
#     course = canvas.Course(c, 21130, False)
#     group_set = canvas.GroupSet(course, 'Lab group', False)

#x = client.queue_query_node(client.ds.Course, 21130, client.ds.Course.name)
#client.flush_queue_node()
