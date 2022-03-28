import contextlib
import functools
import logging
from pathlib import Path
import shutil
import tempfile
import types

import git
import gitlab
import gitlab.v4.objects.tags

import events
import item_parser
import general
import git_tools
import gitlab_tools
import google_tools.sheets
import grading_sheet
import group_project
import instance_cache
import live_submissions_table
import path_tools
import webhook_listener


class Lab:
    '''
    This class abstracts over a single lab in a course.

    The lab is hosted on Chalmers GitLab.
    Related attributes and methods:
    - official_project, grading_project
    - create_group_projects, create_group_projects_fast
    - delete_group_projects
    - hooks_manager

    This class also manages a local repository called the grading repository
    that fetches from official and student projects on Chalmers GitLab
    and pushes to the grading project on Chalmers GitLab.
    The latter is intended to be consumed by graders.
    Related attributes and methods:
    - repo_init
    - repo_fetch_all
    - repo_push
    - remote_tags

    It also manages a grading sheet on Google Docs.
    Related attributes and methods:
    - grading_sheet
    - update_grading_sheet

    It also manages a live submissions table on Canvas.
    Related attributes and methods:
    - setup_live_submissions_table(self, deadline = None):
    - self.live_submissions_table.update_rows()
    - update_live_submissions_table(self):

    It also provides handling for events.LabEvent.
    Related attributes and methods:
    - handle_event

    See update_grading_sheet_and_live_submissions_table for an example interaction.

    This class is configured by the config argument to its constructor.
    The format of this argument is documented in gitlab.config.py.template under _lab_config.

    This class manages instances of group_project.GroupProject.
    See student_group and student_groups.
    Each instance of this class is managed by an instance of course.Course.
    '''
    def __init__(self, course, id, config = None, dir = None, deadline = None, logger = logging.getLogger(__name__)):
        '''
        Initialize lab manager.
        Arguments:
        * course: course manager.
        * id: lab id, typically used as key in a lab configuration dictionary (see 'gitlab_config.py.template')
        * config:
            lab configuration, typically the value in a lab configuration dictionary.
            If None, will be taken from labs dictionary in course configuration.
        * dir:
            Local directory used as local copy of the grading repository.
            Only its parent directory has to exist.
        * deadline:
            Optional deadline for submissioms.
            If set, submissions to consider for the grading sheet
            and live submissions table are limited by this deadline.
            It is up to lab handlers how they want to treat late submissions.
            At the moment, all lab handler implementations
            do not inspect the lab deadline.
        '''
        self.logger = logger
        self.course = course
        self.id = id
        self.dir = None if dir is None else Path(dir)
        self.deadline = deadline

        self.config = self.course.config.labs[id] if config is None else config

        # Naming config
        self.id_str = self.course.config.lab.id.print(self.id)
        self.name = self.course.config.lab.name.print(self.id)
        self.name_semantic = (self.config.path_source / 'name').read_text().strip()
        self.name_full = '{} — {}'.format(self.name, self.name_semantic)

        # Gitlab config
        self.path = self.course.config.path.labs / self.course.config.lab.id_gitlab.print(self.id)

        # Local grading repository config.
        self.dir_repo = self.dir / 'repo'
        # Whether we have updated the repository and it needs to be pushed.
        self.repo_updated = False

        # Other local data.
        self.file_live_submissions_table = self.dir / 'live-submissions-table.html'
        self.file_live_submissions_table_staging = path_tools.add_suffix(
            self.file_live_submissions_table,
            '.staging',
        )

    @functools.cached_property
    def gl(self):
        return self.course.gl

    @functools.cached_property
    def entity_cached_params(self):
        return types.SimpleNamespace(
            gl = self.gl,
            logger = self.logger,
        ).__dict__

    @functools.cached_property
    def group(self):
        '''
        The group for this lab on Chalmers GitLab.
        '''
        r = gitlab_tools.CachedGroup(
            **self.entity_cached_params,
            path = self.path,
            name = self.name_full,
        )

        def create():
            gitlab_tools.CachedGroup.create(r, self.course.labs_group.get)
        r.create = create

        return r

    # We give an alternative implemention of official_project using inheritance.
    # This example is applicable also to our other usages of CachedGroup and CachedProject.
    # Unfortunately, Python does not support class closures (classes in a function's scope).
    # So boilerplate is needed to store the functions arguments as class instance attributes.
    # That's why we chose to manually implement inheritance in the function scope.
    #
    # @functools.cached_property
    # def official_project(self):
    #     '''
    #     The official lab project on Chalmers GitLab.
    #     On creation:
    #     * The contents are taken from the specified local lab directory
    #       (together with an optionally specified .gitignore file).
    #       So make sure the problem and solution subdirectories are clean beforehand.
    #     * Problem and solution branches are set up.
    #     '''
    #     def OfficialProject(gitlab_tools.CachedProject):
    #         def __init__(self, outer):
    #             self.outer = outer
    #             super().__init__(
    #                 gl = outer.gl,
    #                 path = outer.path / outer.course.config.path_lab.official,
    #                 name = '{} — official repository'.format(outer.name),
    #                 logger = outer.logger,
    #             )
    #
    #         def create(self):
    #             super().create(self.outer.group.get())
    #
    #             with tempfile.TemporaryDirectory() as dir:
    #                 repo = git.Repo.init(dir)
    #
    #                 def push_branch(name, message):
    #                     shutil.copytree(self.outer.config.path_source / name, dir, dirs_exist_ok = True)
    #                     repo.git.add('--all', '--force')
    #                     repo.git.commit(message = message)
    #                     repo.git.push(
    #                         self.outer.official_project.ssh_url_to_repo,
    #                         git_tools.refspec(git_tools.head, git_tools.local_branch(name), force = True)
    #                     )
    #
    #                 if self.config.path_gitignore:
    #                     shutil.copyfile(self.outer.config.path_gitignore, Path(dir) / '.gitignore')
    #                 push_branch(self.outer.course.config.branch.problem, 'Initial commit.')
    #                 push_branch(self.outer.course.config.branch.solution, 'Official solution.')
    #
    #         return OfficialProject(self)

    @functools.cached_property
    def official_project(self):
        '''
        The official lab project on Chalmers GitLab.
        On creation:
        * The contents are taken from the specified local lab directory
          (together with an optionally specified .gitignore file).
          So make sure the problem and solution subdirectories are clean beforehand.
        * Problem and solution branches are set up.
        '''
        r = gitlab_tools.CachedProject(
            **self.entity_cached_params,
            path = self.path / self.course.config.path_lab.official,
            name = '{} — official repository'.format(self.name),
        )

        def create():
            project = gitlab_tools.CachedProject.create(r, self.group.get)
            try:
                with tempfile.TemporaryDirectory() as dir:
                    repo = git.Repo.init(dir)

                    def push_branch(name, message):
                        shutil.copytree(self.config.path_source / name, dir, dirs_exist_ok = True)
                        repo.git.add('--all', '--force')
                        repo.git.commit(message = message)
                        repo.git.push(project.ssh_url_to_repo, git_tools.refspec(
                            git_tools.head,
                            git_tools.local_branch(name),
                            force = True
                        ))

                    if self.config.path_gitignore:
                        shutil.copyfile(self.config.path_gitignore, Path(dir) / '.gitignore')
                    push_branch(self.course.config.branch.problem, 'Initial commit.')
                    push_branch(self.course.config.branch.solution, 'Official solution.')
            except:  # noqa: E722
                r.delete()
                raise
        r.create = create

        return r

    @functools.cached_property
    def staging_project(self):
        '''
        The staging project on Chalmers GitLab.
        When created, forked from the official project and modified to prepare for forking of student projects.
        '''
        r = gitlab_tools.CachedProject(
            **self.entity_cached_params,
            path = self.path / self.course.config.path_lab.staging,
            name = '{} — staging repository'.format(self.name),
        )

        def create():
            if self.logger:
                self.logger.info(f'Forking project {r.path}')
            r.get = self.official_project.get.forks.create({
                'namespace_path': str(r.path.parent),
                'path': r.path.name,
                'name': r.name,
            })
            try:
                r.get = gitlab_tools.wait_for_fork(self.gl, r.get, check_immediately = False)
                r.get.branches.create({
                    'branch': self.course.config.branch.master,
                    'ref': self.course.config.branch.problem,
                })
                r.get.default_branch = self.course.config.branch.master
                r.get.save()
                r.get.branches.get(self.course.config.branch.problem, lazy = True).delete()
                r.get.branches.get(self.course.config.branch.solution, lazy = True).delete()
            except:  # noqa: E722
                r.delete()
                raise
        r.create = create

        return r

    @contextlib.contextmanager
    def with_staging_project(self):
        self.staging_project.create()
        try:
            yield self.staging_project.get
        finally:
            self.staging_project.delete()

    @functools.cached_property
    def grading_project(self):
        '''
        The grading project on Chalmers GitLab.
        When created, it is empty.
        '''
        r = gitlab_tools.CachedProject(
            **self.entity_cached_params,
            path = self.path / self.course.config.path_lab.grading,
            name = '{} — grading repository'.format(self.name),
        )

        def create():
            gitlab_tools.CachedProject.create(r, self.group.get)
        r.create = create

        return r

    @functools.cached_property
    def repo(self):
        '''
        Local grading repository.
        This is used as staging for (pushes to) the grading project on Chalmers GitLab.
        It fetches from the official lab repository and student group repositories.
        '''
        try:
            return git.Repo(self.dir_repo)
        except git.NoSuchPathError:
            self.repo_init()
            return self.repo

    def repo_add_remote(self, name, project, **kwargs):
        git_tools.add_tracking_remote(
            self.repo,
            name,
            project.ssh_url_to_repo,
            no_tags = True,
            overwrite = True,
            **kwargs,
        )

    def repo_add_groups_remotes(self, **kwargs):
        '''
        Configure fetching remotes for all student groups in local grading repository.
        This overwrites any existing configuration for such remotes, except for groups no longer existing.
        '''
        for group_id in self.course.groups:
            self.student_group(group_id).repo_add_remote(ignore_missing = True)

    def repo_delete(self):
        '''
        Delete the repository directory.
        Warning: Make sure that self.dir is correctly configured before calling.
        '''
        shutil.rmtree(self.dir)

    def repo_init(self, bare = False):
        '''
        Initialize the local grading repository.
        If the directory exists, we assume that all remotes are set up.
        Otherwise, we create the directory and populate it with remotes on Chalmers GitLab as follows.
        Fetching remotes are given by the official repository and student group repositories.
        Pushing remotes are just the grading repository.
        '''
        self.logger.info('Initializing local grading repository.')
        repo = git.Repo.init(self.dir_repo, bare = bare)
        try:
            with repo.config_writer() as c:
                c.add_value('advice', 'detachedHead', 'false')

            # Configure and fetch official repository.
            branches = [self.course.config.branch.problem, self.course.config.branch.solution]
            self.repo_add_remote(
                self.course.config.path_lab.official,
                self.official_project.get,
                fetch_branches = [(git_tools.Namespacing.local, b) for b in branches],
                fetch_tags = [(git_tools.Namespacing.local, git_tools.wildcard)],
            )
            self.repo_fetch_official()

            # Configure offical grading repository and student groups.
            self.repo_add_remote(
                self.course.config.path_lab.grading,
                self.grading_project.get,
                push_branches = branches,
                push_tags = [git_tools.wildcard],
            )
            self.repo_add_groups_remotes(ignore_missing = True)
        except:  # noqa: E722
            shutil.rmtree(self.dir)
            raise
        self.repo = repo

    def repo_remote_command(self, command):
        if self.course.ssh_multiplexer is None:
            self.repo.git._call_process(*command)
        else:
            self.course.ssh_multiplexer.git_cmd(self.repo, command)

    def repo_command_fetch(self, remotes):
        remotes = list(remotes)
        self.logger.debug(f'Fetching from remotes: {remotes}.')

        def command():
            yield 'fetch'
            yield '--update-head-ok'
            yield from ['--jobs', str(self.course.config.gitlab_ssh.max_sessions)]
            yield from ['--multiple', *remotes]
        self.repo_remote_command(list(command()))

        # Update caching mechanisms.
        self.repo_updated = True
        with contextlib.suppress(AttributeError):
            del self.remote_tags

    def repo_command_push(self, remote):
        self.logger.debug(f'Pushing to remote: {remote}.')

        def command():
            yield 'push'
            yield remote
        self.repo_remote_command(list(command()))

    def repo_fetch_official(self):
        '''
        Fetch problem and solution branches from the offical
        repository on Chalmers GitLab to the local grading repository.
        '''
        self.logger.info('Fetching from official repository.')
        self.repo_command_fetch([self.course.config.path_lab.official])

    def repo_push(self, force = False):
        '''
        Push the local grading repository to the grading repository on Chalmers GitLab.
        Only push if changes have been recorded.
        '''
        if self.repo_updated or force:
            self.logger.info('Pushing to grading repository.')
            self.repo_command_push(self.course.config.path_lab.grading)
            self.repo_updated = False

    @instance_cache.instance_cache
    def student_group(self, group_id):
        return group_project.GroupProject(self, group_id)

    @functools.cached_property
    def student_groups(self):
        return [self.student_group(group_id) for group_id in self.course.groups]

    def configure_student_project(self, project):
        self.logger.debug('Configuring student project {project.path_with_namespace}')

        def patterns():
            for request_handler in self.config.request_handlers.values():
                for pattern in request_handler.request_matcher.protection_patterns:
                    yield pattern

        self.logger.debug('Protecting tags')
        gitlab_tools.protect_tags(self.gl, project.id, patterns())
        project = gitlab_tools.wait_for_fork(self.gl, project)
        self.logger.debug(f'Protecting branch {self.course.config.branch.master}')
        gitlab_tools.protect_branch(self.gl, project, self.course.config.branch.master, delete_prev = True)
        return project

    # TODO:
    # Debug what happens when running this without the grading project having been created.
    # For some reason, project.delete seems to trigger an exception.
    def create_group_projects_fast(self, exist_ok = False):
        '''
        Create all student projects for this lab.
        Each project is forked from the staging project and appropriately configured.
        '''
        with self.with_staging_project() as staging_project:
            projects = dict()

            try:
                for group_id in self.course.groups:
                    c = self.student_group(group_id).project
                    self.logger.info(f'Forking project {c.path}')
                    try:
                        projects[group_id] = staging_project.forks.create({
                            'namespace_path': str(c.path.parent),
                            'path': c.path.name,
                            'name': c.name,
                        })
                    except gitlab.GitlabCreateError as e:
                        if exist_ok and e.response_code == 409:
                            if self.logger:
                                self.logger.info('Skipping because project already exists')
                        else:
                            raise

                for (group_id, project) in tuple(projects.items()):
                    self.logger.info(f'Configuring project {project.path_with_namespace}')
                    project = self.configure_student_project(project)
                    project.delete_fork_relation()
                    self.student_group(group_id).project.get = project
                    del projects[group_id]
                    self.student_group(group_id).repo_add_remote()
            except:  # noqa: E722
                for project in projects.values():
                    self.gl.projects.delete(project.path_with_namespace)
                raise

    def create_group_projects(self):
        for group_id in self.course.groups:
            self.student_group(group_id).project.create()

    def delete_group_projects(self):
        for group_id in self.course.groups:
            self.student_group(group_id).project.delete()

    def hotfix_groups(self, branch_hotfix):
        '''
        Attempt to apply a hotfix to all student projects.
        This calls 'hotfix_group' with the master/main branch.
        If any groups have created separate branches and you wish to hotfix those, use the 'hotfix_group' method.
        '''
        for group_id in self.course.groups:
            self.student_group(group_id).hotfix(branch_hotfix, self.course.config.branch.master)

    def repo_fetch_all(self):
        '''
        Fetch from the official repository and all student repositories.
        '''
        self.logger.info('Fetching from official project and student projects.')

        def remotes():
            yield self.course.config.path_lab.official
            for group in self.student_groups:
                yield group.remote
        self.repo_command_fetch(remotes())

    @functools.cached_property
    def remote_tags(self):
        '''
        A dictionary mapping each group id to a dictionary of key-value pairs (path, ref) where:
        - path is the tag name in the remote repository (converted to pathlib.PurePosixPath).
        - ref is an instance of git.Reference for the reference in refs/remote_tags/<full group id>.

        Clear this cached property after fetching.
        '''
        refs = git_tools.references_hierarchy(self.repo)
        remote_tags = refs[git_tools.refs.name][git_tools.remote_tags.name]

        def f():
            for group_id in self.course.groups:
                value = remote_tags.get(self.course.config.group.full_id.print(group_id), dict())
                yield (group_id, git_tools.flatten_references_hierarchy(value))
        return dict(f())

    @functools.cached_property
    def tags(self):
        '''
        A dictionary hierarchy of tag path name segments
        with values in tags in the local grading repository.

        Clear this cached property after constructing tags.
        '''
        refs = git_tools.references_hierarchy(self.repo)
        return refs[git_tools.refs.name][git_tools.tags.name]

    def hooks_create(self, netloc = None):
        '''
        Create webhooks in all group project in this lab on GitLab with the given net location.
        See group_project.GroupProject.hook_create.
        Returns a dictionary mapping group ids to hooks.

        Use this method only if you intend to create and
        delete webhooks over separate program invocations.
        Otherwise, the context manager hooks_manager is more appropriate.
        '''
        self.logger.info('Creating project hooks in all student projects')
        hooks = dict()
        try:
            for group in self.student_groups:
                hooks[group.id] = group.hook_create(netloc = netloc)
            return hooks
        except:  # noqa: E722
            for (group_id, hook) in hooks.items():
                self.student_group(group_id).hook_delete(hook)
            raise

    def hooks_delete(self, hooks):
        '''
        Delete webhooks in student projects in this lab on on GitLab.
        Takes a dictionary mapping each group id to its hook.
        See group_project.GroupProject.hook_delete.
        '''
        self.logger.info('Deleting project hooks in all student projects')
        for group in self.student_groups:
            group.hook_delete(hooks[group.id])

    def hooks_delete_all(self, except_for = ()):
        '''
        Delete all webhooks in all group project in this lab set up with the given netloc on GitLab.
        See group_project.GroupProject.hook_delete_all.
        '''
        for group in self.student_groups:
            group.hooks_delete_all(except_for = except_for)

    @contextlib.contextmanager
    def hooks_manager(self, netloc = None):
        '''
        A context manager for installing GitLab web hooks for all student projects in this lab.
        This is an expensive operation, setting up and cleaning up costs one HTTP call per project.
        Yields a dictionary mapping each group id to the hook installed in the project of that group.
        '''
        with contextlib.ExitStack() as stack:
            try:
                self.logger.info('Creating project hooks in all student projects')

                def f():
                    for group in self.student_groups:
                        yield (group.id, stack.enter_context(group.hook_manager(netloc = netloc)))
                yield dict(f())
            finally:
                self.logger.info('Deleting project hooks in all student projects (do not interrupt)')

    # Alternative implementation
    # @contextlib.contextmanager
    # def hooks_manager(self, netloc):
    #     hooks = self.hooks_create(netloc)
    #     try:
    #         yield hooks
    #     finally:
    #         self.hooks_delete(hooks)

    def setup_request_handlers(self):
        '''
        Setup the configured request handlers.
        This method must be called before requests can be processed.
        '''
        self.logger.info('Setting up request handlers')
        for handler in self.config.request_handlers.values():
            handler.setup(self)

    def setup_live_submissions_table(self, deadline = None):
        '''
        Setup the live submissions table.
        Takes an optional deadline parameter for limiting submissions to include.
        If not set, we use self.deadline.
        Request handlers should be set up before calling this method.
        '''
        if deadline is None:
            deadline = self.deadline
        config = live_submissions_table.Config(deadline = deadline)

        self.live_submissions_table = live_submissions_table.LiveSubmissionsTable(
            self,
            config = config,
            column_types = self.submission_handler.grading_columns,
        )

    def setup(self, deadline = None, use_live_submissions_table = True):
        '''
        General setup method.
        Call before any request processing is started.

        Arguments:
        * deadline:
            Passed to setup_live_submissions_table.
            If set, overrides self.deadline.
        * use_live_submissions_table:
            Whether to build and update a live submissions table
            of submissions needing reviews (by graders).
        '''
        if deadline is None:
            deadline = self.deadline

        self.setup_request_handlers()
        if use_live_submissions_table:
            self.setup_live_submissions_table(deadline = self.deadline)

    def parse_request_tags(self, from_gitlab = True):
        '''
        Parse request tags for group projects in this lab.
        This calls parse_request_tags in each contained group project.
        The boolean parameter from_gitlab determines if:
        * (True) tags read from Chalmers GitLab (a HTTP call)
        * (False) tags are read from the local grading repository.

        This method needs to be called before requests_and_responses
        in each contained handler data instance can be accessed.
        '''
        self.logger.info('Parsing request tags.')
        for group in self.student_groups:
            group.parse_request_tags(from_gitlab = from_gitlab)

    def parse_response_issues(self):
        '''
        Parse response issues for group projects on in this lab.
        This calls parse_response_issues in each contained group project.
        Cost: one HTTP call per group.

        This method needs to be called before requests_and_responses
        in each contained handler data instance can be accessed.

        Returns the frozen set of group ids with changes in review issues (if configured).
        '''
        self.logger.info('Parsing response issues.')

        def f():
            for group in self.student_groups:
                if group.parse_response_issues():
                    yield group.id
        return frozenset(f())

    def parse_requests_and_responses(self, from_gitlab = True):
        '''Calls parse_request_tags and parse_response_issues.'''
        self.parse_request_tags(from_gitlab = from_gitlab)
        self.parse_response_issues()

    def process_group_request(self, group):
        '''
        Process a request in a group.
        See GroupProject.process_request.

        Returns a boolean indicating if a submission was newly processed.
        '''
        requests_new = group.process_requests()
        return requests_new[self.config.submission_handler_key]

    def process_requests(self):
        '''
        Process requests in group projects in this lab.
        This skips requests already marked as handled in the local grading repository.
        Before calling this method, the following setups steps need to have been executed:
        * self.setup_handlers()
        * requests and responses need to be up to date.
          Update responses before updating requests to avoid responses with no matching request.

        Returns the frozen set of group ids with newly processed submissions.
        '''
        self.logger.info('Processing requests.')
        self.submission_solution.process_request()

        def f():
            for group in self.student_groups:
                requests_new = group.process_requests()
                if requests_new[self.config.submission_handler_key]:
                    yield group.id
        return frozenset(f())

    @functools.cached_property
    def submission_handler(self):
        '''The submission handler specified by the lab configuration.'''
        return self.config.request_handlers[self.config.submission_handler_key]

    @functools.cached_property
    def have_reviews(self):
        '''Whether review response issues are configured.'''
        return self.submission_handler.review_response_key is not None

    @functools.cached_property
    def review_template_issue(self):
        '''
        The submission review template issue specified by the lab configuration.
        Parsing this on first access takes an HTTP call.
        None if no submission review is configured.
        '''
        if self.submission_handler.review_response_key is None:
            return None

        self.logger.debug('Retrieving template issue.')

        def parser(issue):
            try:
                self.course.config.grading_response_template.parse(issue.title)
            except Exception:
                return None
            return ((), issue)

        u = dict()

        item_parser.parse_all_items(
            item_parser.Config(
                location_name = 'official lab project',
                item_name = 'official response issue',
                item_formatter = gitlab_tools.format_issue_metadata,
                logger = self.logger,
            ),
            [(parser, f'{self.submission_handler.review_response_key} template issue', u)],
            gitlab_tools.list_all(self.official_project.lazy.issues),
        )
        return u.get(())

    def handle_requests(self):
        self.logger.info('Handling request tags.')
        for group in self.student_groups:
            group.handle_requests()

    @contextlib.contextmanager
    def checkout_with_empty_bin_manager(self, commit):
        '''
        Context manager for a checked out commit and an empty directory
        that is used for transient results such as compilation products.
        '''
        with git_tools.checkout_manager(self.repo, commit) as src:
            with tempfile.TemporaryDirectory() as bin:
                yield (src, Path(bin))

    @functools.cached_property
    def head_problem(self):
        return git_tools.normalize_branch(self.repo, self.course.config.branch.problem)

    @functools.cached_property
    def head_solution(self):
        return git_tools.normalize_branch(self.repo, self.course.config.branch.solution)

    @functools.cached_property
    def submission_problem(self):
        return group_project.RequestAndResponses(
            self,
            None,
            self.course.config.branch.problem,
            (self.head_problem, self.head_problem.commit),
        )

    @functools.cached_property
    def submission_solution(self):
        return group_project.RequestAndResponses(
            self,
            None,
            self.course.config.branch.solution,
            (self.head_solution, self.head_solution.commit),
        )

    @functools.cached_property
    def compiler(self):
        if self.config.compiler is not None:
            self.config.compiler.setup(self)
        return self.config.compiler

    def checkout_problem(self):
        '''A context manager for the checked out problem head (path.Path).'''
        return git_tools.checkout_manager(self.repo, self.head_problem)

    @contextlib.contextmanager
    def checkout_and_compile_problem(self):
        with self.checkout_with_empty_bin_manager(self.head_problem) as (src, bin):
            if self.compiler is not None:
                self.compiler.compile(src, bin)
                yield (src, bin)

    def groups_with_live_submissions(self, deadline = None):
        '''A generator for groups with live submissions for the given optional deadline.'''
        for group_id in self.course.groups:
            group = self.student_group(group_id)
            if group.submission_current(deadline = deadline) is not None:
                yield group_id

    @contextlib.contextmanager
    def live_submissions_table_staging_manager(self):
        try:
            yield
        finally:
            self.file_live_submissions_table_staging.unlink(missing_ok = True)

    def update_live_submissions_table(self, group_ids = None):
        '''
        Updates the live submissions table on Canvas.
        Before calling this method, all group rows in the
        live submissions table need to have been updated.

        See LiveSubmissionsTable.build for argument descriptions.
        '''
        self.logger.info('Updating live submissions table')
        with self.live_submissions_table_staging_manager():
            self.live_submissions_table.build(
                self.file_live_submissions_table_staging,
                group_ids = group_ids,
            )
            if path_tools.file_content_eq(
                self.file_live_submissions_table_staging,
                self.file_live_submissions_table,
                missing_ok_b = True,
            ):
                self.logger.debug(
                    'Live submissions table has not changed, '
                    'skipping upload to Canvas.'
                )
                self.file_live_submissions_table_staging.unlink()
            else:
                self.logger.info('Posting live submissions table to Canvas')
                target = self.config.canvas_path_awaiting_grading
                self.course.canvas_course.post_file(
                    self.file_live_submissions_table_staging,
                    self.course.canvas_course.get_folder_by_path(target.parent).id,
                    target.name,
                )
                self.file_live_submissions_table_staging.replace(
                    self.file_live_submissions_table,
                )

    def parse_issue(self, issue):
        request_types = self.config.request.__dict__
        for (request_type, spec) in request_types.items():
            for (response_type, pp) in spec.issue.__dict__.items():
                try:
                    return (request_type, response_type, pp.parse(issue.title))
                except Exception:
                    continue

    def parse_grading_issues(self):
        for group_id in self.course.groups(self):
            self.student_group(group_id).grading_issues = dict()

        r = self.course.parse_response_issues(self.grading_project)
        for ((request, response_type), value) in r.items():
            (group_id, request) = self.course.qualify_with_slash.parse(request)
            self.student_group(group_id).grading_issues[(request, response_type)] = value

    @functools.cached_property
    def grading_sheet(self):
        return self.course.grading_spreadsheet.ensure_grading_sheet(self.id)

    def normalize_group_ids(self, group_ids = None):
        '''TODO: move to course.Course?'''
        return self.course.groups if group_ids is None else group_ids

    def include_group_in_grading_sheet(self, group, deadline = None):
        '''
        We include a group in the grading sheet if it has a student member or a submission.
        TOOD: make configurable in course configuration.
        '''
        if deadline is None:
            deadline = self.deadline

        return group.non_empty() or list(group.submissions_relevant(deadline))

    def update_grading_sheet(self, group_ids = None, deadline = None):
        '''
        Update the grading sheet.

        Arguments:
        * group_ids:
            If set, restrict the update to the given group ids.
        * deadline:
            Deadline to use for submissions.
            If not set, we use self.deadline.
        '''
        if deadline is None:
            deadline = self.deadline

        group_ids = self.normalize_group_ids(group_ids)
        groups = [
            group
            for group in map(self.student_group, group_ids)
            if self.include_group_in_grading_sheet(group, deadline)
        ]

        # Refresh grading sheet cache.
        self.grading_sheet.clear_cache()

        # Ensure grading sheet has rows for all required groups.
        self.grading_sheet.setup_groups(
            groups = [group.id for group in groups],
            group_link = lambda group_id: self.student_group(group_id).project.get.web_url,
        )

        # Ensure grading sheet has sufficient query group columns.
        self.grading_sheet.ensure_num_queries(max(
            (general.ilen(group.submissions_relevant(deadline)) for group in groups),
            default = 0,
        ))

        request_buffer = self.course.grading_spreadsheet.create_request_buffer()
        for group in groups:
            for (query, submission) in enumerate(group.submissions_relevant(deadline)):
                if submission.outcome is None:
                    grader = None
                    outcome = None
                else:
                    grader = google_tools.sheets.cell_value(submission.informal_grader_name)
                    outcome = google_tools.sheets.cell_link_with_fields(
                        self.course.config.outcome.as_cell.print(submission.outcome),
                        submission.outcome_issue.web_url,
                    )

                self.grading_sheet.write_query(
                    request_buffer,
                    group.id,
                    query,
                    grading_sheet.Query(
                        submission = google_tools.sheets.cell_link_with_fields(
                            submission.request_name,
                            gitlab_tools.url_tag_name(group.project.get, submission.request_name),
                        ),
                        grader = grader,
                        score = outcome,
                    ),
                )
        request_buffer.flush()

    def update_submission_systems(self, group_ids = None, deadline = None):
        '''
        Update the submission systems for specified groups.
        The submission systems are:
        - grading project on Chalmers GitLab,
        - live submissions table (if set up),
        - grading sheet.

        Arguments:
        * group_ids:
            Iterable for group_ids to restrict updates to.
            Defaults to all groups.
        * deadline:
            Passed to update_grading_sheet.
            If set, overrides self.deadline.
        '''
        if group_ids is None:
            group_ids = self.course.groups
        group_ids = tuple(group_ids)

        # Clear group members cache.
        for group_id in group_ids:
            self.student_group(group_id).members_clear()

        # Update submission systems.
        if hasattr(self, 'live_submissions_table'):
            self.live_submissions_table.update_rows(group_ids = group_ids)
        self.repo_push()
        if group_ids:
            if hasattr(self, 'live_submissions_table'):
                self.update_live_submissions_table()
            self.update_grading_sheet(group_ids = group_ids)

    def initial_run(self, deadline = None):
        '''
        Does an initial run of processing everything.
        Assumes that setup has already occurred.

        Arguments:
        * deadline:
            Passed to update_grading_sheet.
            If set, overrides self.deadline.
        '''
        self.parse_response_issues()
        self.repo_fetch_all()
        self.parse_request_tags(False)
        self.process_requests()
        self.update_submission_systems(deadline = deadline)

    def refresh_lab(self):
        '''
        Refresh group project requests and responses.
        Should be called regularly even if webhooks are in place.
        This is because webhooks can fail to trigger
        or the network connection may be done.
        '''
        self.logger.info('Refreshing lab.')
        review_updates = frozenset(self.parse_response_issues())

        self.repo_fetch_all()
        self.parse_request_tags(from_gitlab = False)
        new_submissions = frozenset(self.process_requests())

        # Update submission system.
        self.logger.info(f'Groups with new submissions: {new_submissions}')
        self.logger.info(f'Groups with review updates: {review_updates}')
        self.update_submission_systems(group_ids = review_updates | new_submissions)

    def refresh_group(self, group, refresh_responses = True):
        '''
        Refresh requests and responses in a single group in this lab.
        Typically called after notification by a webhook.

        Arguments:
        * group_id: The id of the group to refresh.
        * refresh_responses: If set to False, responses will not be updated.
        '''
        suffix = '' if refresh_responses else ' (requests only)'
        self.logger.info(f'Refreshing {group.name}{suffix}.')

        review_updates = refresh_responses and group.parse_response_issues()
        group.repo_fetch()
        # Setting from_gitlab = True results in a single HTTP call.
        # It might be faster if we have a large number of remote tags.
        group.parse_request_tags(from_gitlab = False)
        new_submissions = self.process_group_request(group)

        # Update submission system.
        if new_submissions:
            self.logger.info('New submissions received.')
        if review_updates:
            self.logger.info('New review updates received.')
        self.update_submission_systems(group_ids = filter(
            lambda _: review_updates or new_submissions, [group.id]
        ))

    def update_grading_sheet_and_live_submissions_table(self, deadline = None):
        '''Does what it says.'''
        self.setup(deadline = deadline)
        self.initial_run(deadline = deadline)

    def checkout_tag_hierarchy(self, dir):
        '''
        Check out all tags in the grading repository in a hierarchy based at dir.
        The directory dir and its parents are created if they do not exist.
        To save space, tags are omitted if they satisfy one of the following conditions:
        - ultimate path segment is 'handled',
        - penultimate path segment is 'after'.
        This is to save space; the content of these tags
        # is identical to that the respective parent tag.

        Use this function to more quickly debug issues with contents of the grading repository.
        '''
        for (path, tag) in git_tools.flatten_references_hierarchy(self.tags).items():
            if any([
                path.name == 'handled',
                len(path.parents) > 0 and path.parent.name == 'after',
            ]):
                continue

            out = dir / path
            out.mkdir(parents = True)
            git_tools.checkout(self.repo, out, tag)

    @functools.cached_property
    def group_by_gitlab_username(self):
        def f():
            for group in self.student_groups:
                for gitlab_user in group.members:
                    yield (gitlab_user.username, group)
        return general.sdict(f(), format_value = lambda group: group.name)

    def group_by_gitlab_username_clear(self):
        with contextlib.suppress(AttributeError):
            del self.group_by_gitlab_username

    def grading_report(self, scoring = None):
        '''
        Prepare a grading report for this lab.
        This returns a map sending usernames on Chalmers GitLab to scores.
        Scores are user-defined.

        Arguments:
        * scoring:
            A function taking a list of submission outcomes and returning a score.
            Defaults to None for no submissions and the maximum function otherwise.
        '''
        return {
            gitlab_username: group.get_score(scoring = scoring)
            for (gitlab_username, group) in self.group_by_gitlab_username.items()
        }

    def parse_hook_event(self, hook_event, group_id, strict = False):
        '''
        Arguments:
        * hook_event:
            Dictionary (decoded JSON).
            Event received from a webhook in this lab.
        * group_id:
            Group id parsed from the event project path.
        * strict:
            Whether to fail on unknown events.

        Returns an iterator of pairs of:
        - an instance of events.LabEvent,
        - a callback function to handle the event.
        These are the lab events triggered by the webhook event.
        '''
        if group_id in self.course.groups:
            group = self.student_group(group_id)
            yield from webhook_listener.map_with_callback(
                group.lab_event,
                group.parse_hook_event(hook_event, strict = strict),
            )
        else:
            if strict:
                raise ValueError(f'Unknown group id {group_id}')

            self.logger.warning(f'Received webhook event for unknown group id {group_id}.')
            self.logger.debug(f'Webhook event:\n{hook_event}')

    @property
    def course_event(self):
        return lambda lab_event: events.CourseEventInLab(
            lab_id = self.id,
            lab_event = lab_event,
        )
