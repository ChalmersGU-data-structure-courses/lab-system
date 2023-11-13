import abc
import contextlib
import functools
import logging
from pathlib import Path
import shutil
import tempfile
from typing import Iterable

import git
import gitlab
import gitlab.v4.objects.tags

import events
import general
import git_tools
import gitlab_tools
import google_tools.sheets
import grading_sheet
import grading_via_merge_request
import group_project
import instance_cache
import live_submissions_table
import path_tools
import print_parse
import webhook_listener


class StudentConnector(abc.ABC):
    @abc.abstractmethod
    def desired_groups(self):
        '''
        The set of desired group ids.
        These usually come from the Canvas course.
        '''
        ...

    @abc.abstractmethod
    def desired_members(self, id):
        '''
        The set of CIDs for a given group id.
        These usually come from the Canvas course.
        '''
        ...

    @abc.abstractmethod
    def gitlab_group_slug_pp(self):
        '''
        '''
        ...

    @abc.abstractmethod
    def gitlab_group_name(self, id):
        '''The corresponding name on Chalmers GitLab a given group id.'''
        ...

    @abc.abstractmethod
    def gdpr_coding(self):
        '''
        GDPR coding for group ids (instance of GDPRCoding).
        Currently only used in the grading spreadsheet.
        '''
        ...

    @abc.abstractmethod
    def gdpr_link_problematic(self):
        '''
        Whether gorup links can be set in non-GDPR-cleared documents.
        Currently only used in the grading spreadsheet.
        '''
        ...

class StudentConnectorIndividual(StudentConnector):
    def __init__(self, course):
        self.course = course

    def desired_groups(self):
        def f():
            for canvas_user in self.course.canvas_course.students:
                gitlab_username = self.course.gitlab_username_from_canvas_user_id(canvas_user.id, strict = False)
                if not gitlab_username is None:
                    yield gitlab_username

        return frozenset(f())

    def gitlab_group_slug_pp(self):
        def print(x):
            return x.strip('1')

        def parse(x):
            if x == 'test':
                return 'test'

            if x in self.course.canvas_user_by_gitlab_username:
                return x
            y = x + '1'
            if y in self.course.canvas_user_by_gitlab_username:
                return y
            return None

        return print_parse.PrintParse(
            print = print,
            parse = parse,
        )

    def gitlab_group_name(self, id):
        if id == 'test':
            return 'Test Student'

        canvas_user = self.course.canvas_user_by_gitlab_username.get(id)
        if canvas_user is None:
            return f'{id} — not on Canvas'

        return canvas_user.name

    def desired_members(self, id):
        return frozenset([id])

    def gdpr_coding(self):
        return self.course.student_name_coding.gdpr_coding

    def gdpr_link_problematic(self):
        return False

class StudentConnectorGroupSet(StudentConnector):
    def __init__(self, group_set):
        self.group_set = group_set

    def desired_groups(self):
        return frozenset(
            self.group_set.config.name.parse(canvas_group.name)
            for canvas_group in self.group_set.canvas_group_set.details.values()
        )

    def desired_members(self, id):
        def f():
            canvas_name = self.group_set.config.name.print(id)
            canvas_id = self.group_set.canvas_group_set.name_to_id[canvas_name]
            for canvas_user_id in self.group_set.canvas_group_set.group_users[canvas_id]:
                gitlab_username = self.group_set.course.gitlab_username_from_canvas_user_id(canvas_user_id, strict = False)
                if not gitlab_username is None:
                    yield gitlab_username

        return frozenset(f())

    def gitlab_group_slug_pp(self):
        return self.group_set.config.full_id

    def gitlab_group_name(self, id):
        return self.group_set.config.name.print(id)

    def gdpr_coding(self):
        return self.group_set.config.gdpr_coding

    def gdpr_link_problematic(self):
        return True

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
        self.deadline = deadline

        self.dir = None if dir is None else Path(dir)
        if self.dir:
            self.dir.mkdir(exist_ok = True)

        self.config = self.course.config.labs[id] if config is None else config

        # Naming config
        self.id_str = self.course.config.lab.id.print(self.id)
        self.name = self.course.config.lab.name.print(self.id)
        self.name_semantic = (self.config.path_source / 'name').read_text().strip()
        self.name_full = '{} — {}'.format(self.name, self.name_semantic)

        # Student connector
        if self.config.group_set:
            group_set = self.course.get_group_set(self.config.group_set)
            self.student_connector = StudentConnectorGroupSet(group_set)
        else:
            self.student_connector = StudentConnectorIndividual(self.course)

        # Gitlab config
        self.path = self.course.path / self.course.config.lab.full_id.print(self.id)

        # Local grading repository config.
        self.dir_repo = None if self.dir is None else self.dir / 'repo'
        # Whether we have updated the repository and it needs to be pushed.
        self.repo_updated = False

        # Other local data.
        self.file_live_submissions_table = self.dir / 'live-submissions-table.html'
        self.file_live_submissions_table_staging = path_tools.add_suffix(
            self.file_live_submissions_table,
            '.staging',
        )

        if self.config.grading_via_merge_request:
            self.grading_via_merge_request_setup_data = grading_via_merge_request.SetupData(self)
            self.dir_status_repos = None if self.dir is None else self.dir / 'status-repos'
            if self.dir_status_repos:
                self.dir_status_repos.mkdir(exist_ok = True)

        # Qualify a request by the full group id.
        # Used as tag names in the grading repository of each lab.
        # TODO: unused?
        self.qualify_request = print_parse.compose(
            print_parse.on(general.component_tuple(0), self.student_connector.gitlab_group_slug_pp()),
            print_parse.qualify_with_slash
        )

    @property
    def gl(self):
        return self.course.gl

    @functools.cached_property
    def gitlab_group(self):
        '''
        The group for this lab on Chalmers GitLab.
        '''
        r = gitlab_tools.CachedGroup(
            gl = self.gl,
            logger = self.logger,
            path = self.path,
            name = self.name,
        )

        def create():
            gitlab_tools.CachedGroup.create(
                r,
                self.course.course_group.get,
                description = self.name_semantic,
            )
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
        The student lab projects are forked from this.
        On creation:
        * The contents of the main branch are taken from the problem folder of the specified local lab directory
          (together with an optionally specified .gitignore file).
          So make sure this directory is clean beforehand.

        This used to contain branches "problem" and "solution".
        * Branch "problem" does not exist anymore.
        * Branch "solution" is now part of the grading project instead.
        '''
        r = gitlab_tools.CachedProject(
            gl = self.gl,
            logger = self.logger,
            path = self.path / self.course.config.path_lab.official,
            name = 'Primary repository',
        )

        def create():
            project = gitlab_tools.CachedProject.create(r, self.gitlab_group.get)
            try:
                with tempfile.TemporaryDirectory() as dir:
                    repo = git.Repo.init(dir)

                    def push_branch(name, path, message):
                        shutil.copytree(path, dir, dirs_exist_ok = True, symlinks = True)
                        repo.git.add('--all', '--force')
                        repo.git.commit('--allow-empty', message = message)
                        repo.git.push(project.ssh_url_to_repo, git_tools.refspec(
                            git_tools.head,
                            git_tools.local_branch(name),
                            force = True
                        ))

                    if self.config.path_gitignore:
                        shutil.copyfile(self.config.path_gitignore, Path(dir) / '.gitignore')
                    push_branch(
                        self.course.config.branch.master,
                        self.config.path_source / 'problem',
                        'Initial commit.',
                    )

                project.lfs_enabled = False
                project.wiki_enabled = False
                project.packages_enabled = False
                project.jobs_enabled = False
                project.snippets_enabled = False
                project.container_registry_enabled = False
                project.service_desk_enabled = False
                project.shared_runners_enabled = False
                project.ci_forward_deployment_enabled = False
                project.ci_job_token_scope_enabled = False
                project.public_jobs = False
                project.remove_source_branch_after_merge = False
                project.auto_devops_enabled = False
                project.keep_latest_artifact = False
                project.requirements_enabled = False
                project.security_and_compliance_enabled = False
                project.request_access_enabled = False
                project.analytics_access_level = 'disabled'
                project.operations_access_level = 'disabled'
                project.releases_access_level = 'disabled'
                project.pages_access_level = 'disabled'
                project.security_and_compliance_access_level = 'disabled'
                project.environments_access_level = 'disabled'
                project.feature_flags_access_level = 'disabled'
                project.infrastructure_access_level = 'disabled'
                project.monitor_access_level = 'disabled'
                project.emails_disabled = False
                project.permissions = {'project_access': None, 'group_access': None}
                project.save()

            except:  # noqa: E722
                r.delete()
                raise
        r.create = create

        return r

    @functools.cached_property
    def grading_project(self):
        '''
        The grading project on Chalmers GitLab.
        When created, it is empty.
        '''
        r = gitlab_tools.CachedProject(
            gl = self.gl,
            logger = self.logger,
            path = self.path / self.course.config.path_lab.grading,
            name = 'Collection repository',
        )

        def create():
            gitlab_tools.CachedProject.create(r, self.gitlab_group.get)
        r.create = create

        return r

    @functools.cached_property
    def groups(self):
        # def actual_project(x):
        #     return all([
        #         not x in [self.course.config.path_lab.official, self.course.config.path_lab.grading],
        #         not x.endswith('-playground'),
        #         not x.endswith('-grading'),
        #     ])

        def f():
            for group in gitlab_tools.list_all(self.gitlab_group.lazy.subgroups):
                group_id = self.student_connector.gitlab_group_slug_pp().parse(group.path)
                if not group_id is None:
                    yield group_id

        return frozenset(f())

    def group_delete_all(self):
        for group_id in self.groups:
            self.student_group(group_id).group.delete()

        for x in ['groups', 'student_groups']:
            with contextlib.suppress(AttributeError):
                delattr(self, x)

    def create_groups_from_canvas(self, delete_existing = False):
        if delete_existing:
            self.group_delete_all()
        groups_old = () if delete_existing else self.groups

        for group_id in self.student_connector.desired_groups():
            if not group_id in groups_old:
                self.student_group(group_id).group.create()

        with contextlib.suppress(AttributeError):
            del self.groups

    @instance_cache.instance_cache
    def student_group(self, group_id):
        return group_project.GroupProject(self, group_id)

    @functools.cached_property
    def student_groups(self):
        return {group_id: self.student_group(group_id) for group_id in self.groups}

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
        for group_id in self.groups:
            self.student_group(group_id).repo_add_remote(ignore_missing = True)

    def repo_delete(self, force = False):
        '''
        Delete the repository directory.
        Warning: Make sure that self.dir is correctly configured before calling.
        '''
        try:
            shutil.rmtree(self.dir_repo)
        except FileNotFoundError:
            if not force:
                raise

    def repo_init(self, bare = False):
        '''
        Initialize the local grading repository.
        If the directory exists, we assume that all remotes are set up.
        Otherwise, we create the directory and populate it with remotes on Chalmers GitLab as follows.
        Fetching remotes are given by the official repository and student group repositories.
        Pushing remotes are just the grading repository.
        '''
        self.logger.info('Initializing local grading repository.')
        try:
            repo = git.Repo.init(str(self.dir_repo), bare = bare)
            with repo.config_writer() as c:
                c.add_value('advice', 'detachedHead', 'false')

            # Configure and fetch official repository.
            self.repo_add_remote(
                self.course.config.path_lab.official,
                self.official_project.get,
                fetch_branches = [(git_tools.Namespacing.local, self.course.config.branch.master)],
                fetch_tags = [(git_tools.Namespacing.local, git_tools.wildcard)],
            )
            self.repo_fetch_official()

            # Add optional solution.
            if self.config.has_solution:
                self.repo_add_solution()

            # Configure offical grading repository and student groups.
            def push_branches():
                yield self.course.config.branch.master
                if self.config.has_solution:
                    yield self.course.config.branch.solution

            self.repo_add_remote(
                self.course.config.path_lab.grading,
                self.grading_project.get,
                push_branches = list(push_branches()),
                push_tags = [git_tools.wildcard],
            )
            self.repo_add_groups_remotes(ignore_missing = True)
        except:  # noqa: E722
            shutil.rmtree(self.dir_repo, ignore_errors = True)
            raise

        self.repo = repo

    def repo_add_solution(self):
        '''
        Add solution to local repo.
        Call separately if solution has been added later.
        '''
        solution_tree = git_tools.create_tree_from_dir(self.repo, self.config.path_source / 'solution')
        commit = git.Commit.create_from_tree(
            self.repo,
            solution_tree,
            'Official solution.',
            [self.head_problem.commit],
        )
        self.repo.create_head(self.course.config.branch.solution, commit, force = True)

    def repo_remote_command(self, repo, command):
        if self.course.ssh_multiplexer is None:
            repo.git._call_process(*command)
        else:
            self.course.ssh_multiplexer.git_cmd(repo, command)

    def repo_command_fetch(self, repo, remotes):
        remotes = list(remotes)
        self.logger.debug(f'Fetching from remotes: {remotes}.')

        def command():
            yield 'fetch'
            yield '--update-head-ok'
            yield from ['--jobs', str(self.course.config.gitlab_ssh.max_sessions)]
            yield from ['--multiple', *remotes]
        self.repo_remote_command(repo, list(command()))

        # Update caching mechanisms.
        self.repo_updated = True
        with contextlib.suppress(AttributeError):
            del self.remote_tags

    def repo_command_push(self, repo, remote):
        self.logger.debug(f'Pushing to remote: {remote}.')

        def command():
            yield 'push'
            yield remote
        self.repo_remote_command(repo, list(command()))

    def repo_fetch_official(self):
        '''
        Fetch main branch from the offical repository on Chalmers GitLab to the local grading repository.
        '''
        self.logger.info('Fetching from primary repository.')
        self.repo_command_fetch(self.repo, [self.course.config.path_lab.official])

    def repo_push(self, force = False):
        '''
        Push the local grading repository to the grading repository on Chalmers GitLab.
        Only push if changes have been recorded.
        '''
        if self.repo_updated or force:
            self.logger.info('Pushing to grading repository.')
            self.repo_command_push(self.repo, self.course.config.path_lab.grading)
            self.repo_updated = False

    def configure_student_project(self, project):
        self.logger.debug(f'Configuring student project {project.path_with_namespace}')

        def patterns():
            for request_handler in self.config.request_handlers.values():
                for pattern in request_handler.request_matcher.protection_patterns:
                    yield pattern

        self.logger.debug('Protecting tags')
        gitlab_tools.protect_tags(self.gl, project.id, patterns())
        gitlab_tools.delete_protected_branches(project)

    def create_group_projects_fast(self, exist_ok = False):
        '''
        Create all student projects for this lab.
        Each project is forked from the staging project and appropriately configured.

        OUTDATED (non-functional), use create_group_projects instead.
        '''
        with self.with_staging_project() as staging_project:
            projects = dict()

            try:
                for group_id in self.groups:
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

    def create_group_projects(self, exist_ok = False):
        for group_id in self.groups:
            x = self.student_group(group_id).project
            if exist_ok:
                x.create_ensured()
            else:
                x.create()

    def delete_group_projects(self):
        for group_id in self.groups:
            self.student_group(group_id).project.delete()

    def hotfix_groups(
        self,
        branch_hotfix,
        group_ids = None,
        merge_files = False,
        fail_on_problem = True,
        notify_students: str = None,
    ):
        '''
        Attempt to apply a hotfix to all student projects.
        This calls 'hotfix_group' with the master/main branch.
        If any groups have created separate branches and you wish to hotfix those, use the 'hotfix_group' method.

        Flags:
        * merge_files: if True, attempt a 3-way merge to resolve conflicting files.
        * group_ids:
            Iterable for group_ids to hotfix.
            Defaults to all groups.
        * fail_on_problem:
            Fail with an exception if a merge cannot be performed.
            If False, only an error is logged.
        * notify_students:
            Notify student members of the hotfix commit by creating a commit comment with this message.
            The message is appended with mentions of the student members.

        Will log a warning if the merge has already been applied.
        '''
        for group_id in self.normalize_group_ids(group_ids):
            self.student_group(group_id).hotfix(
                branch_hotfix,
                self.course.config.branch.master,
                merge_files = merge_files,
                fail_on_problem = fail_on_problem,
                notify_students = notify_students,
            )

    def repo_fetch_all(self):
        '''
        Fetch from the official repository and all student repositories.
        '''
        self.logger.info('Fetching from official project and student projects.')

        def remotes():
            yield self.course.config.path_lab.official
            for group in self.student_groups.values():
                yield group.remote
        self.repo_command_fetch(self.repo, remotes())

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
            for group in self.student_groups.values():
                value = remote_tags.get(group.remote, dict())
                yield (group.id, git_tools.flatten_references_hierarchy(value))
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

    def hook_specs(self, netloc = None) -> Iterable[gitlab_tools.HookSpec]:
        for group in self.student_groups.values():
            yield from group.hook_specs(netloc)

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
        for group in self.student_groups.values():
            group.parse_request_tags(from_gitlab = from_gitlab)

    def parse_response_issues(self, on_duplicate = True, delete_duplicates = False):
        '''
        Parse response issues for group projects on in this lab.
        This calls parse_response_issues in each contained group project.
        Cost: one HTTP call per group.

        This method needs to be called before requests_and_responses
        in each contained handler data instance can be accessed.

        Arguments:
        * on_duplicate:
            - None: Raise an exception.
            - True: Log a warning and keep the first (newer) item.
            - False: Log a warning and keep the second (older) item.
        * delete_duplicates: if true, delete duplicate issues.

        Returns the frozen set of group ids with changes in review issues (if configured).
        '''
        self.logger.info('Parsing response issues.')

        def f():
            for group in self.student_groups.values():
                if group.parse_response_issues(on_duplicate = on_duplicate, delete_duplicates = delete_duplicates):
                    yield group.id
        return frozenset(f())

    @contextlib.contextmanager
    def parse_grading_merge_request_responses(self):
        '''
        This method assumes self.config.grading_via_merge_request is true.
        Parse grading merge request responses for group projects on in this lab.
        This calls parse_grading_merge_request_responses in each contained group project.
        Cost: two HTTP calls per group.

        This method needs to be called before requests_and_responses
        in each contained handler data instance can be accessed.

        Returns the frozen set of group ids with changes in review issues (if configured).

        This method is a context manager.
        Inside the context, grading merge requests have notes cache clear suppressed.
        process_requests benefits from being executed inside its scope.
        This is because processing requests may run GradingViaMergeRequest.sync_submissions.
        '''
        self.logger.info('Parsing grading merge request responses.')

        with contextlib.ExitStack() as stack:
            def f():
                for group in self.student_groups.values():
                    if group.parse_grading_merge_request_responses():
                        yield group.id
                    stack.enter_context(group.grading_via_merge_request.notes_suppress_cache_clear())
            yield frozenset(f())

    def parse_requests_and_responses(self, from_gitlab = True):
        '''
        Calls:
        * parse_response_issues
        * parse_grading_merge_request_responses (if configured)
        * parse_request_tags

        Does more HTTP requests for Chalmers GitLab than needed.
        '''
        self.parse_response_issues()
        if self.config.grading_via_merge_request:
            with self.parse_grading_merge_request_responses():
                pass
        self.parse_request_tags(from_gitlab = from_gitlab)

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

        If grading via merge request has been configured,
        benefits from being executed within the scope of parse_grading_merge_request_responses.
        This is because processing requests may run GradingViaMergeRequest.sync_submissions.
        '''
        self.logger.info('Processing requests.')
        if self.config.has_solution:
            self.submission_solution.process_request()

        def f():
            for group in self.student_groups.values():
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

    def handle_requests(self):
        self.logger.info('Handling request tags.')
        for group in self.student_groups.values():
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
        return git_tools.normalize_branch(self.repo, self.course.config.branch.master)

    @functools.cached_property
    def head_solution(self):
        if self.config.has_solution:
            return git_tools.normalize_branch(self.repo, self.course.config.branch.solution)

    @functools.cached_property
    def submission_problem(self):
        return group_project.RequestAndResponses(
            self,
            None,
            self.course.config.branch.master,
            (self.head_problem, self.head_problem.commit),
        )

    @functools.cached_property
    def submission_solution(self):
        if self.config.has_solution:
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
        for group_id in self.groups:
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
        for group_id in self.groups:
            self.student_group(group_id).grading_issues = dict()

        r = self.course.parse_response_issues(self.grading_project)
        for ((request, response_type), value) in r.items():
            (group_id, request) = self.course.qualify_with_slash.parse(request)
            self.student_group(group_id).grading_issues[(request, response_type)] = value

    @functools.cached_property
    def grading_sheet(self):
        return self.course.grading_spreadsheet.ensure_grading_sheet(self)

    def normalize_group_ids(self, group_ids = None):
        return self.student_connector.desired_groups() if group_ids is None else group_ids

    def include_group_in_grading_sheet(self, group, deadline = None):
        '''
        We include a group in the grading sheet if it has a submission.
        Extra groups to include can be configured in the grading sheet config using:
        * include_groups_with_no_submission
        '''
        if deadline is None:
            deadline = self.deadline

        return any([
            list(group.submissions_relevant(deadline)),
            self.course.config.grading_sheet.include_groups_with_no_submission and group.non_empty(),
        ])

    @functools.cached_property
    def grading_sheet_group_link(self):
        if not self.student_connector.gdpr_link_problematic:
            return lambda group_id: self.student_group(group_id).project.get.web_url

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
            group_link = self.grading_sheet_group_link,
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
                    grader = google_tools.sheets.cell_value(submission.grader_informal_name)
                    outcome = google_tools.sheets.cell_link_with_fields(
                        self.course.config.outcome.as_cell.print(submission.outcome),
                        submission.link,
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
            group_ids = self.groups
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
        with contextlib.ExitStack() as stack:
            self.parse_response_issues()
            if self.config.grading_via_merge_request:
                stack.enter_context(self.parse_grading_merge_request_responses())
            self.repo_fetch_all()
            self.parse_request_tags(False)
            self.process_requests()
        self.update_submission_systems(deadline = deadline)

    def refresh_lab(self):
        '''
        Refresh group project requests and responses.
        Should be called regularly even if webhooks are in place.
        This is because webhooks can fail to trigger or the network connection may be down.
        '''
        self.logger.info('Refreshing lab.')
        with contextlib.ExitStack() as stack:
            review_updates = self.parse_response_issues()
            if self.config.grading_via_merge_request:
                review_updates = review_updates | stack.enter_context(self.parse_grading_merge_request_responses())

            self.repo_fetch_all()
            self.parse_request_tags(from_gitlab = False)
            new_submissions = frozenset(self.process_requests())

        # Update submission system.
        self.logger.info(f'Groups with new submissions: {new_submissions}')
        self.logger.info(f'Groups with review updates: {review_updates}')
        self.update_submission_systems(group_ids = review_updates | new_submissions)

    def refresh_group(self, group, refresh_issue_responses = False, refresh_grading_merge_request = False):
        '''
        Refresh requests and responses in a single group in this lab.
        Typically called after notification by a webhook.

        Arguments:
        * group_id: The id of the group to refresh.
        * refresh_responses: If set to False, responses will not be updated.
        '''
        refresh_some_responses = refresh_issue_responses or refresh_grading_merge_request
        suffix = '' if refresh_some_responses else ' (requests only)'
        self.logger.info(f'Refreshing {group.name}{suffix}.')

        with contextlib.ExitStack() as stack:
            def f():
                x = refresh_issue_responses and group.parse_response_issues()
                if x:
                    self.logger.info('found response issue update')
                    yield x
                if self.config.grading_via_merge_request:
                    x = refresh_grading_merge_request and group.parse_grading_merge_request_responses()
                    if x:
                        self.logger.info('found merge request update')
                        stack.enter_context(group.grading_via_merge_request.notes_suppress_cache_clear())
                        yield x

            grading_updates = any(f())
            group.repo_fetch()
            # Setting from_gitlab = True results in a single HTTP call.
            # It might be faster if we have a large number of remote tags.
            group.parse_request_tags(from_gitlab = False)
            new_submissions = self.process_group_request(group)

        # Update submission system.
        if new_submissions:
            self.logger.info('New submissions received.')
        if grading_updates:
            self.logger.info('Grading updates received.')
        self.update_submission_systems(group_ids = filter(
            lambda _: grading_updates or new_submissions, [group.id]
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
            for group in self.student_groups.values():
                for gitlab_user in group.members:
                    yield (gitlab_user.username, group)
        return general.sdict(f(), format_value = lambda group: group.name)

    def group_by_gitlab_username_clear(self):
        with contextlib.suppress(AttributeError):
            del self.group_by_gitlab_username

    def grading_report(self, scoring = None, strict = True):
        '''
        Prepare a grading report for this lab.
        This returns a map sending usernames on Chalmers GitLab to scores.
        Scores are user-defined.

        Arguments:
        * scoring:
            A function taking a list of submission outcomes and returning a score.
            Defaults to None for no submissions and the maximum function otherwise.
        * strict:
            Refuse to compute score if there is an ungraded submission.
        '''
        return {
            gitlab_username: group.get_score(scoring = scoring, strict = strict)
            for (gitlab_username, group) in self.group_by_gitlab_username.items()
        }

    def parse_hook_event(self, hook_event, group_id_gitlab, strict = False):
        '''
        Arguments:
        * hook_event:
            Dictionary (decoded JSON).
            Event received from a webhook in this lab.
        * group_id_gitlab:
            Group id as appearing in the project path of the event.
        * strict:
            Whether to fail on unknown events.

        Returns an iterator of pairs of:
        - an instance of events.LabEvent,
        - a callback function to handle the event.
        These are the lab events triggered by the webhook event.
        '''
        group_id = self.student_connector.gitlab_group_slug_pp().parse(group_id_gitlab)
        if group_id in self.groups:
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

    def report_assignment_populate(self, scoring = None, strict = True):
        grades = self.grading_report(scoring = scoring, strict = strict)

        id = self.report_assignment_get().id
        submissions = self.course.canvas_course.get_submissions(id, use_cache = False)
        for submission in submissions:
            canvas_user_id = submission.user_id
            try:
                canvas_user = self.course.canvas_course.student_details[canvas_user_id]
            except KeyError:
                self.logger.warning(f'* Submission user {canvas_user_id} not a Canvas user (probably it is the test student).')
                continue

            gitlab_user = self.course.gitlab_user_by_canvas_id(canvas_user_id)
            if gitlab_user is None:
                self.logger.warning(f'* Canvas user {canvas_user.name} not on Chalmers GitLab.')
                continue

            try:
                grade = grades.pop(gitlab_user.username)
            except KeyError:
                self.logger.warning(f'* Canvas user {canvas_user.name} not in lab on Chalmers GitLab.')
                continue
            if grade is None:
                self.logger.warning(f'* {gitlab_user.username} ({canvas_user.name}): no graded submission')
                continue

            self.logger.info(f'* {canvas_user.name}: {grade}')
            canvas_grade = {
                0: 'incomplete',
                1: 'complete',
            }[grade]
            endpoint = self.course.canvas_course.endpoint + ['assignments', id, 'submissions', canvas_user_id]
            self.course.canvas.put(endpoint, {
                'submission[posted_grade]': canvas_grade
            })

        if grades:
            self.logger.warning('Chalmers GitLab users with unreported grades:')
            for (gitlab_username, grade) in grades.items():
                print(f'* {gitlab_username}: {grade}')

    def sync_students_to_gitlab(self, *, add = True, remove = True, restrict_to_known = True):
        '''
        Synchronize Chalmers GitLab student group membership according to the group membership on Canvas.

        If add is True, this adds missing members of groups on GitLab.
        An invitation is sent if a GitLab account is not found.
        If remove is True, this removes invitations and members not belonging to groups on GitLab.
        If any of these are False, a warning is logged instead of performing the action.

        If restrict_to_known is True, removals are restricted to invitations
        and members recognized as belonging to students in the Canvas course.
        This is recommended in case there are students participating
        in the labs that are not registered in the Canvas course.
        However, a registered student can then contrive to obtain duplicate group memberships
        by changing their primary email address on Canvas prior to changing groups and accepting invitations.

        Note in case remove is True and restrict_to_known is False:
        An exception is raised if a Canvas student cannot be resolved to a GitLab username.
        This is to prevent students from being unintentionally removed from their groups.

        This method is simpler than invite_students_to_gitlab.
        It does not use a ledger of past invitations.
        However, it only works properly if we can resolve Canvas students to Chalmers GitLab accounts.

        Call sync_students_to_gitlab(add = False, remove = False, restrict_to_known = False)
        to obtain (via logged warnings) a report of group membership deviations.
        '''
        self.logger.info('synchronizing students from Canvas groups to GitLab group')

        # We use @student.chalmers.se.
        # TODO: use info from LDAP
        suffix = '@student.chalmers.se'
        pp_email = print_parse.PrintParse(
            print = lambda x: x + suffix,
            parse = lambda x: general.remove_suffix(x, suffix),
        )

        def canvas_name(gitlab_username):
            try:
                canvas_user = self.course.canvas_user_by_gitlab_username[gitlab_username]
            except KeyError:
                return 'unknown Canvas student'
            return canvas_user.name

        def str_with_user_details(identifier, gitlab_username):
            return f'{identifier} ({canvas_name(gitlab_username)})'

        def known_gitlab_username_from_email(email):
            try:
                gitlab_username = pp_email.parse(email)
            except Exception:
                return None
            if not gitlab_username in self.course.canvas_user_by_gitlab_username:
                return None
            return gitlab_username

        def user_str_from_email(email):
            return str_with_user_details(email, known_gitlab_username_from_email(email))

        def user_str_from_gitlab_username(gitlab_username):
            return str_with_user_details(gitlab_username, gitlab_username)

        for group_id in self.student_connector.desired_groups():
            entity_name = f'{self.student_connector.gitlab_group_name(group_id)} on GitLab'
            entity = self.student_group(group_id).project.lazy

            # Current members and invitations.
            # If restrict_to_known holds, restricts to gitlab users and email addresses
            # recognized as belonging to Canvas students.
            self.logger.debug(f'checking {entity_name}')
            members = {
                gitlab_user.username
                for gitlab_user in gitlab_tools.members_dict(entity).values()
                if general.when(restrict_to_known, gitlab_user.username in self.course.canvas_user_by_gitlab_username)
            }

            def invitations():
                for email in gitlab_tools.invitation_dict(self.gl, entity):
                    if restrict_to_known and not known_gitlab_username_from_email(email):
                        continue
                    yield email
            invitations = frozenset(invitations())

            members_desired = set()
            invitations_desired = set()
            for gitlab_username in self.student_connector.desired_members(group_id):
                if self.course.gitlab_user(gitlab_username):
                    members_desired.add(gitlab_username)
                else:
                    invitations_desired.add(pp_email.print(gitlab_username))

            for email in invitations - invitations_desired:
                if email:
                    self.logger.warning(f'deleting invitation of {user_str_from_email(email)} to {entity_name}')
                    with gitlab_tools.exist_ok():
                        gitlab_tools.invitation_delete(self.gl, entity, email)
                else:
                    self.logger.warning(f'extra invitation of {user_str_from_email(email)} to {entity_name}')

            for gitlab_username in members - members_desired:
                if remove:
                    self.logger.warning(
                        f'removing {user_str_from_gitlab_username(gitlab_username)} from {entity_name}'
                    )
                    with gitlab_tools.exist_ok():
                        entity.members.delete(self.course.gitlab_user(gitlab_username).id)
                else:
                    self.logger.warning(
                        f'extra member {user_str_from_gitlab_username(gitlab_username)} of {entity_name}'
                    )

            for email in invitations_desired - invitations:
                if add:
                    self.logger.log(25, f'inviting {user_str_from_email(email)} to {entity_name}')
                    try:
                        with gitlab_tools.exist_ok():
                            gitlab_tools.invitation_create(self.gl, entity, email, gitlab.const.DEVELOPER_ACCESS)
                    except gitlab.exceptions.GitlabCreateError as e:
                        self.logger.error(str(e))
                else:
                    self.logger.warning(f'missing invitation of {user_str_from_email(email)} to {entity_name}')

            for gitlab_username in members_desired - members:
                if add:
                    self.logger.log(25, f'adding {user_str_from_gitlab_username(gitlab_username)} to {entity_name}')
                    with gitlab_tools.exist_ok():
                        entity.members.create({
                            'user_id': self.course.gitlab_user(gitlab_username).id,
                            'access_level': gitlab.const.DEVELOPER_ACCESS,
                        })
                else:
                    self.logger.warning(
                        f'missing member {user_str_from_gitlab_username(gitlab_username)} of {entity_name}'
                    )
