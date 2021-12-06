import dataclasses
import typing

import general


dataclass_incomparable = dataclasses.dataclass(eq = False)

@dataclass_incomparable
class QueueEvent:
    pass

@dataclass_incomparable
class ProgramTermination(QueueEvent):
    pass

@dataclass_incomparable
class LabEntry:
    lab_id: typing.Any

@dataclass_incomparable
class LabRefresh(LabEntry):
    pass

@dataclass_incomparable
class GroupProjectEvent(LabEntry):
    group_id: typing.Any
    event: dict

@dataclass_incomparable
class GroupProjectEventTag(GroupProjectEvent):
    pass

@dataclass_incomparable
class GroupProjectEventIssue(GroupProjectEvent):
    pass

def less_than(a, b):
    R = general.BoolException
    cases = [(a, False), (b, True)]

    def test_top(cls):
        for (x, result) in cases:
            if isinstance(x, cls):
                raise R(result)

    def both_instance(cls):
        return all(isinstance(x, cls) for (x, _) in cases)

    try:
        test_top(ProgramTermination)

        assert both_instance(LabEntry)
        if not a.lab_id == b.lab_id:
            raise R(False)

        test_top(LabRefresh)

        assert both_instance(GroupProjectEvent)
        if not a.group_id == b.group_id:
            raise R(False)

        for cls in [GroupProjectEventTag, GroupProjectEventIssue]:
            if both_instance(cls):
                raise R(True)
        raise R(False)
    except R as e:
        return e.value
