import contextlib
import functools
import logging

import canvas.client_rest as canvas
import util.general


class GroupSet:
    def __init__(self, course, config, logger=logging.getLogger(__name__)):
        self.logger = logger
        self.course = course
        self.config = config

    @property
    def gl(self):
        return self.course.gl

    @property
    def canvas(self):
        return self.course.canvas

    @property
    def canvas_course(self):
        return self.course.canvas_course

    def canvas_group_set_get(self, use_cache):
        return canvas.GroupSet(
            self.canvas_course, self.config.group_set_name, use_cache=use_cache
        )

    @functools.cached_property
    def canvas_group_set(self):
        return self.canvas_group_set_get(True)

    def canvas_group_set_refresh(self):
        self.canvas_group_set = self.canvas_group_set_get(False)

    def create_groups_on_canvas(self, group_ids):
        """
        Create (additional) additional groups with the given ids (e.g. range(50)) on Canvas.
        This uses the configured Canvas group set where students sign up for lab groups.
        Refreshes the Canvas cache and local cache of the group set (this part of the call may not be interrupted).
        """
        group_names = util.general.sdict(
            (group_id, self.config.name.print(group_id)) for group_id in group_ids
        )
        for group_name in group_names.values():
            if group_name in self.canvas_group_set.name_to_id:
                raise ValueError(
                    f"Group {group_name} already exists in "
                    f"Canvas group set {self.canvas_group_set.group_set.name}"
                )

        for group_name in group_names.values():
            self.canvas_group_set.create_group(group_name)
        self.canvas_group_set_refresh()
        with contextlib.suppress(AttributeError):
            del self.groups_on_canvas

    @functools.cached_property
    def groups_on_canvas(self):
        return dict(
            (
                self.config.name.parse(canvas_group.name),
                tuple(
                    self.canvas_course.user_details[canvas_user_id]
                    for canvas_user_id in self.canvas_group_set.group_users[
                        canvas_group.id
                    ]
                ),
            )
            for canvas_group in self.canvas_group_set.details.values()
        )
