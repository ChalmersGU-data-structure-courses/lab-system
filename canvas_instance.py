import logging

from general import OpenWithNoModificationTime, print_json
from canvas import Canvas, Course, GroupSet, Assignment

logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)

canvas = Canvas('chalmers.instructure.com')
course_id = 10681
group_set = 5387 # inferrable from assignment
assignment_id = 'lab 2' #23431

canvas = Canvas('chalmers.instructure.com')
course = Course(canvas, course_id)
group_set = GroupSet(canvas, course_id, group_set)
assignment = Assignment(canvas, course_id, assignment_id)

def user_details(username):
    print('Listing users matching \'{}\':'.format(username))
    for u in group_set.user_name_to_id:
        if username.lower() in u.lower():
            user = group_set.user_name_to_id[u]
            print('  {} is in {}.'.format(group_set.user_str(user), group_set.group_str(group_set.user_to_group[user]) if user in group_set.user_to_group else 'no group.'))

def group_details(groupname):
    groupname = str(groupname)
    print('Listing groups matching \'{}\':'.format(groupname))
    for g in group_set.group_name_to_id:
        if g.lower() in [x.lower() for x in [groupname, group_set.group_prefix + groupname]]:
            group = group_set.group_name_to_id[g]
            print('  {} has members:'.format(group_set.group_str(group)))
            for user in group_set.group_users[group]:
                print('    {}'.format(group_set.user_str(user)))
