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

from course_basics import CompilationRequirement, SubmissionHandlingException
import git_tools
import gitlab_tools
import google_tools.sheets
import grading_sheet
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
        self.path = self.course.config.path.labs / self.id_str

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
        return GroupProject(self, group_id)

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

    def update_submissions_and_gradings(self, reload = False):
        self.logger.info('Updating submissions and gradings.')
        for group in self.student_groups:
            group.update_submissions_and_gradings(reload = reload)

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
                    score = google_tools.sheets.extended_value_number(response['score'])

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
        self.update_submissions_and_gradings(reload = True)
        self.repo_fetch_all()
        self.update_grading_sheet(deadline = deadline)
        self.update_live_submissions_table(deadline = deadline)
        self.repo_push()

class GroupProject:
    def __init__(self, lab, id, logger = logging.getLogger('group-project')):
        self.course = lab.course
        self.lab = lab
        self.id = id
        self.logger = logger

        self.remote = self.course.config.group.full_id.print(id)

        #def f(x):
        #    return self.course.request_namespace(lambda request_type, spec: x)

        #self.request_tags = self.course.request_namespace(lambda x, y: dict())
        #self.response_issues = self.course.request_namespace(lambda x, y: dict())
        #self.requests_and_responses = self.course.request_namespace(lambda x, y: dict())

        # Map from submissions to booleans.
        # Values mean the following:
        # * not in map: submission has not yet been considered
        # * False: submission is invalid (for example, because compilation is required and it didn't compile)
        # * True: submission is valid (to be sent to graders)
        self.submission_valid = dict()

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

    # TODO.
    # We could cache this if we have a way to detect updates.
    # But e.g. group hooks monitoring for membership updates are only
    # available in the "Premium tier" version of GitLab, not the open source one.
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

    def append_mentions(self, text):
        '''
        Append a mentions paragraph to a given Markdown text.
        This will mention all the student members.
        Under standard notification settings, it will trigger notifications
        when the resulting text is posted in an issue or comment.
        '''
        return gitlab_tools.append_mentions(text, self.members())

    def repo_fetch(self):
        '''
        Make sure the local repository as up to date with respect to
        the contents of the student repository on GitLab Chalmers.
        '''
        self.logger.info(f'Fetching from student repository, remote {self.remote}.')
        self.lab.repo.remote(self.remote).fetch('--update-head-ok')

    # def repo_tag_names(self):
    #     '''
    #     Read the local tags fetched from the student project on GitLab.
    #     Returns a list of tag names.
    #     '''
    #     dir = Path(self.lab.repo.git_dir) / git_tools.refs / git_tools.remote_tags / self.remote
    #     return [file.name for file in dir.iterdir()]

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
        url = 'https://' + print_parse.netloc.print(netloc)
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

    def delete_all_hooks(self):
        '''
        Delete all webhook in the student project on GitLab.
        You should use this when previous program runs where killed or stopped
        in a non-standard fashion that prevented cleanup and have left lingering webhooks.
        '''
        for hook in self.project.lazy.hooks.list(all = True):
            self.hook_delete(hook)

    @contextlib.contextmanager
    def hook_manager(self, netloc):
        ''' A context manager for creating a webhook. '''
        hook = self.hook_create(netloc)
        try:
            yield hook
        finally:
            self.hook_delete(hook)

    @functools.cached_property
    def submissions_and_gradings(self):
        return self.course.parse_submissions_and_gradings(self.project.get)

    def update_submissions_and_gradings(self, reload = False):
        if reload:
            with contextlib.suppress(AttributeError):
                del self.submissions_and_gradings
        self.submissions_and_gradings

    def submissions_and_gradings_before(self, deadline = None):
        return dict(filter(
            lambda x: deadline == None or x[1][0].date < deadline,
            self.submissions_and_gradings.items()
        ))

    def graded_submissions(self, deadline = None):
        def f():
            for entry in self.submissions_and_gradings_before(deadline).items():
                if entry[1][1] != None:
                    yield entry[1]
        return list(f())

    def current_submission(self, deadline = None):
        x = list(self.submissions_and_gradings_before(deadline).items())
        if x and x[-1][1][1] == None:
            return x[-1][1][0]
        return None

    def relevant_submissions(self, deadline = None):
        def f():
            yield from self.graded_submissions(deadline)
            x = list(self.submissions_and_gradings_before(deadline).items())
            if x and x[-1][1][1] == None:
                yield x[-1][1]
        return list(f())

    def update_request_tags(self):
        '''
        Update the request tags attribute from Chalmers GitLab.
        Returns an object with request types as attributes and values indicating if there was an update.
        '''
        request_tags = self.course.parse_request_tags(self.project.get)
        updated = self.course.request_namespace(lambda request_type, _:
            general.ne_on(
                request_tags,
                self.request_tags,
                lambda x: tuple(tag.name for tag in x.__dict__[request_type])
            )
        )
        self.request_tags = request_tags

        if any(updated.__dict__.values()):
            self.repo_fetch()
        return updated

    def response_key(self, response):
        '''
        When to consider two response issues to be the same.
        Used in update_response_issues.
        '''
        if response == None:
            return None

        (issue, parsed_issue) = response
        return parsed_issue

    def update_response_issues(self):
        '''
        Update the stored response issues attribute from Chalmers GitLab.
        Returns an object with request types as attributes and values indicating if there was an update.
        '''
        response_issues = self.course.parse_response_issues(self.project.get)
        updated = self.course.request_namespace(lambda request_type, _:
            general.ne_on(
                response_issues,
                self.response_issues,
                lambda x: dict(
                    (response_type, self.response_key(response))
                    for (response_type, response) in x.__dict__[request_type].items()
                )
            )
        )
        self.response_issues = response_issues
        return updated

    def update_requests_and_responses(self):
        '''
        Update the requests_and_responses attribute from the request_tag and response_issues attributes.
        Returns an object with request types as attributes and values indicating if there was an update.
        Updates are defined as in update_request_tags and update_response_issues.
        '''
        def key(x):
            if not x:
                return None

            (request, response) = next(reversed(x.items()))
            return dict(
                (request, self.response_key(response))
                for (response_type, response) in response.__dict__.items()
                if response_type != 'tag'
            )

        requests_and_responses = self.course.merge_requests_and_responses(
            self.project.get,
            self.request_tags,
            self.response_issues
        )
        updated = self.course.request_namespace(lambda request_type, _:
            general.ne_on(
                requests_and_responses,
                self.requests_and_responses,
                lambda x: key(x.__dict__[request_type]))
        )
        self.requests_and_responses = requests_and_responses
        return updated

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

    def create_response_issue_in_grading_project(
        self,
        request_type,
        request,
        response_type,
        description,
        params = dict(),
        exist_ok = True
    ):
        '''
        Create a response issue in the grading project (only visible to graders).
        Also update the local grading issue  cache ('grading_issue') with this response.
        If a response issue of the given response type already exists, do nothing if exist_ok holds.
        Otherwise, raise an error.
        '''
        key = (request, response_type)
        self.logger.info(f'Grading project: creating {response_type} issue for {request_type} {request}.')

        if key in self.grading_issues:
            raise ValueError(f'Grading project: {response_type} issue for {request_type} {request} already exists.')

        issue = self.post_issue(self.lab.grading_project, request_type, request, response_type, description, params)
        self.grading_issues[key] = (issue, params)
        return issue

    def process_robograding(self, request):
        '''
        Process a robograding request.
        The request is ignored if it has already been answered.
        There are two possible types of answers:
        * reporting a compilation problem,
        * the robograding report.
        '''
        # Get the response on record so far.
        response = self.requests_and_responses.robograding[request]

        # Have we already handled this request?
        if response.compilation or response.robograding:
            return

        self.logger.info(f'Robograding {request}')
        issue_params = types.SimpleNamespace(
            request_type = 'robograding',
            request = request,
        ).__dict__

        # Check the commit out.
        with (
            git_tools.with_checkout(self.lab.repo, git_tools.remote_tag(self.remote, request)) as src,
            tempfile.TemporaryDirectory() as bin
        ):
            # If a compiler is configured, compile first.
            if self.lab.config.compiler:
                self.logger.info('* compiling')
                try:
                    self.lab.config.compiler(src, bin)
                except SubmissionHandlingException as e:
                    self.create_response_issue(**issue_params,
                        response_type = 'compilation',
                        description = e.markdown() + general.join_lines([
                            '',
                            'If you believe this is a mistake on our end, please contact the responsible teacher.'
                        ]),
                    )
                    return

            # Call the robograder.
            try:
                self.logger.info('* robograding')
                r = self.lab.config.robograder.run(src, bin)
                description = r.report
            except SubmissionHandlingException as e:
                description = e.markdown()
            self.create_response_issue(**issue_params,
                response_type = 'robograding',
                description = description,
            )

    def process_robogradings(self):
        ''' Process all robograding requests. '''
        for request in self.requests_and_responses.robograding.keys():
            self.process_robograding(request)

    def process_submission(self, request):
        '''
        Process a submission request.
        '''
        # Have we already handled this request?
        if request in self.submissions_valid:
            return

        # Get the response on record so far.
        response = self.requests_and_responses.robograding[request]

        # If compilation is required and there is already a compilation response,
        # we record the submission as rejected.
        if all([
            self.lab.config.compilation_requirement == CompilationRequirement.require,
            response.compilation
        ]):
            self.submission_valid[request] = False
            return

        # Otherwise,

        self.logger.info(f'Handling submission {request}')
        issue_params = types.SimpleNamespace(
            request_type = 'submission',
            request = request,
        ).__dict__

        has_grading_robograding = self.grading_issues.get((request, 'robograding'))
        has_grading_compilation = self.grading_issues.get((request, 'compilation'))
        has_grading_issue = has_grading_robograding or has_grading_compilation

        #require_compilation = not has_grading_issue or False # Unfinished

        # Check the commit out.
        with (
            git_tools.with_checkout(self.lab.repo, git_tools.remote_tag(self.remote, request)) as src,
            tempfile.TemporaryDirectory() as bin,
        ):

            has_compilation: response.compilation

            # If a compiler is configured, compile first, but only if actually needed.
            compilation_okay = True
            if self.lab.config.compiler and not (response.compilation and has_grading_issue):
                self.logger.info('* compiling')
                try:
                    self.lab.config.compiler(src, bin)
                except SubmissionHandlingException as e:
                    compilation_okay = False

                    # Only report problem if configured and not yet reported.
                    message = self.lab.config.compilation_message.get(self.lab.config.compilation_requirement)
                    if message != None:
                        self.create_response_issue(**issue_params,
                            response_type = 'compilation',
                            description = str().join([
                                message,
                                general.join_lines([]),
                                e.markdown(),
                            ])
                        )

                    # Stop if compilation is required.
                    if self.lab.config.compilation_requirement == CompilationRequirement.require:
                        self.submissions_valid[request] = False
                        return

                    # Report compilation problem in grading project.
                    if not has_grading_compilation:
                        self.create_response_issue_in_grading_project(**issue_params,
                            response_type = 'compilation',
                            description = e.markdown(),
                        )

            # Prepare robograding report for graders if configured.
            if self.lab.config.robograder and compilation_okay:
                try:
                    r = self.lab.config.robograder.run(src, bin)
                    description = r.report
                except SubmissionHandlingException as e:
                    description = e.markdown()
                self.create_response_issue_in_grading_project(**issue_params,
                    response_type = 'robograding',
                    description = description,
                )

    def process_submissions(self):
        ''' Processes the latest submission, if any. '''
        x = self.requests_and_responses.submission
        if not x:
            return

        self.process_submission(next(reversed(x.keys())))


        # how do we know a submission has been processed?
        # ultimately, we can never know: we might have crashed.
        # we could run with a flag 'force' to indicate that we don't know.
        # if 'force' is false, then existing an robograding in the grading repository can indicate that we don't need to process.
        # but what if we don't have a robograder?
        # we would also have to compile again.
        # we could check in the google doc.
        # if we have an entry there, then we processed it already.

        # if self.lab.config.compiler:

        # with_remote = lambda s: '{}/{}'.format(remote, s)
        # logger.log(logging.INFO, 'Robograding {}...'.format(with_remote(tag)))

        # with tempfile.TemporaryDirectory() as dir:
        #     dir = Path(dir)
        #     self.submission_checkout(dir, abs_remote_tag(with_remote(tag)))

        #     response = None

        #     # TODO: Escape embedded error for Markdown.
        #     def record_error(description, error, is_code):
        #         nonlocal response
        #         code = '```' if is_code else ''
        #         response = '{}\n{}\n{}\n{}\n'.format(description, code, error.strip(), code)

        #     try:
        #         self.submission_check_symlinks(dir)
        #         self.submission_compile(dir)
        #         response = self.submission_robograde(dir)
        #     except check_symlinks.SymlinkException as e:
        #         record_error('There is a problem with symbolic links in your submission.', e.text, True)
        #     except java.CompileError as e:
        #         record_error('I could not compile your Java files:', e.compile_errors, True)
        #     except robograde.RobogradeFileConflict as e:
        #         response = 'I could not test your submission because the compiled file\n```\n{}\n```\nconflicts with files I use for testing.'.format(e.file)
        #     except robograde.RobogradeException as e:
        #         record_error('Oops, you broke me!\n\nI encountered a problem while testing your submission.\nThis could be a problem with myself (a robo-bug) or with your code (unexpected changes to class or methods signatures). If it is the latter, you might be able to elucidate the cause from the below error message and fix it. If not, tell my designers!', e.errors, True)

        #     if in_student_repo:
        #         response = '{}\n{}\n'.format(response, Course.mention(self.course.students(n)))

        #     p = self.lab_group_project(n) if in_student_repo else self.grading_project()
        #     logger.log(logging.INFO, response)
        #     p.issues.create({
        #         'title': self.config.testing_issue_print(tag if in_student_repo else with_remote(tag)),
        #         'description': response,
        #     })

        # logger.log(logging.INFO, 'Robograded {}.'.format(with_remote(tag)))
