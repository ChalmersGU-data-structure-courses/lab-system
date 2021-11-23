import contextlib
import functools
import general
import git
import gitlab
import logging
import tempfile
import types

import course_basics
import git_tools
import gitlab_tools
import grading_sheet
import print_parse

class HandlerData:
    def __init__(self, group, handler_key):
        self.course = group.course
        self.lab = group.lab
        self.logger = group.logger

        self.handler_key = handler_key
        self.handler = self.lab.config.request_handlers[handler_key]

        # A dictionary mapping request names to tags, which are an instance of one of:
        # - gitlab.v4.objects.tags.ProjectTag,
        # - pairs of git.Reference and git.Commit.
        # Ordered by date.
        #
        # Populated by GroupProject.parse_requests_tags.
        # Initializes with None.
        self.request_tags = None

        # A dictionary mapping keys of response titles to dictionaries
        # mapping request names to issues and issue title parsings.
        #
        # Populated by GroupProject.parse_response_issues.
        # Initialized with inner dictionaries set to None.
        self.response_issues = {
            response_key: None,
            for (response_key, issue_title) in self.handler.issue_titles.items()
        }

    @functools.cached_property
    def requests_and_responses(self):

class GroupProject:
    def __init__(self, lab, id, logger = logging.getLogger(__name)):
        self.course = lab.course
        self.lab = lab
        self.id = id
        self.logger = logger

        self.name = self.course.config.group.name.print(id)
        self.remote = self.course.config.group.full_id.print(id)

        self.handler_data = {
            handler_key: HandlerData(self, handler_key)
            for handler_key in self.lab.config.request_handlers.items()
        }

    @functools.cached_property
    def gl(self):
        return self.lab.gl

    @functools.cached_property
    def project(self):
        '''
        A lab project for a student group.
        On creation, the repository is initialized with the problem branch of the local grading repository.
        That one needs to be initialized and have the problem branch.
        '''
        r = gitlab_tools.CachedProject(
            gl = self.gl,
            path = self.course.group(self.id).path / self.course.config.lab.full_id.print(self.lab.id),
            name = self.lab.name_full,
            logger = self.logger,
        )

        def create():
            project = gitlab_tools.CachedProject.create(r, self.course.group(self.id).get)
            try:
                self.lab.repo.git.push(
                    project.ssh_url_to_repo,
                    git_tools.refspec(
                        git_tools.local_branch(self.course.config.branch.problem),
                        self.course.config.branch.master,
                        force = True,
                    )
                )
                self.course.configure_student_project(project)
                self.repo_add_remote()
            except:
                r.delete()
                raise
        r.create = create

        return r

    def repo_add_remote(self, ignore_missing = False):
        '''
        Add the student repository on Chalmers GitLab as a remote to the local repository.
        This configures the refspecs for fetching in the manner expected by this script.
        This will only be done if the student project on Chalmers GitLab exists.
        If 'ignore_missing' holds, no error is raised if the project is missing.
        '''
        try:
            self.lab.repo_add_remote(
                self.remote,
                self.project.get,
                fetch_branches = [(git_tools.Namespacing.remote, git_tools.wildcard)],
                fetch_tags = [(git_tools.Namespacing.qualified_suffix_tag, git_tools.wildcard)],
                prune = True,
            )
        except gitlab.GitlabGetError as e:
            if ignore_missing and e.response_code == 404 and e.error_message == '404 Project Not Found':
                if self.logger:
                    self.logger.debug(f'Not adding remote {self.remote} because project is missing')
            else:
                raise e

    @functools.cached_property
    def members(self):
        '''
        The members of a student group project are taken from these sources:
        * members of the containing student group,
        * members of the project iself (for students that have been added because they changed groups).
        In both cases, we restrict to users with developer or maintainer rights.
        '''
        return general.dict_union(map(self.course.student_members, [
            self.course.group(self.id),
            self.project,
        ])).values()

    # TODO.
    # We could improve caching of members if we had a way to detect updates.
    # But e.g. group hooks monitoring for membership updates are only
    # available in the "Premium tier" version of GitLab, not the open source one.
    def members_clear(self):
        with contextlib.suppress(AttributeError):
            del self.members

    def append_mentions(self, text):
        '''
        Append a mentions paragraph to a given Markdown text.
        This will mention all the student members.
        Under standard notification settings, it will trigger notifications
        when the resulting text is posted in an issue or comment.
        '''
        return gitlab_tools.append_mentions(text, self.members)

    def repo_fetch(self):
        '''
        Make sure the local repository as up to date with respect to
        the contents of the student repository on GitLab Chalmers.
        '''
        self.logger.info(f'Fetching from student repository, remote {self.remote}.')
        self.lab.repo.remote(self.remote).fetch('--update-head-ok')

    def repo_tag(self, tag_name):
        '''
        Construct the tag (instance of git.Tag) in the grading repository
        corresponding to the tag with given name in the student repository.
        This will have the group's remote prefixed.

        Arguments:
        * tag_name: Instance of PurePosixPath, str, or gitlab.v4.objects.tags.ProjectTag.
        '''
        if isinstance(tag_name, gitlab.v4.objects.tags.ProjectTag):
            tag_name = tag_name.name
        tag_name = git_tools.qualify(self.remote, tag_name) / 'tag'
        return git_tools.normalize_tag(self.lab.repo, tag_name)

    def hotfix_group(self, branch_hotfix, branch_group):
        '''
        Attempt to hotfix the branch 'branch_group' of the group project.
        The hotfix branch 'branch_hotfix' in the local grading repository is a descendant of the problem branch.
        The metadata of the applied commit is taken from the commit pointed to by 'branch_hotfix'.
        Will log a warning if the merge cannot be performed.
        '''
        self.logger.info(f'Hotfixing {branch_group} in f{self.project.path}')

        # Make sure our local mirror of the student branches is as up to date as possible.
        self.repo_fetch()

        problem = self.lab.head_problem
        hotfix = git_tools.normalize_branch(self.repo, branch_hotfix)
        if problem == hotfix:
            self.logger.warn('Hotfixing: hotfix identical to problem.')
            return

        master = git_tools.remote_branch(self.remote, branch_group)
        index = git.IndexFile.from_tree(self.lab.repo, problem, master, hotfix, i = '-i')
        merge = index.write_tree()
        diff = merge.diff(master)
        if not diff:
            self.logger.warn('Hotfixing: hotfix already applied')
            return
        for x in diff:
            self.logger.info(x)

        commit = git.Commit.create_from_tree(
            self.lab.repo,
            merge,
            hotfix.message,
            parent_commits = [git_tools.resolve(self.lab.repo, master)],
            head = False,
            author = hotfix.author,
            committer = hotfix.committer,
            author_date = hotfix.authored_datetime,
            commit_date = hotfix.committed_datetime,
        )

        return self.lab.repo.remote(self.remote).push(git_tools.refspec(
            commit.hexsha,
            self.course.config.branch.master,
            force = False,
        ))

    def hook_create(self, netloc):
        '''
        Create webhook in the student project on GitLab.
        The hook is triggered if tags are updated or issues are changed.
        This r

        Note: Due to a GitLab bug, the hook is not called when an issue is deleted.
              Thus, before deleting a response issue, you should first rename it
              (triggering the hook)  so that it is no longer recognized as a response issue.
        '''
        url = print_parse.url.print(print_parse.URL_HTTPS(netloc))
        self.logger.debug(f'Creating project hook with url {url}')
        return self.project.lazy.hooks.create({
            'url': url,
            'enable_ssl_verification': 'false',
            'token': self.course.config.gitlab_webhook_secret_token,
            'issues_events': 'true',
            'tag_push_events': 'true',
        })

    def hook_delete(self, hook):
        ''' Delete a webhook in the student project on GitLab. '''
        self.logger.debug(f'Deleting project hook with url {hook.url}')
        hook.delete()

    def hook_delete_all(self):
        '''
        Delete all webhook in the student project on GitLab.
        You should use this when previous program runs where killed or stopped
        in a non-standard fashion that prevented cleanup and have left lingering webhooks.
        '''
        for hook in self.project.lazy.hooks.list(all = True):
            self.hook_delete(hook)

    @contextlib.contextmanager
    def hook_manager(self, netloc):
        '''A context manager for creating a webhook.'''
        hook = self.hook_create(netloc)
        try:
            yield hook
        finally:
            self.hook_delete(hook)

    def post_response_issue(self, title, description):
        self.logger.debug(general.join_lines([
            'Posting response issue:',
            f'* title: {title}',
            f'* description:',
            *description.splitlines()
        ]))
        return self.project.lazy.issues.create({
            'title': title,
            'description': self.append_mentions(description)
        })

    def post_issue(self, project, request_type, request, response_type, description, params):
        title = self.course.config.request.__dict__[request_type].issue.__dict__[response_type].print(
            params | {'tag': request}
        )
        self.logger.debug(general.join_lines([
            f'Title: {title}',
            'Description:',
        ]) + description)
        return project.lazy.issues.create({'title': title, 'description': description})

    def create_response_issue(
        self,
        request_type,
        request,
        response_type,
        description,
        params = dict(),
        exist_ok = True
    ):
        '''
        Create a response issue in the student project.
        Also update the local response cache ('response') with this response.
        If a response issue of the given response type already exists, do nothing if exist_ok holds.
        Otherwise, raise an error.
        '''
        self.logger.info(f'Creating {response_type} issue for {request_type} {request}.')

        response = self.requests_and_responses.__dict__[request_type][request]
        if response.__dict__[response_type]:
            raise ValueError(f'{response_type} issue for {request_type} {request} already exists.')

        description += self.mention_paragraph()
        qualified_request = self.course.qualify_request.print((self.id, request))
        issue = self.post_issue(self.project, request_type, qualified_request, response_type, description, params)
        response.__dict__[response_type] = (issue, params)
        return issue
