import http_logging
import logging

from general import OpenWithNoModificationTime, print_json
from canvas import Canvas, Course, Groups, Assignment

#logging.basicConfig()
#logging.getLogger().setLevel(logging.INFO)

canvas = Canvas('chalmers.instructure.com')
course_id = 10681
group_set = 5387 # inferrable from assignment
assignment_id = 'lab 1' #23431

canvas = Canvas('chalmers.instructure.com')
course = Course(canvas, course_id)
groups = Groups(canvas, course_id, group_set)
assignment = Assignment(canvas, course_id, assignment_id)

def user_details(username):
    print('Listing users matching \'{}\':'.format(username))
    for u in groups.user_name_to_id:
        if username.lower() in u.lower():
            user = groups.user_name_to_id[u]
            print('  {} is in {}.'.format(groups.user_str(user), groups.group_str(groups.user_to_group[user]) if user in groups.user_to_group else 'no group.'))

def group_details(groupname):
    groupname = str(groupname)
    print('Listing groups matching \'{}\':'.format(groupname))
    for g in groups.group_name_to_id:
        if g.lower() in [x.lower() for x in [groupname, groups.group_prefix + groupname]]:
            group = groups.group_name_to_id[g]
            print('  {} has members:'.format(groups.group_str(group)))
            for user in groups.group_users[group]:
                print('    {}'.format(groups.user_str(user)))
