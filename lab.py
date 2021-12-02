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

import item_parser
import general
import git_tools
import gitlab_tools
import google_tools.sheets
import grading_sheet
import group_project
import instance_cache
import live_submissions_table


class Lab:
    '''
    This class abstracts over a single lab in a course.

    The lab is hosted on Chalmers GitLab.
    Related attributes and methods:
    - official_project, grading_project
    - create_group_projects, create_group_projects_fast
    - delete_group_projects
    - hook_manager

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
    - update_live_submissions_table(self, deadline = None):

    This class is configured by the config argument to its constructor.
    The format of this argument is documented in gitlab.config.py.template under _lab_config.

    This class manages instances of group_project.GroupProject.
    See student_group and student_groups.
    Each instance of this class is managed by an instance of course.Course.
    '''
    def __init__(self, course, id, config = None, dir = None, logger = logging.getLogger(__name__)):
        '''
        Initialize lab manager.
        Arguments:
        * course: course manager.
        * id: lab id, typically used as key in a lab configuration dictionary (see 'gitlab_config.py.template')
        * config: lab configuration, typically the value in a lab configuration dictionary.
                  If None, will be taken from labs dictionary in course configuration.
        * dir: Local directory used as local copy of the grading repository.
               Only its parent directory has to exist.
        '''

        self.logger = logger
        self.course = course
        self.id = id
        self.dir = None if dir is None else Path(dir)

        self.config = self.course.config.labs[id] if config is None else config

        # Naming config
        self.id_str = self.course.config.lab.id.print(self.id)
        self.name = self.course.config.lab.name.print(self.id)
        self.name_semantic = (self.config.path_source / 'name').read_text().strip()
        self.name_full = '{} — {}'.format(self.name, self.name_semantic)

        # Gitlab config
        self.path = self.course.config.path.labs / self.course.config.lab.id_gitlab.print(self.id)

        # Whether we have updated the grading repository
        # and it needs to be pushed.
        self.repo_updated = False

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
            return git.Repo(self.dir)
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
        repo = git.Repo.init(self.dir, bare = bare)
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

    def repo_fetch_official(self):
        '''
        Fetch problem and solution branches from the offical
        repository on Chalmers GitLab to the local grading repository.
        '''
        self.logger.info('Fetching from official repository.')
        self.repo.remote(self.course.config.path_lab.official).fetch('--update-head-ok')

    def repo_push(self, force = False):
        '''
        Push the local grading repository to the grading repository on Chalmers GitLab.
        Only push if changes have been recorded.
        '''
        if self.repo_updated or force:
            self.logger.info('Pushing to grading repository.')
            self.repo.remote(self.course.config.path_lab.grading).push()
            self.repo_updated = False

    @instance_cache.instance_cache
    def student_group(self, group_id):
        return group_project.GroupProject(self, group_id)

    @functools.cached_property
    def student_groups(self):
        return [self.student_group(group_id) for group_id in self.course.groups]

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
                    if self.logger:
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
                    project = self.course.configure_student_project(project)
                    project.delete_fork_relation()
                    self.student_group(group_id).project.get = project
                    del projects[group_id]
                    self.student_group(group_id).repo_add_remote()
            except:  # noqa: E722
                for project in projects.values():
                    project.delete()
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
        for group in self.course.groups:
            self.hotfix_group(branch_hotfix, group, self.course.config.branch.master)

    def repo_fetch_all(self):
        '''
        Fetch from the official repository and all student repositories.
        '''
        self.repo_fetch_official()
        for group in self.student_groups:
            group.repo_fetch()

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

    def hooks_create(self, netloc):
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
                hooks[group.id] = group.hook_create(netloc)
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

    def hooks_delete_all(self, netloc):
        '''
        Delete all webhooks in all group project in this lab set up with the given netloc on GitLab.
        See group_project.GroupProject.hook_delete_all.
        '''
        for group in self.student_groups:
            group.hook_delete_all(netloc)

    @contextlib.contextmanager
    def hooks_manager(self, netloc):
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
                        yield (group.id, stack.enter_context(group.hook_manager(netloc)))
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
        '''
        self.logger.info('Parsing response issues.')
        for group in self.student_groups:
            group.parse_response_issues()

    def parse_requests_and_responses(self, from_gitlab = True):
        '''Calls parse_request_tags and parse_response_issues.'''
        self.parse_request_tags(from_gitlab = from_gitlab)
        self.parse_response_issues()

    def process_requests(self):
        '''
        Parse response issues for group projects in this lab.
        This skips requests already marked as handled in the local grading repository.
        Before calling this method, the following setups steps need to have been executed:
        * self.setup_handlers()
        * requests and responses need to be up to date.
          Update responses before updating requests to avoid responses with no matching request.
        '''
        self.logger.info('Processing requests.')
        self.submission_solution.process_request()
        for group in self.student_groups:
            group.process_requests()

    @functools.cached_property
    def submission_handler(self):
        '''The submission handler specified by the lab configuration.'''
        return self.config.request_handlers[self.config.submission_handler_key]

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

    def update_live_submissions_table(self, deadline = None):
        self.logger.info('Updating live submissions table')
        table = live_submissions_table.LiveSubmissionsTable(self)
        with tempfile.TemporaryDirectory() as dir:
            path = Path(dir) / 'index.html'
            table.build(path, deadline = deadline, columns = self.submission_handler.grading_columns)
            self.logger.info('Posting live submissions table to Canvas')
            target = self.config.canvas_path_awaiting_grading
            folder = self.course.canvas_course.get_folder_by_path(target.parent)
            self.course.canvas_course.post_file(path, folder.id, target.name)

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
        return self.course.grading_spreadsheet.ensure_grading_sheet(
            self.id,
            # Restrict to non-empty groups.
            [group_id for group_id in self.course.groups if self.student_group(group_id).non_empty()],
            lambda group_id: self.student_group(group_id).project.get.web_url
        )

    def update_grading_sheet(self, deadline = None):
        # Ensure grading sheet exists and has sufficient query group columns.
        self.grading_sheet.ensure_num_queries(max(
            (general.ilen(group.submissions_relevant(deadline)) for group in self.student_groups),
            default = 0,
        ))

        request_buffer = self.course.grading_spreadsheet.create_request_buffer()
        for group_id in self.course.groups:
            group = self.student_group(group_id)

            # HACK (for now).
            # Only include non-empty groups.
            # Should output warning if an empty group has a submission.
            if not group.non_empty():
                continue

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
                    group_id,
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

    def update_grading_sheet_and_live_submissions_table(self, deadline = None):
        '''
        Does what its name says.

        Passes the deadline parameters to the methods update_grading_sheet and update_live_submissions_table.
        '''
        self.setup_request_handlers()
        self.parse_response_issues()
        self.repo_fetch_all()
        self.parse_request_tags(False)
        self.setup_request_handlers()
        self.process_requests()
        self.repo_push()
        self.update_live_submissions_table(deadline = deadline)
        self.update_grading_sheet(deadline = deadline)
        self.repo_push()  # Needed because update_grading_sheet might add stuff to repo.
