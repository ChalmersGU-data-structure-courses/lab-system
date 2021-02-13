import itertools
import gitlab
from pathlib import Path

from general import *
from this_dir import this_dir

id_group_dit = 1319

print('Authenticating...')
gl = gitlab.Gitlab('https://git.chalmers.se/', private_token = 'REDACTED_PRIVATE_TOKEN')
gl.auth()

#u = gl.users
#for user in itertools.islice(u.list(all = True), 1000000):
#    print(user.attributes)
#    print("{}: {}, {}, {}".format(user.id, user.name, user.username, user.email if 'email' in user.attributes else str(None)))
#exit()

#print(gl.user)

group_dit = gl.groups.get(id_group_dit)

#print(group_dit)

def get_lab_groups():
    return dict(((int(subgroup.name.split()[2])), gl.groups.get(subgroup.id))
        for subgroup in group_dit.subgroups.list(all = True)
        if subgroup.name.lower().startswith('lab group')
    )

def delete_lab_groups():
    for group in get_lab_groups().values():
        print('Deleting group {}'.format(group.name))
        group.delete()

def create_lab_groups(n):
    current_lab_groups = get_lab_groups()
    for i in range(n):
        if i not in current_lab_groups:
            r = gl.groups.create({
                'name': 'Lab Group {}'.format(i),
                'path': 'lab_group_{}'.format(i),
                'parent_id': id_group_dit,
                'default_branch_protection': 1,  # Developers and maintainers can push new commits
                'project_creation_level': 'maintainer',
                'subgroup_creation_level': 'owner',
            })
            print(r)

def get_subgroup(path):
    xs = [gl.groups.get(subgroup.id, lazy = True) for subgroup in group_dit.subgroups.list(all = True) if subgroup.path == path]
    return xs[0] if xs else None

def get_template_group():
    return get_subgroup('lab_templates')

def create_template_group():
    if not get_template_group():
        r = gl.groups.create({
            'name': 'Lab templates',
            'path': 'lab_templates',
            'parent_id': id_group_dit,
         })
        print(r)
        
def create_lab_project(group, k, dir):
    project = gl.projects.create({
        'name': 'Lab {}'.format(k),
        'path': 'lab{}'.format(k),
        'namespace_id': group.id,
    })
    print(project)

projects = gl.projects.list(owned = True, all = True)
#for p in projects:
#    print(p.path_with_namespace)

def get_project(path):
    id = from_singleton_maybe(p.id for p in projects if p.path_with_namespace == path)
    if not id:
        return None

    return gl.projects.get(id)

def fork_lab_project(lab, groups):
    p = get_project('courses/dit181/lab_templates/lab{}'.format(lab))
    print(p.forks)

    for group in groups:
        print('forking {} to {}...'.format(p.name, group.name))
        try:
            q = p.forks.create({'namespace': group.id})
            print('forked {} to {}'.format(p.name, group.name))
        except gitlab.exceptions.GitlabCreateError:
            print('skipping already created project for group {}'.format(group.name))
            continue

def make_students_developers():
    lab_groups = get_lab_groups()
    for n, group in lab_groups.items():
        for user in group.members.list():
            if user.access_level != gitlab.OWNER_ACCESS:
                if user.access_level != gitlab.DEVELOPER_ACCESS:
                    print(f'changing rights of {user.name} in {group.name} to developer...')
                    user.access_level = gitlab.DEVELOPER_ACCESS
                    user.save()

def check_submissions(lab):
    lab_groups = get_lab_groups()
    for n, group in lab_groups.items():
        project = gl.projects.get(from_singleton(p.id for p in group.projects.list() if p.path == f'lab{lab}'))
        for tag in project.tags.list():
            print(f'Lab group {n} has a tag {tag.name} for Lab {lab}')
            print(f'message: {tag.message}')

def print_tags(lab, lab_groups):
    for n in range(45):
        group = lab_groups[n]
        project = get_project('{}/lab{}'.format(group.full_path, lab))
        tags = project.tags.list()
        #print(f'{group.name}:', *[tag.name for tag in tags])
        if tags:
            tag_name = tags[0].name
            #print(f'https://git.chalmers.se/courses/dit181/lab_group_{n}/lab1/-/tree/{tag_name}')
            print(f'https://git.chalmers.se/courses/dit181/lab_group_{n}/lab1/-/compare/fb30e73b...{tag_name}?view=parallel')
        else:
            print('-')

def get_tags(lab, lab_groups):
    r = dict()
    for n in range(45):
        group = lab_groups[n]
        project = get_project('{}/lab{}'.format(group.full_path, lab))
        tags = project.tags.list()
        if tags:
            r[n] = tags[0].name
    return r

#lab_groups = get_lab_groups()
#tags = get_tags(1, lab_groups)

repo = Path('/home/noname/DIT181/lab1')

def create_submission_branch(n, tag):
    subprocess.run(['git', 'fetch', '--tags', '--force', '--prune', 'g{}'.format(n)], cwd = repo, check = True)
    subprocess.run(['git', 'branch', 'group-{}'.format(n), tag], cwd = repo, check = True)

#for n, tag in tags.items():
#    if n >= 8:
#        subprocess.run(['git', 'push', 'origin', 'group-{}'.format(n)], cwd = repo, check = True)
    

#print_tags(1, lab_groups)

# If Chalmers GitLab had the Invitations API...
#import requests

#session = requests.Session()
#session.headers.update({'PRIVATE-TOKEN': '{}'.format(file_token.read_text())})

#def invite(group, level, email_addresses):
#    r = session.post('https://git.chalmers.se/api/v4/groups/{}/invitations'.format(group), data = {
#        'access_level' : level,
#        'email': ','.join(email_addresses),
#    })
#    r.raise_for_status()
#    print_json(r.json())


#fork_lab_project(1, [lab_groups[44]])
#exit()

#create_lab_project(get_template_group(), 1, Path('/home/noname/datastructures/code/lab1/problem'))
#p = get_project('courses/dit181/lab_group_24/lab1')
#add_protection_levels(p)
#fork_lab_project(1)

#p = get_project('courses/dit181/lab_group_44/lab1')
#print(p)
#protect_master(p)
#b = p.branches.get('master')
#b.protect(developers_can_push = True, developers_can_merge = True)
#b = p.protectedbranches.get('master')
#print(b.__dir__())

#for i, group in get_lab_groups().items():
#    print(i)
#    p = get_project('courses/dit181/lab_group_{}/lab{}'.format(i, 1))
#    protect_master(p)
