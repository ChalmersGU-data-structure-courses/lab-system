import dataclasses
import typing
from pathlib import Path

import util.general
import util.ordering


# ## Interfaces.
#
# Each interface defined here forms a preorder (the priority preorder).
# The partial order relation is inherited from the attribute _key.
# This attribute defines the priority of an instance.
# If a._key <= b._key, then a has priority over b.

_dataclass_incomparable = dataclasses.dataclass(eq=False)

_decorator = util.general.compose(
    _dataclass_incomparable,
    util.ordering.preorder_from_key,
)


@_decorator
class ProgramEvent:
    pass


@_decorator
class CourseEvent:
    pass


@_decorator
class LabEvent:
    pass


@_decorator
class GroupProjectEvent:
    pass


@_decorator
class GroupProjectResponseEvent:
    pass


# ## Instances of ProgramEvent.


@_dataclass_incomparable
class TerminateProgram(ProgramEvent):
    _key = (0,)


@_dataclass_incomparable
class ProgramEventInCourse(ProgramEvent):
    course_dir: Path
    course_event: CourseEvent

    @property
    def _key(self):
        return (1, util.ordering.DiscreteOrder(self.course_dir), self.course_event)


# ## Instances of CourseEvent.


@_dataclass_incomparable
class ReloadCourse(CourseEvent):
    _key = (0,)


@_dataclass_incomparable
class SyncFromCanvas(CourseEvent):
    _key = (1, util.ordering.DiscreteOrder(0))


@_dataclass_incomparable
class CourseEventInLab(CourseEvent):
    lab_id: typing.Any
    lab_event: LabEvent

    @property
    def _key(self):
        return (
            1,
            util.ordering.DiscreteOrder(1),
            util.ordering.DiscreteOrder(self.lab_id),
            self.lab_event,
        )


# ## Instances of LabEvent.


@_dataclass_incomparable
class RefreshLab(LabEvent):
    _key = (0,)


@_dataclass_incomparable
class LabEventInGroupProject(LabEvent):
    group_id: typing.Any
    group_project_event: GroupProjectEvent

    @property
    def _key(self):
        return (1, util.ordering.DiscreteOrder(self.group_id), self.group_project_event)


# ## Instances of GroupProjectEvent.


@_dataclass_incomparable
class GroupProjectWebhookEvent(GroupProjectEvent):
    pass


@_dataclass_incomparable
class GroupProjectTagEvent(GroupProjectWebhookEvent):
    _key = (0,)


@_dataclass_incomparable
class GroupProjectWebhookResponseEvent(GroupProjectWebhookEvent):
    """
    GroupProjectResponseEvent has priority over GroupProjectTagEvent.
    This is because we need to reload requests anyway
    after reloading responses before merging them.
    """

    group_project_response_event: GroupProjectResponseEvent

    @property
    def _key(self):
        return (1, self.group_project_response_event)


# ## Instances of GroupProjectResponseEvent


@_dataclass_incomparable
class GroupProjectIssueEvent(GroupProjectResponseEvent):
    _key = ()


@_dataclass_incomparable
class GroupProjectGradingMergeRequestEvent(GroupProjectResponseEvent):
    _key = ()
