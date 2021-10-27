import functools
import general
import gitlab
import logging
from pathlib import Path, PurePosixPath
import time

import git_tools

def read_private_token(x):
    if isinstance(x, Path):
        x = x.read_text()
    return x

def wait_for_fork(gl, project, fork_poll_interval = 0.5, check_immediately = True):
    # The GitLab API does not have a synchronous fork command.
    # This is the currently recommended workaround.
    while not project.import_status in ['none', 'finished']:
        print(f'YYYYYYYYYYYYYYY {project.import_status}')
        if check_immediately:
            check_immediately = False
        else:
            time.sleep(fork_poll_interval)
            print('XXXXXXX getting')
        project = gl.projects.get(project.id)
    return project

def protect_tags(gl, project_id, tags, delete_existing = False):
    project = gl.projects.get(project_id, lazy = True)
    if delete_existing:
        # Needs gitlab.v4.objects.projects.Project, not just gitlab.v4.objects.projects.ProjectFork.
        # Otherwise, the attribute protectedtags does not exist.
        for x in project.protectedtags.list(all = True):
            x.delete()
    for pattern in tags:
        project.protectedtags.create({'name': pattern, 'create_access_level': gitlab.DEVELOPER_ACCESS})

def protect_branch(gl, project_id, branch):
    project = gl.projects.get(project_id, lazy = True)
    project.branches.get(branch, lazy = True).protect(developers_can_push = True, developers_can_merge = True)

def members_from_access(entity, levels):
    return dict((user.id, user) for user in entity.members.list(all = True) if user.access_level in levels)

def mention_str(users):
    return ' '.join(sorted(['@' + user.username for user in users], key = str.casefold))

class CachedGroup:
    def __init__(self, gl, path, name, logger = None):
        self.gl = gl
        self.path = path
        self.name = name
        self.logger = logger

    @functools.cached_property
    def get(self):
        if self.logger:
            self.logger.debug(f'Getting group {self.path}')
        return self.gl.groups.get(str(self.path), lazy = False)

    @functools.cached_property
    def lazy(self):
        g = self.gl.groups.get(str(self.path), lazy = True)
        g.namespace_path = str(self.path)
        return g

    def create(self, group = None, **kwargs):
        if self.logger:
            self.logger.info(f'Creating group {self.path}')
        if group == None:
            group = self.gl.groups.get(str(self.path.parent))
        self.get = self.gl.groups.create({
            # The GitLab API should permit to give path instead of id.
            #'parent_path': str(self.path.parent),
            'parent_id': group.id,
            'path': self.path.name,
            'name': self.name,
        } | kwargs)
        # Creating a group seems to make you a member.
        # This does not seem to be documented in the GitLab API.
        # Working around this issue.
        self.get.members.get(self.gl.user.id).delete()
        return self.get

    def delete(self):
        if self.logger:
            self.logger.info(f'Deleting group {self.path}')
        # Triggers a bug in python-gitlab:
        # https://github.com/python-gitlab/python-gitlab/issues/1494
        #self.get().delete()
        # Workaround:
        self.gl.groups.delete(str(self.path))
        with general.catch_attribute_error():
            del self.get

    def replace_create(self, f):
        create_old = self.create
        self.create = f(self, create_old)
        return self

class CachedProject:
    def __init__(self, gl, path, name, logger = None):
        self.gl = gl
        self.path = path
        self.name = name
        self.logger = logger

    @functools.cached_property
    def get(self):
        if self.logger:
            self.logger.debug(f'Getting project {self.path}')
        return self.gl.projects.get(str(self.path), lazy = False)

    @functools.cached_property
    def lazy(self):
        p = self.gl.projects.get(str(self.path), lazy = True)
        p.path_with_namespace = str(self.path)
        return p

    def create(self, group = None, **kwargs):
        if self.logger:
            self.logger.info(f'Creating project {self.path}')
        if group == None:
            group = self.gl.groups.get(str(self.path.parent))
        self.get = self.gl.projects.create({
            # The GitLab API should permit to give path instead of id.
            #'namespace_path': str(self.path.parent),
            'namespace_id': group.id,
            'path': self.path.name,
            'name': self.name,
        } | kwargs)
        return self.get

    def delete(self):
        if self.logger:
            self.logger.info(f'Deleting project {self.path}')
        # Triggers a bug in python-gitlab:
        # https://github.com/python-gitlab/python-gitlab/issues/1494
        #self.get().delete()
        # Workaround:
        self.gl.projects.delete(str(self.path))
        with general.catch_attribute_error():
            del self.get

def entity_path_segment(entity):
    type_segment = {
        gitlab.v4.objects.groups.Group: 'groups',
        gitlab.v4.objects.projects.Project: 'projects',
    }[entity.__class__]
    return PurePosixPath(type_segment) / str(entity.id)

def invitation_list(gitlab_client, entity):
    return gitlab_client.http_list(
        str(PurePosixPath('/') / entity_path_segment(entity) / 'invitations'),
        all = True
    )

def invitation_create(gitlab_client, entity, email, access_level, exist_ok = False, **kwargs):
    '''
    Information on arguments:
    * entity: A group or a project (can be lazy).
    '''
    r = gitlab_client.http_post(
        str(PurePosixPath('/') / entity_path_segment(entity) / 'invitations'),
        post_data = {
            'email': email,
            'access_level': access_level,
            **kwargs
        }
    )

    def exist(message):
        if len(message) == 1:
            msg = next(iter(message.values()))
            for s in ['Member already invited', 'Already a member']:
                if msg.startswith(s):
                    return True
        return False

    if r['status'] == 'error':
        message = r['message']
        if not (exist_ok and exist(message)):
            raise ValueError(str(message))

def invitation_delete(gitlab_client, entity, email):
    gitlab_client.http_delete(
        str(PurePosixPath('/') / entity_path_segment(entity) / 'invitations' / email),
    )

        #general.print_json(self.gl.http_delete(str(path / 'sattler.christian@gmail.com')))


if __name__ == '__main__':
    logging.basicConfig()
    logging.root.setLevel(logging.DEBUG)
   
    print('asd')
 
    import gitlab_config as config
    from pathlib import PurePosixPath
    
    g = gitlab.Gitlab(
        config.base_url,
        private_token = read_private_token(config.gitlab_private_token)
    )
    g.auth()

    root = PurePosixPath('/')

    #g.http_list(root / 'projects' / )

