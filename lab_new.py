import contextlib
import functools
import general
import git
import gitlab
import logging
from pathlib import Path
import shutil
import tempfile
import types

import course_new as course
import git_tools
import gitlab_tools
from instance_cache import instance_cache

class SubmissionHandlingException:
    # Return a markdown-formatted error message for use within a Chalmers GitLab issue.
    def markdown(self):
        None

class Lab:
    def __init__(self, course, id, dir, config = None, logger = logging.getLogger('lab')):
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
        self.dir = dir

        self.config = config if config != None else self.course.config.labs[id]

        # Naming config
        self.id_str = self.course.config.lab.id.print(self.id)
        self.name = self.course.config.lab.name.print(self.id)
        self.name_semantic = (self.config.path_source / 'name').read_text().strip()
        self.name_full = '{} — {}'.format(self.name, self.name_semantic)

        # Gitlab config
        self.gl = self.course.gl
        self.path = self.course.config.path.labs / self.id_str

        self.cached_params = types.SimpleNamespace(
            gl = self.gl,
            logger = self.logger,
        ).__dict__

    @functools.cached_property
    def group(self):
        '''
        The group for this lab on Chalmers GitLab.
        '''
        r = gitlab_tools.CachedGroup(**self.cached_params,
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
        r = gitlab_tools.CachedProject(**self.cached_params,
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
        r = gitlab_tools.CachedProject(**self.cached_params,
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
        r = self.staging_project.create()
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
        r = gitlab_tools.CachedProject(**self.cached_params,
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
        This is used as staging for (pushes to) the grading project on GitLab Chalmers.
        It fetches from the official lab repository and student group repositories.
        '''
        return git.Repo(self.dir)

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
            self.repo_add_group_remote(group_id, **kwargs)

    def repo_init(self, bare = True):
        '''
        Initialize the local grading repository.
        If the directory exists, we assume that all remotes are set up.
        Otherwise, we create the directory and populate it with remotes on GitLab Chalmers as follows.
        Fetching remotes are given by the official repository and student group repositories.
        Pushing remotes are just the grading repository.
        '''
        repo = git.Repo.init(self.dir, bare = bare)
        try:
            branches = [self.course.config.branch.problem, self.course.config.branch.solution]
            self.repo_add_remote(
                self.course.config.path_lab.official,
                self.official_project.get,
                fetch_branches = [(git_tools.Namespacing.local, b) for b in branches],
                fetch_tags = [(git_tools.Namespacing.local, git_tools.wildcard)],
            )
            self.repo_add_remote(
                self.course.config.path_lab.grading,
                self.grading_project.get,
                push_branches = branches,
                push_tags = [git_tools.wildcard],
            )
            self.repo.remote(self.course.config.path_lab.official).fetch()
            self.repo_add_groups_remotes(ignore_missing = True)
        except:
            shutil.rmtree(self.dir)
            raise
        self.repo = repo

    def repo_fetch_official(self):
        '''
        Fetch problem and solution branches from the offical
        repository on GitLab Chalmers to the local grading repository.
        '''
        self.repo.remotes[self.course.config.path_lab.official].fetch()

    def repo_push_grading(self):
        '''
        Push the local grading repository to the grading repository on GitLab Chalmers.
        
        '''
        self.repo.remotes[self.course.config.path_lab.grading].push()

    @instance_cache
    def student_group(self, group_id):
        return GroupProject(self, group_id)

    def create_group_projects(self):
        for group_id in self.course.groups:
            self.student_group(group_id).project.create()

    def delete_group_projects(self):
        for group_id in self.course.groups:
            self.group_project(group_id).project.delete()

    def create_group_projects_fast(self, only_missing = False):
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
                        if only_missing and e.response_code == 409:
                            if self.logger:
                                self.logger.info('Skipping because project already exists')
                        else:
                            raise

                for (group_id, project) in tuple(projects.items()):
                    project = self.course.configure_student_project(project)
                    project.delete_fork_relation()
                    self.groups(group_id).project.get = project
                    del projects[group_id]
                    self.groups(group_id).repo_add_remote()
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

    def setup_robograder(self):
        '''
        This method sets up the robograder.
        Call before any robograding happens.
        Once needs to be called (for the local installation, not each program run).
        '''
        with tempfile.TemporaryDirectory() as src:
            src = Path(src)
            git_tools.checkout(self.repo, src, git_tools.local_branch(self.course.config.branch.problem))
            with tempfile.TemporaryDirectory() as bin:
                bin = Path(bin)
                if self.config.compiler:
                    self.config.compiler(src, bin)
                if self.config.robograder:
                    self.config.robograder.setup(src, bin)

    #def compile_submission(self, bin):
    #   

class GroupProject:
    def __init__(self, lab, group_id, logger = logging.getLogger('group-project')):
        self.gl = lab.gl
        self.course = lab.course
        self.lab = lab
        self.group_id = group_id
        self.logger = logger

        self.remote = self.course.config.group.full_id.print(group_id)

        def f(x):
            return self.course.request_namespace(lambda request_type, spec: x)

        self.request_tags = self.course.request_dict(lambda x, y: dict())
        self.response_issues = self.course.request_dict(lambda x, y: dict())
        self.requests_and_responses = self.course.request_namespace(lambda x, y: dict())

    @functools.cached_property
    def project(self):
        '''
        A lab project for a student group.
        On creation, the repository is initialized with the problem branch of the local grading repository.
        That one needs to be initialized and have the problem branch.
        '''
        r = gitlab_tools.CachedProject(
            gl = self.gl,
            path = self.course.group(self.group_id).path / self.course.config.lab.full_id.print(self.lab.id),
            name = self.lab.name_full,
            logger = self.logger,
        )

        def create():
            project = gitlab_tools.CachedProject.create(r, self.course.group(self.group_id).get)
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
        try:
            lab.repo_add_remote(
                self.remote,
                self.project.get,
                fetch_branches = [(git_tools.Namespacing.remote, git_tools.wildcard)],
                fetch_tags = [(git_tools.Namespacing.remote, git_tools.wildcard)],
                prune = True,
            )
        except gitlab.GitlabGetError as e:
            if ignore_missing and e.response_code == 404 and e.error_message == '404 Project Not Found':
                if self.logger:
                    self.logger.debug(f'Not adding remote {remote} because project is missing')
            else:
                raise e

    def repo_fetch(self):
        self.lab.repo.remotes[self.course.config.group.full_id.print(group_id)].fetch()

    def hotfix_group(self, branch_hotfix, branch_group):
        '''
        Attempt to hotfix the branch 'branch_group' of the group project.
        The hotfix branch 'branch_hotfix' in the local grading repository is a descendant of the problem branch.
        The metadata of the applied commit is taken from the commit pointed to by 'branch_hotfix'.
        Will log a warning if the merge cannot be performed.
        '''
        self.logger.info(f'Hotfixing {branch_group} in f{self.project.path}')

        self.lab.repo.remote(self.remote).fetch()

        problem = git_tools.resolve_ref(self.lab.repo, git_tools.local_branch(self.course.config.branch.problem))
        hotfix = git_tools.resolve_ref(self.lab.repo, git_tools.local_branch(branch_hotfix))
        if problem == hotfix:
            self.logger.warn('Hotfixing: hotfix identical to problem.')
            return

        master = git_tools.remote_branch(remote, branch_group)
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
            parent_commits = [git_tools.resolve_ref(self.lab.repo, master)],
            head = False,
            author = hotfix.author,
            committer = hotfix.committer,
            author_date = hotfix.authored_datetime,
            commit_date = hotfix.committed_datetime,
        )

        return self.repo.remote(remote).push(git_tools.refspec(
            commit.hexsha,
            self.course.config.branch.master,
            force = False,
        ))

    def update_request_tags(self):
        '''
        Update the request tags attribute from GitLab Chalmers.
        Returns an object with request types as attributes and values indicating if there was an update.
        '''
        request_tags = self.course.parse_request_tags(self.project.get)
        updated = self.course.request_namespace(lambda request_type, _:
            general.ne_on(
                request_tags,
                self.request_tags,
                lambda x: tuple(tag.name for tag in x[request_type])
            )
        )
        self.request_tags = request_tags
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
        Update the stored response issues attribute from GitLab Chalmers.
        Returns an object with request types as attributes and values indicating if there was an update.
        '''
        response_issues = self.course.parse_response_issues(self.project.get)
        updated = self.course.request_namespace(lambda request_type, _:
            general.ne_on(
                response_issues,
                self.response_issues,
                lambda x: dict(
                    (response_type, self.response_key(response))
                    for (response_type, response) in x[request_type].items()
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

            (request, response) = list(x.items())[-1]
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

import gitlab_config as config

if __name__ == "__main__":
    logging.basicConfig()
    logging.root.setLevel(logging.INFO)

    c = course.Course(config)
    lab = Lab(c, 2, Path('/home/noname/test'))
    g = lab.student_group(0)
    print(g.update_request_tags())
    print(g.update_response_issues())
    print(g.update_requests_and_responses())
