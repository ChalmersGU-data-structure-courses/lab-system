from collections.abc import Generator, Iterable
import contextlib
import functools
import logging
from typing import TYPE_CHECKING

import canvas.client_rest as canvas
import lab_interfaces
import util.general

if TYPE_CHECKING:
    import course as module_course


class GroupSet[GroupId]:
    def __init__(
        self,
        course: "module_course.Course",
        config: lab_interfaces.GroupSetConfig[GroupId],
        logger: logging.Logger = logging.getLogger(__name__),
    ):
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
            self.canvas_course,
            self.config.canvas_group_set_name,
            use_cache=use_cache,
        )

    @functools.cached_property
    def canvas_group_set(self):
        return self.canvas_group_set_get(True)

    def canvas_group_set_refresh(self):
        self.canvas_group_set = self.canvas_group_set_get(False)

    def create_groups_on_canvas(self, group_ids: Iterable[GroupId]):
        """
        Create (additional) additional groups with the given ids (e.g. range(50)) on Canvas.
        This uses the configured Canvas group set where students sign up for lab groups.
        Refreshes the Canvas cache and local cache of the group set (this part of the call may not be interrupted).
        """
        group_names = util.general.sdict(
            (group_id, self.config.effective_canvas_name.print(group_id))
            for group_id in group_ids
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

    def canvas_group_ids(self) -> Generator[GroupId]:
        for canvas_group in self.canvas_group_set.details.values():
            yield self.config.effective_canvas_name.parse(canvas_group.name)

    def canvas_group_members(self, id: GroupId) -> Iterable[int]:
        canvas_group_name = self.config.effective_canvas_name.print(id)
        canvas_group_id = self.canvas_group_set.name_to_id[canvas_group_name]
        yield from self.canvas_group_set.group_users[canvas_group_id]
