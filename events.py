import dataclasses
from pathlib import Path
from typing import Any, ClassVar

import util.general
import util.ordering

## Interfaces.
#
# Each interface defined here forms a preorder (the priority preorder).
# The partial order relation is inherited from the attribute _key.
# This attribute defines the priority of an instance.
# If a._key <= b._key, then a has priority over b.

_dataclass_no_eq = dataclasses.dataclass(eq=False)


def _decorator(x):
    return _dataclass_no_eq(
        # pylint: disable-next=protected-access
        util.ordering.preorder_from_key(x, key=lambda x: x._key)
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
class GradingMergeRequestEvent:
    pass


## Instances of ProgramEvent.


@_dataclass_no_eq
class TerminateProgram(ProgramEvent):
    _key: ClassVar = (0,)


@_dataclass_no_eq
class ProgramEventInCourse(ProgramEvent):
    course_dir: Path
    course_event: CourseEvent

    @property
    def _key(self):
        return (1, util.ordering.DiscreteOrder(self.course_dir), self.course_event)


## Instances of CourseEvent.


@_dataclass_no_eq
class ReloadCourse(CourseEvent):
    _key: ClassVar = (0,)


@_dataclass_no_eq
class SyncFromCanvas(CourseEvent):
    _key: ClassVar = (1, util.ordering.DiscreteOrder(0))


@_dataclass_no_eq
class CourseEventInLab(CourseEvent):
    lab_id: Any
    lab_event: LabEvent

    @property
    def _key(self):
        return (
            1,
            util.ordering.DiscreteOrder(1),
            util.ordering.DiscreteOrder(self.lab_id),
            self.lab_event,
        )


## Instances of LabEvent.


@_dataclass_no_eq
class RefreshLab(LabEvent):
    _key = (0,)


@_dataclass_no_eq
class LabEventInGroupProject(LabEvent):
    group_id: Any
    group_project_event: GroupProjectEvent

    @property
    def _key(self):
        return (1, util.ordering.DiscreteOrder(self.group_id), self.group_project_event)


## Instances of GroupProjectEvent.


@_dataclass_no_eq
class GroupProjectTagEvent(GroupProjectEvent):
    _key: ClassVar = util.ordering.DiscreteOrder(0)


@_dataclass_no_eq
class GroupProjectIssueEvent(GroupProjectEvent):
    _key: ClassVar = util.ordering.DiscreteOrder(1)


@_dataclass_no_eq
class GroupProjectGradingMergeRequestEvent(GroupProjectEvent):
    variant: Any
    grading_merge_request_event: GradingMergeRequestEvent

    @property
    def _key(self):
        return (
            2,
            util.ordering.DiscreteOrder(self.variant),
            self.grading_merge_request_event,
        )


## Instances of GradingMergeRequestEvent


@_dataclass_no_eq
class GradingMergeRequestAssigneeEvent(GradingMergeRequestEvent):
    _key: ClassVar = util.ordering.DiscreteOrder(0)


@_dataclass_no_eq
class GradingMergeRequestLabelEvent(GradingMergeRequestEvent):
    _key: ClassVar = util.ordering.DiscreteOrder(1)


@_dataclass_no_eq
class GradingMergeRequestNoteEvent(GradingMergeRequestEvent):
    _key: ClassVar = util.ordering.DiscreteOrder(1)
