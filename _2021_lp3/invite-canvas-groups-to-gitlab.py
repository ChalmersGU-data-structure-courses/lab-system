#!/usr/bin/env python3

import json
import gitlab
from pathlib import Path

from util.general import print_json
from canvas import Canvas, Course, GroupSet


canvas_url = 'canvas.gu.se'
course_id = 42575
group_set = 'Lab groups'

use_cache = False
#use_cache = True
update = use_cache
#update = False

canvas = Canvas(canvas_url)
course = Course(canvas, course_id, use_cache = use_cache)
group_set = GroupSet(course, group_set, use_cache = use_cache)

invitation_file = Path(__file__).parent / 'invitations_sent'

def get_invitations():
    if not invitation_file.exists():
        return dict()

    with invitation_file.open() as file:
        return dict(json.load(file))

def set_invitations(invitations):
    with invitation_file.open('w') as file:
        return json.dump(list(invitations.items()), file)

invitations = get_invitations()

group_ids = invitations.keys() | group_set.details.keys()

for group in group_ids:
    old = invitations.get(group, [])
    new = group_set.group_users.get(group, [])

    def print_desc(desc, ids):
        if ids:
            print('{} members of {}:'.format(desc, group_set.details[group].name))
            for user in ids:
                user_details = course.user_details[user]
                print(user_details.name, ': ', user_details.email)

    minus = list(set(old) - set(new))
    print_desc('Leaving', minus)

    plus = list(set(new) - set(old))
    print_desc('Coming', plus)

    invitations[group] = list(new)

    #print_desc('All', new)

if update:
    set_invitations(invitations)

exit()

def username_from_email(s):
    return s.split('@')[0]

users_by_keys = dict((user.name.split(' ')[0].lower(), user) for user in course.students)

for user in course.students:
    if not username_from_email(user.email) == user.login_id:
        print_json(user)

#file_token = Path(__file__).parent / 'gitlab_access_token'
file_token = Path('gitlab_access_token')

print('Authenticating...')
gl = gitlab.Gitlab('https://git.chalmers.se/', private_token = file_token.read_text())
gl.auth()

u = gl.users
gitlab_users_by_username = dict((user.username, user) for user in u.list(all = True))
