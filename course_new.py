import functools
import general
import gitlab
from pathlib import Path

import canvas

#===============================================================================
# Other tools

def read_private_token(x):
    if isinstance(x, Path):
        x = x.read_text()
    return x

#===============================================================================
# Course labs management

class Course:
    def __init__(self, config, canvas_use_cache = True):
        self.config = config

        self.canvas = canvas.Canvas(config.canvas.url, auth_token = config.canvas_auth_token)
        self.canvas_course = canvas.Course(self.canvas, config.canvas.course_id, use_cache = canvas_use_cache)
        self.canvas_group_set = canvas.GroupSet(self.canvas_course, config.canvas.group_set, use_cache = canvas_use_cache)

        self.gl = gitlab.Gitlab(self.config.base_url, private_token = read_private_token(self.config.private_token))
        self.gl.auth()

    def group(self, id, lazy = True):
        return self.gl.groups.get(id if isinstance(id, int) else str(id), lazy = lazy)

    def project(self, id, lazy = True):
        return self.gl.projects.get(id if isinstance(id, int) else str(id), lazy = lazy)

    def labs_group(self, **kwargs):
        return self.group(self.config.path.labs, **kwargs)

    def groups_group(self, **kwargs):
        return self.group(self.config.path.groups, **kwargs)

    def graders_group(self, **kwargs):
        return self.group(self.config.path.graders, **kwargs)

import gitlab_config as config

course = Course(config)
