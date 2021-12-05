import contextlib
import dateutil
import functools
import logging
import operator
from pathlib import Path, PurePosixPath
import time
import urllib.parse

import gitlab

import general


logger = logging.getLogger(__name__)

def read_private_token(x):
    if isinstance(x, Path):
        x = x.read_text()
    return x

# The default value of per_page seems to be 15.
# This is incredibly slow.
# We wish to retrieve as many items at once, so supply a large per_page parameter.
# The maximum seems to be 100.
list_all_args = {
    'all': True,
    'per_page': 1000,
}

def list_all(manager):
    return manager.list(**list_all_args)

@contextlib.contextmanager
def exist_ok():
    try:
        yield
    except gitlab.exceptions.GitlabCreateError as e:
        if not e.response_code in [304, 409]:
            raise
    except gitlab.exceptions.GitlabDeleteError as e:
        if not e.response_code in [304, 404]:
            raise

def exist_ok_check(enabled = False):
    return exist_ok() if enabled else contextlib.nullcontext()

def wait_for_fork(gl, project, fork_poll_interval = 0.5, check_immediately = True):
    # The GitLab API does not have a synchronous fork command.
    # This is the currently recommended workaround.
    logger.debug(f'Waiting for fork of {project.path_with_namespace}...')
    while not project.import_status in ['none', 'finished']:
        if check_immediately:
            check_immediately = False
        else:
            time.sleep(fork_poll_interval)
        project = gl.projects.get(project.id)
        logger.debug(f'Import status: {project.import_status}')
    logger.debug('Finished waiting for fork.')
    return project

def protect_tags(gl, project_id, patterns, delete_existing = False, exist_ok = True):
    project = gl.projects.get(project_id, lazy = True)
    if delete_existing or exist_ok:
        protected_prev = list_all(project.protectedtags)
    if delete_existing:
        # Needs gitlab.v4.objects.projects.Project, not just gitlab.v4.objects.projects.ProjectFork.
        # Otherwise, the attribute protectedtags does not exist.
        for x in protected_prev:
            x.delete()
        protected_prev = list()
    if exist_ok:
        patterns_prev = set(
            protect.name
            for protect in protected_prev
            if [level['access_level'] for level in protect.create_access_levels] == [30]
        )
        patterns = set(patterns) - patterns_prev
    for pattern in patterns:
        with exist_ok_check(exist_ok):
            project.protectedtags.create({'name': pattern, 'create_access_level': gitlab.DEVELOPER_ACCESS})

def protect_branch(gl, project_id, branch):
    project = gl.projects.get(project_id, lazy = True)
    project.branches.get(branch, lazy = True).protect(developers_can_push = True, developers_can_merge = True)

def members_from_access(entity, levels):
    return dict((user.id, user) for user in list_all(entity.members) if user.access_level in levels)

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
        if group is None:
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
        with contextlib.suppress(AttributeError):
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
        if group is None:
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
        with contextlib.suppress(AttributeError):
            del self.get

def users_dict(manager):
    return dict((user.username, user) for user in list_all(manager))

def members_dict(entity):
    return users_dict(entity.members)

def member_create(entity, user_id, access_level, exist_ok = False, **kwargs):
    with exist_ok_check(exist_ok):
        entity.members.create({
            'user_id': user_id,
            'access_level': access_level,
            **kwargs,
        })

def member_delete(entity, user_id, exist_ok = False):
    with exist_ok_check(exist_ok):
        entity.members.delete(user_id)

def entity_path_segment(entity):
    type_segment = {
        gitlab.v4.objects.groups.Group: 'groups',
        gitlab.v4.objects.projects.Project: 'projects',
    }[entity.__class__]
    return PurePosixPath(type_segment) / str(entity.id)

def invitation_list(gitlab_client, entity):
    return gitlab_client.http_list(
        str(PurePosixPath('/') / entity_path_segment(entity) / 'invitations'),
        **list_all_args,
    )

@gitlab.exceptions.on_http_error(gitlab.exceptions.GitlabCreateError)
def invitation_create(gitlab_client, entity, email, access_level, **kwargs):
    r = gitlab_client.http_post(
        str(PurePosixPath('/') / entity_path_segment(entity) / 'invitations'),
        post_data = {
            'email': email,
            'access_level': access_level,
            **kwargs
        }
    )

    if r['status'] == 'error':
        message = general.from_singleton(r['message'].values())
        response_code = None
        if any(message.startswith(prefix) for prefix in [
                'Member already invited',
                'Already a member',
                'Invite email has already been taken',
                'The member\'s email address has already been taken',
                'User already exists in source',
        ]):
            response_code = 409
        raise gitlab.exceptions.GitlabCreateError(message, response_code = response_code)

@gitlab.exceptions.on_http_error(gitlab.exceptions.GitlabDeleteError)
def invitation_delete(gitlab_client, entity, email):
    gitlab_client.http_delete(
        str(PurePosixPath('/') / entity_path_segment(entity) / 'invitations' / email),
    )

def get_tags_sorted_by_date(project):
    tags = list_all(project.tags)
    for tag in tags:
        tag.date = dateutil.parser.parse(tag.commit['committed_date'])
    tags.sort(key = operator.attrgetter('date'))
    return tags

def format_username(user):
    '''
    Format username of a GitLab user.
    This prepends the character '@'.
    '''
    return '@' + user.username

def mentions(users):
    '''
    Get mentions string for an iterable of users.
    Including this in an issue or comment will typically
    trigger notification to the mentioned users.
    '''
    return ' '.join(map(format_username, users))

def append_paragraph(text, paragraph):
    '''Append a paragraph to a given Markdown text.'''
    lines = text.splitlines()

    def f():
        if len(lines) != 0:
            yield from lines
            yield ''
    return general.join_lines(f()) + paragraph

def append_mentions(text, users):
    '''Append a mentions paragraph to a given Markdown text.'''
    return append_paragraph(text, mentions(users))

def project_url(project, path_segments = [], query_params = dict()):
    '''
    Format a URL for a project request.

    Arguments:
    * project: Project in which to make the request in.
    * path_segments:
        Iterable of path segments to append to
        the projects path to give the desired endpoint.
    * query: Query parameters represented as a dictionary mapping strings to strings.
    '''
    url = urllib.parse.urlparse(project.web_url)
    url = url._replace(path = str(PurePosixPath(url.path) / PurePosixPath(*path_segments)))
    url = url._replace(query = urllib.parse.urlencode(query_params))
    return urllib.parse.urlunparse(url)

# TODO:
# Add web_url attribute to lazy project instances when we can cheaply compute them.
# Then these two methods become callable on them.

# BUG:
# GitLab does not provide any way to disambiguate between a branch and a tag.
# Currently, these links seem to prefer tags over branches.
# How to make sure (otherwise, exploitable by students)?
def url_tree(project, ref):
    return project_url(project, ['-', 'tree', str(ref)])

def url_blob(project, ref, path):
    return project_url(project, ['-', 'tree', str(ref), *PurePosixPath(path).parts])

# BUG:
# GitLab gets confused when references contain slashes ('/').
# Although the diff shows correctly, links back to the project are broken.
def url_compare(project, source, target):
    return project_url(
        project,
        ['-', 'compare', str(source) + '...' + str(target)], {'w': '1'}
    )

def url_tag_name(project, tag_name):
    return project_url(project, ['-', 'tags', tag_name])

def url_tag(project, tag):
    return url_tag_name(project, tag.name)

def url_issues_new(project, **kwargs):
    '''
    Format a URL for opening a new issue in a project.

    Arguments:
    * project: Relevant project.
    * kwargs:
        Parameters to initialize the issue with.
        Values should be strings.
        Commonly used keys are 'title' and 'description'.
    '''
    return project_url(
        project,
        ['-', 'issues', 'new'],
        dict((f'issue[{key}]', value) for (key, value) in kwargs.items())
    )

def format_tag_metadata(project, tag_name, description = None):
    def lines():
        if description:
            yield description
        yield f'* name: {tag_name}'
        url = url_tag_name(project, tag_name)
        yield f'* URL: {url}'
    return general.join_lines(lines())

def format_issue_metadata(issue, description = None):
    def lines():
        if description:
            yield description
        yield f'* title: {issue.title}'
        author = issue.author['name']
        yield f'* author: {author}'
        yield f'* URL: {issue.web_url}'
    return general.join_lines(lines())
