import dataclasses
import typing

import general


dataclass_incomparable = dataclasses.dataclass(eq = False)

@dataclass_incomparable
class Event:
    pass

@dataclass_incomparable
class ProgramTermination(Event):
    pass

@dataclass_incomparable
class LabEvent(Event):
    lab_id: typing.Any

@dataclass_incomparable
class LabRefresh(LabEvent):
    pass

@dataclass_incomparable
class GroupProjectEvent(LabEvent):
    group_id: typing.Any
    event: dict

@dataclass_incomparable
class GroupProjectEventTag(GroupProjectEvent):
    pass

@dataclass_incomparable
class GroupProjectEventIssue(GroupProjectEvent):
    pass

def __le__(a, b):
    R = general.BoolException
    cases = [(a, True), (b, False)]

    def test_top(cls):
        for (x, result) in cases:
            if isinstance(x, cls):
                raise R(result)

    def both_instance(cls):
        return all(isinstance(x, cls) for (x, _) in cases)

    def failure():
        raise ValueError(f'Unexpected event comparison:\n{a}\nvs.\n{b}')

    try:
        test_top(ProgramTermination)

        if not both_instance(LabEvent):
            failure()

        if not a.lab_id == b.lab_id:
            raise R(False)
        test_top(LabRefresh)

        if not both_instance(GroupProjectEvent):
            failure()

        if not a.group_id == b.group_id:
            raise R(False)

        for cls in [GroupProjectEventTag, GroupProjectEventIssue]:
            if both_instance(cls):
                raise R(True)
        raise R(False)
    except R as e:
        return e.value

Event.__le__ = __le__
general.partial_ordering(Event)
