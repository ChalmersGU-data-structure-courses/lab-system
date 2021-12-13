import dataclasses
from pathlib import Path
import typing

import general
import ordering


# ## Interfaces.
#
# Each interface defined here forms a preorder (the priority preorder).
# The partial order relation is inherited from the attribute _key.
# This attribute defines the priority of an instance.
# If a._key <= b._key, then a has priority over b.

_dataclass_incomparable = dataclasses.dataclass(eq = False)

_decorator = general.compose(
    _dataclass_incomparable,
    ordering.preorder_from_key,
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
        return (1, ordering.DiscreteOrder(self.course_dir), self.course_event)


# ## Instances of CourseEvent.

@_dataclass_incomparable
class ReloadCourse(CourseEvent):
    _key = (0,)

@_dataclass_incomparable
class CourseEventInLab(CourseEvent):
    lab_id: typing.Any
    lab_event: LabEvent

    @property
    def _key(self):
        return (1, ordering.DiscreteOrder(self.lab_id), self.lab_event)


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
        return (1, ordering.DiscreteOrder(self.group_id), self.group_project_event)


# ## Instances of GroupProjectEvent.

@_dataclass_incomparable
class GroupProjectWebhookEvent(GroupProjectEvent):
    pass

@_dataclass_incomparable
class GroupProjectTagEvent(GroupProjectWebhookEvent):
    _key = 0

@_dataclass_incomparable
class GroupProjectIssueEvent(GroupProjectWebhookEvent):
    _key = 1
    '''
    GroupProjectIssueEvent has priority over GroupProjectTagEvent.
    This is because we need to reload requests anyway
    after reloading responses before merging them.
    '''
