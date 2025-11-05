import enum
import typing


def patch_enum_type_params():
    """
    Patch enum metaclass to allow for type parameters in enums.
    These are useful for abstract enum classes.

    We could instead have created a metaclass inheriting from enum.EnumType.
    But that might mess with the integration of enumerations in type checkers.

    TODO:
    Actually, the EnumType metaclass repurposes this syntax for member lookup.
    So we would have to disable that.
    But that would break things.
    So this approach is not viable.
    """
    # pylint: disable=protected-access
    # Make patching idempotent.
    if hasattr(enum.EnumType, "_get_mixins_orig_"):
        return

    enum.EnumType._get_mixins_orig_ = enum.EnumType._get_mixins_

    def get_mixins(class_name, bases):
        if bases and bases[-1] == typing.Generic:
            bases = bases[:-1]
        return enum.EnumType._get_mixins_orig_(class_name, bases)

    enum.EnumType._get_mixins_ = get_mixins


# patch_enum_type_params()


class EnumSpecType(enum.EnumType):
    @classmethod
    def _get_mixins_(mcs, class_name, bases):
        if bases and bases[-1] == typing.Generic:
            bases = bases[:-1]
        return enum.EnumType._get_mixins_(class_name, bases)

    def __getitem__(cls, name):
        return cls.__class_getitem__(name)


class EnumSpec[X](metaclass=EnumSpecType):
    """
    A subclass of enum for enumerations of specifications.
    These are enumerations with separate data attached to every entry.
    The data is accessed via the value attribute.
    In this way, we can avoid repeating ourselves with a secondary dictionary.
    For example:

    @dataclasses.dataclass(frozen=True)
    class StrictnessSpec:
        flag: str
        description: str
        crash_on_error: bool
        allow_warnings: bool

    class Strictness(EnumSpec):
        LOW = StrictnessSpec("low", "...", False, True)
        MEDIUM = StrictnessSpec("medium", "...", True, True)
        HIGH = StrictnessSpec("high", "...", True, False)

    print("Available strictness profiles:")
    for strictness in Strictness:
        spec = strictness.spec
        print(f"{spec.flag}: {spec.description}")
    """

    value: X

    def __new__(cls: type, value):
        x: object
        x = object.__new__(cls)
        x._value_ = value
        x.value = value
        return x

    def __repr__(self):
        return f"{self.__class__.__name__}.{self._name_}"
