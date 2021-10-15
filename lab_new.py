import functools
import general
import git
from pathlib import Path
import shutil
import tempfile

from course_new import *

class Lab:
    def __init__(self, course, id, config, dir_grading):
        '''
        Initialize lab manager.
        Arguments:
        * course: course manager.
        * id: lab id, typically used as key in a lab configuration dictionary (see 'gitlab_config.py.template')
        * config: lab configuration, typically the value in a lab configuration dictionary.
        * dir_grading: Local directory used as local copy of the grading repository.
                       Only its parent directory has to exist.
        '''

        self.course = course
        self.id = id
        self.config = config
        self.dir_grading = dir_grading

        # Naming config
        self.id_str = self.course.config.lab.id.print(self.id)
        self.name = self.course.config.lab.name.print(self.id)
        self.name_semantic = (self.config.path_source / 'name').read_text().strip()
        self.name_full = '{} — {}'.format(self.name, self.name_semantic)

        # Gitlab config
        self.gl = self.course.gl
        self.path = self.course.config.path.labs / self.id_str
        self.path_official = self.path / self.course.config.path_lab.official
        self.path_grading = self.path / self.course.config.path_lab.grading

    def create_group(self):
        self.gl.groups.create({
            'parent_id': self.course.labs_group(lazy = False).id,
            'path': self.path.name,
            'name': self.name_full,
        })

    @functools.cached_property
    def group(self):
        ''' The group for this lab on Chalmers GitLab. '''
        return self.course.group(self.path, lazy = False)

    @functools.cached_property
    def official_project(self):
        return self.course.project(self.path_official, lazy = False)

    def official_project_delete(self):
        self.gl.projects.delete(str(self.path_official))
        general.clear_cached_property(self, 'official_project')

    def official_project_create(self):
        '''
        Create the official lab project on Chalmers GitLab.
        The contents are taken from the specified local lab directory
        (together with an optionally specified .gitignore file).
        Make sure the problem and solution subdirectories are clean before you call this method.

        This sets up problem and solution branches.
        '''

        self.official_project = self.gl.projects.create({
            'namespace_id': self.group.id,
            'path': self.path_official.name,
            'name': '{} — official repository'.format(self.name),
        })

        with tempfile.TemporaryDirectory() as dir:
            repo = git.Repo.init(dir)

            def push_branch(name, message):
                shutil.copytree(self.config.path_source / name, dir, dirs_exist_ok = True)
                repo.git.add('--all', '--force')
                repo.git.commit(message = message)
                repo.git.push(self.official_project.ssh_url_to_repo, f'+HEAD:refs/heads/{name}')

            if self.config.path_gitignore:
                shutil.copyfile(self.config.path_gitignore, Path(dir) / '.gitignore')
            push_branch(self.course.config.branch.problem, 'Initial commit.')
            push_branch(self.course.config.branch.solution, 'Official solution.')

    @functools.cached_property
    def grading_project(self):
        return self.course.project(self.path_grading, lazy = False)

    def grading_project_delete(self):
        self.gl.projects.delete(str(self.path_grading))
        general.clear_cached_property(self, 'grading_project')

    def grading_project_create(self):
        '''
        Create the grading project on Chalmers GitLab.
        Its contents are initially empty.
        '''
        self.grading_project = self.gl.projects.create({
            'namespace_id': self.group.id,
            'path': self.path_grading.name,
            'name': '{} — grading repository'.format(self.name),
        })

    def init_grading_repo(self, bare = True):
        if self.dir.exists():
            self.repo = git.Repo(self.dir_grading)
        else:
            self.repo = git.Repo.init(self.dir_grading, bare = bare)
            brancbes = [self.course.config.branch.problem, self.course.config.branch.solution]
            git.add_tracking_remote(
                self.repo,
                self.path_official.name,
                self.official_project.ssh_url_to_repo,
                fetch_branches = branches,
                fetch_tags = [wildcard],
            )
            git.add_tracking_remote(
                self.repo,
                self.path_grading.name,
                self.official_project.ssh_url_to_repo,
                push_branches = branches,
                push_tags = [wildcard],
            )

    @functools.cached_property
    def repo(self):
        '''
        Local grading repository.
        This is used as staging for (pushes to) the grading project on GitLab Chalmers.
        It fetches from the official lab repository and student group repositories.
        '''
        return init_grading_repo(self)

import gitlab_config as config

course = Course(config)
lab = Lab(course, 2, config.labs[2])

