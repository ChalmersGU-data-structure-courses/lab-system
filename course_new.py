import collections
import dateutil.parser
import functools
import general
import gitlab
import google_tools.general
import google_tools.sheets
import gspread
import logging
import operator
from pathlib import Path, PurePosixPath
import re
import types
import urllib.parse

import canvas
import gitlab_tools
import gspread_tools
from instance_cache import instance_cache
import print_parse

#===============================================================================
# Tools

def dict_sorted(xs):
    return dict(sorted(xs, key = operator.itemgetter(0)))

#===============================================================================
# Course labs management

def parse_issue(config, issue):
    request_types = config.request.__dict__
    for (request_type, spec) in request_types.items():
        for (response_type, pp) in spec.issue.__dict__.items():
            try:
                return (request_type, response_type, pp.parse(issue.title))
            except:
                continue

class Course:
    def __init__(self, config, *, canvas_use_cache = True, logger = logging.getLogger('course')):
        self.logger = logger
        self.config = config

        # Qualify a request by the full group id.
        # Used as tag names in the grading repository of each lab.
        self.qualify_request = print_parse.compose(
            print_parse.on(general.component_tuple(0), self.config.group.full_id),
            print_parse.qualify_with_slash
        )

        self.canvas_use_cache = True

    @functools.cached_property
    def canvas(self):
        return canvas.Canvas(config.canvas.url, auth_token = config.canvas_auth_token)

    @functools.cached_property
    def canvas_course(self):
        return canvas.Course(self.canvas, config.canvas.course_id, use_cache = self.canvas_use_cache)

    @functools.cached_property
    def canvas_group_set(self):
        return canvas.GroupSet(self.canvas_course, config.canvas.group_set, use_cache = self.canvas_use_cache)

    @functools.cached_property
    def gl(self):
        r = gitlab.Gitlab(
            self.config.base_url,
            private_token = gitlab_tools.read_private_token(self.config.gitlab_private_token)
        )
        r.auth()
        return r

    def gitlab_url(self, path):
        return urllib.parse.urljoin(self.config.base_url, str(path))

    @functools.cached_property
    def entity_cached_params(self):
        return types.SimpleNamespace(
            gl = self.gl,
            logger = self.logger,
        ).__dict__


    @functools.cached_property
    def labs_group(self):
        return gitlab_tools.CachedGroup(**self.entity_cached_params,
            path = self.config.path.labs,
            name = 'Labs',
        )

    @functools.cached_property
    def groups_group(self):
        return gitlab_tools.CachedGroup(**self.entity_cached_params,
            path = self.config.path.groups,
            name = 'Student groups',
        )

    @functools.cached_property
    def graders_group(self):
        return gitlab_tools.CachedGroup(**self.entity_cached_params,
            path = self.config.path.graders,
            name = 'Graders',
        )

    @functools.cached_property
    def labs(self):
        return frozenset(
            self.config.lab.id.parse(lab.path)
            for lab in self.labs_group.lazy.subgroups.list(all = True)
        )

    @functools.cached_property
    def groups(self):
        return frozenset(
            self.config.group.id_gitlab.parse(group.path)
            for group in self.groups_group.lazy.subgroups.list(all = True)
        )

    @instance_cache
    def group(self, group_id):
        r = gitlab_tools.CachedGroup(**self.entity_cached_params,
            path = self.groups_group.path / self.config.lab.id.print(group_id),
            name = self.config.group.name.print(group_id),
        )

        def create():
            group = gitlab_tools.CachedGroup.create(r, self.groups_group.get)
            with general.catch_attribute_error():
                del self.groups
        r.create = create

        def delete():
            gitlab_tools.CachedGroup.delete(r)
            with general.catch_attribute_error():
                del self.groups
        r.delete = delete

        return r

    def group_delete_all(self):
        for group_id in self.groups:
            self.group(group_id).delete()

    @functools.cached_property
    def groups_on_canvas(self):
        return dict(
            (self.config.group.name.parse(canvas_group.name), tuple(
                self.canvas_course.user_details[canvas_user_id]
                for canvas_user_id in self.canvas_group_set.group_users[canvas_group.id]
            ))
            for canvas_group in self.canvas_group_set.details.values()
        )

    def create_groups_from_canvas(self, delete_existing = True):
        if delete_existing:
            self.group_delete_all()
        groups_old = () if delete_existing else self.groups
        for (group_id, canvas_users) in self.groups_on_canvas.items():
            if not group_id in groups_old and group_id < 4: # TODO: remove hack
                self.group(group_id).create()

    @functools.cached_property
    def graders(self):
        return gitlab_tools.members_from_access(
            self.graders_group.lazy,
            [gitlab.OWNER_ACCESS]
        )

    def student_members(self, cached_entity):
        '''
        Get the student members of a group or project.
        We approximate this as meaning members that have developer or maintainer rights.
        '''
        return gitlab_tools.members_from_access(
            cached_entity.lazy,
            [gitlab.DEVELOPER_ACCESS, gitlab.MAINTAINER_ACCESS, gitlab.OWNER_ACCESS] # TODO: delete owner case
        )

    def configure_student_project(self, project):
        self.logger.debug('Configuring student project {project.path_with_namespace}')

        def patterns():
            for spec in self.config.request.__dict__.values():
                for pattern in spec.tag_protection:
                    yield pattern

        self.logger.debug('Protecting tags')
        gitlab_tools.protect_tags(self.gl, project.id, patterns())
        self.logger.debug('Waiting for potential fork to finish')
        project = gitlab_tools.wait_for_fork(self.gl, project)
        self.logger.debug(f'Protecting branch {self.config.branch.master}')
        gitlab_tools.protect_branch(self.gl, project.id, self.config.branch.master)
        return project

    def request_namespace(self, f):
        return types.SimpleNamespace(**dict(
            (request_type, f(request_type, spec))
            for (request_type, spec) in self.config.request.__dict__.items()
        ))

    def format_tag_metadata(self, project, tag, description = None):
        def lines():
            if description:
                yield description
            yield f'* name: {tag.name}'
            path = PurePosixPath(project.path_with_namespace)
            url = self.gitlab_url(path / '-' / 'tags' / tag.name)
            yield f'* URL: {url}'
        return general.join_lines(lines())

    #def parse_request_tags(self, tags, tag_name = lambda tag: tag.name)

    def parse_request_tags(self, project):
        '''
        Parse the request tags of a project.
        A request tag is one matching the the pattern in self.config.tag.
        These are used for grading and testing requests.
        Returns an object with attributes for each request type (as specified in config.request).
        Each attribute is a list of tags sorted by committed date.

        Warning: The committed date can be controlled by students by pushing a tag
                 (instead of creating it in the web user interface) with an incorrect date.
        '''
        self.logger.debug('Parsing request tags in project {project.path_with_namespace}')

        request_types = self.config.request.__dict__
        r = self.request_namespace(lambda x, y: list())
        for tag in project.tags.list(all = True):
            tag.date = dateutil.parser.parse(tag.commit['committed_date'])
            for (request_type, spec) in request_types.items():
                if re.fullmatch(spec.tag_regex, tag.name):
                    r.__dict__[request_type].append(tag)
                    break
            else:
                self.logger.info(self.format_tag_metadata(project, tag,
                    f'Unrecognized tag in project {project.path_with_namespace}:'
                ))

        for xs in r.__dict__.values():
            xs.sort(key = operator.attrgetter('date'))
        return r

    def format_issue_metadata(self, project, issue, description = None):
        def lines():
            if description:
                yield description
            yield f'* title: {issue.title}'
            author = issue.author['name']
            yield f'* author: {author}'
            yield f'* URL: {issue.web_url}'
        return general.join_lines(lines())

    def response_issues(self, project):
        '''
        Retrieve the response issues in a project.
        A response issue is one created by a grader and matching an issue title in self.config.issue_title.
        These are used for grading and testing responses.
        '''
        for issue in project.issues.list(all = True):
            if issue.author['id'] in self.graders:
                yield issue

    def parse_response_issues(self, project):
        '''
        Parse the response issues of a project (see 'official_issues').
        Returns an object with attributes for each request type (as specified in config.request).
        Each attribute is a dictionary mapping pairs of tag names and issue types
        to pairs of an issue and the issue title parsing.
        '''
        self.logger.debug('Parsing response issues in project {project.path_with_namespace}')

        r = self.request_namespace(lambda x, y: dict())
        for issue in self.response_issues(project):
            x = parse_issue(self.config, issue)
            if x:
                (request_type, response_type, u) = x
                request_issues = r.__dict__[request_type]
                key = (u['tag'], response_type)
                prev = request_issues.get(key)
                if prev:
                    (issue_prev, _) = prev
                    self.logger.warning(
                          general.join_lines([f'Duplicate response issue in project {project.path_with_namespace}.',])
                        + self.format_issue_metadata(project, issue_prev, 'First issue:')
                        + self.format_issue_metadata(project, issue, 'Second issue:')
                        + general.join_lines(['Ignoring second issue.'])
                    )
                else:
                    request_issues[key] = (issue, u)
            else:
                self.logger.warning(self.format_issue_metadata(project, issue,
                    f'Response issue in project {project.path_with_namespace} with no matching request tag:'
                ))
        return r

    def merge_requests_and_responses(self, project, request_tags = None, response_issues = None):
        '''
        Merges the tag requests and response issues of a project.
        Returns an object with attributes for each request type (as specified in config.request).
        Each attribute is a map from request names to objects with the following attributes:
        * 'tag': the request tag,
        * response_type (for each applicable issue type):
          None (if missing) or a pair of issue and issue title parsing.
        '''
        if request_tags == None:
            request_tags = self.parse_request_tags(project)
        if response_issues == None:
            response_issues = self.parse_response_issues(project)

        def merge(request_type, spec, tags, response_map):
            def response(tag):
                r = types.SimpleNamespace(**dict(
                    (response_type, response_map.pop((tag.name, response_type), None))
                    for response_type in spec.issue.__dict__.keys()
                ))
                r.tag = tag
                return r

            r = dict((tag.name, response(tag)) for tag in tags)
            for ((tag_name, response_type), (issue, _)) in response_map.items():
                self.logger.warning(general.join_lines([
                    f'Unrequested {response_type} issue in project {project.path_with_namespace}:'
                ]) + self.format_issue_metadata(project, issue))
            return r

        return self.request_namespace(lambda request_type, spec:
            merge(request_type, spec, request_tags.__dict__[request_type], response_issues.__dict__[request_type])
        )

if __name__ == "__main__":
    logging.basicConfig()
    logging.root.setLevel(logging.DEBUG)

    import gitlab_config as config

    course = Course(config)
    #project = course.gl.projects.get('courses/DIT181/test/groups/00/lab-2')
    #r = course.merge_requests_and_responses(project)
    #print(r)

    #cv = canvas.Canvas('chalmers.instructure.com', auth_token = config.canvas_auth_token)
    #cc = canvas.Course(cv, 10681)
    #for x in cc.user_details.values():
    #    general.print_json(x)
    #    break
