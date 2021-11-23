import contextlib
import functools
import general
import git
import gitlab
import logging
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import types

import course_basics
import git_tools
import gitlab_tools
import google_tools.sheets
import grading_sheet
import group_project
from instance_cache import instance_cache
import live_submissions_table
import print_parse

class Lab:
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
        self.dir = Path(dir) if dir != None else None

        self.config = config if config != None else self.course.config.labs[id]

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
        r = gitlab_tools.CachedGroup(**self.entity_cached_params,
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
    #                     repo.git.push(self.outer.official_project.ssh_url_to_repo, git_tools.refspec(git_tools.head, git_tools.local_branch(name), force = True))
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
        r = gitlab_tools.CachedProject(**self.entity_cached_params,
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
            except:
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
        r = gitlab_tools.CachedProject(**self.entity_cached_params,
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
            except:
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
        r = gitlab_tools.CachedProject(**self.entity_cached_params,
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

            # Configure offical grading repository and student group
            self.repo_add_remote(
                self.course.config.path_lab.grading,
                self.grading_project.get,
                push_branches = branches,
                push_tags = [git_tools.wildcard],
            )
            self.repo_add_groups_remotes(ignore_missing = True)
        except:
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

    def repo_push(self):
        '''
        Push the local grading repository to the grading repository on Chalmers GitLab.
        Only push if changes have been recorded.
        '''
        if self.repo_updated:
            self.logger.info('Pushing to grading repository.')
            self.repo.remote(self.course.config.path_lab.grading).push()
            self.repo_updated = False

    @instance_cache
    def student_group(self, group_id):
        return group_project.GroupProject(self, group_id)

    @functools.cached_property
    def student_groups(self):
        return [self.student_group(group_id) for group_id in self.course.groups]

    def repo_fetch_all(self):
        '''
        Fetch from the official repository and all student repositories.
        '''
        self.repo_fetch_official()
        for group in self.student_groups:
            group.repo_fetch()

    def create_group_projects(self):
        for group_id in self.course.groups:
            self.student_group(group_id).project.create()

    def delete_group_projects(self):
        for group_id in self.course.groups:
            self.student_group(group_id).project.delete()

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
            except:
                for project in projects.values():
                    project.delete()
                raise

    def hotfix_groups(self, branch_hotfix):
        '''
        Attempt to apply a hotfix to all student projects.
        This calls 'hotfix_group' with the master/main branch.
        If any groups have created separate branches and you wish to hotfix those, use the 'hotfix_group' method.
        '''
        for group in self.course.groups:
            self.hotfix_group(branch_hotfix, group, self.course.config.branch.master)

    @functools.cached_property
    def grading_template_issue(self):
        issues_grading_template = dict()
        self.course.parse_all_response_issues(self.official_project.get, [
            self.course.grading_template_issue_parser(issues_grading_template)
        ])
        return issues_grading_template.get(())

    def get_requests_and_responses(self):
        self.logger.info('Getting request tags and response issues.')
        for group in self.student_groups:
            group.get_requests_and_responses()

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
    def compiler(self):
        if self.config.compiler != None:
            self.config.compiler.setup(self)
        return self.config.compiler

    @contextlib.contextmanager
    def checkout_and_compile_problem(self):
        with self.checkout_with_empty_bin_manager(self.head_problem) as (src, bin):
            if self.compiler != None:
                self.compiler.compile(src, bin)
                yield (src, bin)

    def make_tag_after(self, tag, commit_prev, prev_name):
        '''
        Given a tag tag and a commit commit_prev in the grading repository,
        make a tag tag_after whose commit is a descendant of both tag and ref_prev,
        but has tree (content) identical to that of tag.
        The name of tag must be of the form tag_core / 'tag'.
        The name of tag_after will be 'merge' / tag_core / 'after' / prev_name.
        If tag is a descendant of commit_prev, then tag_after is a synonym for tag.
        Otherwise, it is constructed as a one-sided merge.
        Returns the tag tag_after (an instance of git.Tag).

        First tries to retrieve an existing tag tag_after.
        If none exists, we create it and mark the repository as updated.

        Arguments:
        * tag:
            An instance of git.Tag, PurePosixPath, or str.
            All paths are interpreted relative to refs / tags.
        * commit_prev:
            An instance of git.Commit, git.Reference, PurePosixPath, or str.
            All paths are interpreted absolutely with respect to the repository.
        * prev_name:
            An instance of PurePosixPath or str.
        '''
        # Resolve inputs.
        tag = git_tools.normalize_tag(self.repo, tag)
        commit_prev = git_tools.resolve(self.repo, commit_prev)

        tag_name = PurePosixPath(tag.name)
        if not tag_name.name == 'tag':
            raise ValueError(f'Tag name does not end with component "tag": {str(tag_name)}')
        tag_after_name = str('merge' / tag_name.parent / 'after' / prev_name)

        try:
            tag_after = self.repo.tag(tag_after_name)
            tag_after.commit  # Ensure that the reference exists.
        except ValueError:
            tag_after = git_tools.tag_onesided_merge(
                self.repo,
                tag_after_name,
                tag.commit,
                commit_prev,
            )
            self.repo_updated = True
        return tag_after

    def update_live_submissions_table(self, deadline = None):
        self.logger.info('Updating live submissions table')
        table = live_submissions_table.LiveSubmissionsTable(self)
        with tempfile.TemporaryDirectory() as dir:
            path = Path(dir) / 'index.html'
            table.build(path, deadline = deadline)
            self.repo_push()
            self.logger.info('Posting live submissions table to Canvas')
            target = self.config.canvas_path_awaiting_grading
            folder = self.course.canvas_course.get_folder_by_path(target.parent)
            self.course.canvas_course.post_file(path, folder.id, target.name)

    # def submission_handlers_of_type(self, klass = object):
    #     def f(x):
    #         (handler_id, submission_handler) = x
    #         return isinstance(submission_handler, klass)
    #     return dict(filter(f, self.config.submission_handlers.items()))

    # def testers(self):
    #     return self.submission_handlers_of_type(course_basics.Tester)

    # def submission_grading_robograders(self):
    #     return self.submission_handlers_of_type(course_basics.SubmissionGradingRobograders)

    # def student_callable_robograders(self):
    #     return self.submission_handlers_of_type(course_basics.StudentCallableRobograder)

    # def setup_submission_handlers(self):
    #     '''
    #     Set up the submission handlers.
    #     Call before any submission handling happens.
    #     It is up to each submission handler how much of their setup
    #     they want to handle via the setup callback method.
    #     Some handlers may prefer initialization via their constructor
    #     or even separate compilation setup outside the scope of this script.
    #     '''
    #     self.grading_issue_parsers = []
    #     self.issue_parsers = []
    #     self.tag_parsers = []

    #     with self.checkout_with_empty_bin_manager(self.commit_problem) as (src, bin):
    #         if self.config.compiler:
    #             compiler.setup(self)
    #             compiler.compile(src, bin)
    #         for submission_handler in self.config.submission_handlers:
    #             submission_handler.setup(self, src, bin)

    # A grading issue is parsed to:
    # * group_id
    # * request tag
    # * submission handler key
    # * some handler-specific data

    # A response issue is parsed to a request tag and
    # * a grading response
    # or
    # * submission handler key
    # * some handler-specific data

    # Every process is still indexed by the request tag.
    # Use group_id and request tag as keys.
    # Use submission handler keys + manual grading as sub-keys
    # Grading issues are never inputs, only outputs.
    # So we could avoid scanning them.
    # But that's inefficient.

    # mapping sending request tag to:
    # * tag in repo
    # * handler key: ...

    # mapping sending submission tag to:
    # * tag in repo
    # * grading response
    # * handler key: ...

    # Ignore submission handlers for now.

    def parse_issue(self, issue):
        request_types = self.config.request.__dict__
        for (request_type, spec) in request_types.items():
            for (response_type, pp) in spec.issue.__dict__.items():
                try:
                    return (request_type, response_type, pp.parse(issue.title))
                except:
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
            self.course.groups,
            lambda group_id: self.student_group(group_id).project.get.web_url
        )

    def update_grading_sheet(self, deadline = None):
        # Ensure grading sheet exists and has sufficient query group columns.
        self.grading_sheet.ensure_num_queries(max(
            (len(group.relevant_submissions(deadline)) for group in self.student_groups),
            default = 0,
        ))

        request_buffer = self.course.grading_spreadsheet.create_request_buffer()
        for group_id in self.course.groups:
            group = self.student_group(group_id)
            for (query, (tag, grading)) in enumerate(group.relevant_submissions(deadline)):
                if grading == None:
                    grader = None
                    score = None
                else:
                    (issue, response) = grading
                    informal_name = self.course.issue_author_informal(issue)
                    grader = grading_sheet.link_with_display(informal_name, issue.web_url)
                    score_as_cell = self.course.config.score.as_cell.print(response['score'])
                    score = google_tools.sheets.extended_value_number_or_string(score_as_cell)

                self.grading_sheet.write_query(
                    request_buffer,
                    group_id,
                    query,
                    grading_sheet.Query(
                        submission = grading_sheet.link_with_display(
                            tag.name,
                            group.project.get.web_url + '/-/tree/' + tag.name,
                        ),
                        grader = grader,
                        score = score,
                    ),
                )
        request_buffer.flush()

    def update_grading_sheet_and_live_submissions_table(self, deadline = None):
        '''
        Does what its name says.

        Passes the deadline parameters to the methods update_grading_sheet and update_live_submissions_table.
        '''
        self.get_requests_and_responses()
        self.repo_fetch_all()
        self.handle_requests()
        self.update_grading_sheet(deadline = deadline)
        self.update_live_submissions_table(deadline = deadline)
        self.repo_push()
