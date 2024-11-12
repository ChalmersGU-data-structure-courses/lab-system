import dataclasses
import typing


# There does not seem to be an easy way to metaprogram this class.
# Python does not seem to expose the translation from comparison operator calls
# to calls of rich comparison methods as a callable library function.
class ReverseKey:
    def __init__(self, key):
        self.key = key

    def __lt__(self, other):
        return other.key < self.key

    def __le__(self, other):
        return other.key <= self.key

    def __eq__(self, other):
        return other.key == self.key

    def __ne__(self, other):
        return other.key != self.key

    def __gt__(self, other):
        return other.key > self.key

    def __ge__(self, other):
        return other.key >= self.key


def reverse_key(f=lambda x: x):
    return lambda x: ReverseKey(f(x))


def discrete_order(cls):
    def __lt__(_self, _other):
        return False

    cls.__lt__ = __lt__

    def __le__(self, other):
        return self == other

    cls.__le__ = __le__

    def __gt__(_self, _other):
        return False

    cls.__gt__ = __gt__

    def __ge__(self, other):
        return self == other

    cls.__ge__ = __ge__

    return cls


def preorder(cls):
    """
    Class decorator that fills in missing ordering methods for
    a preorder where a < b should mean a <= b without b <= a.
    The given class must define __le_.
    For this, we define __lt__.
    """

    def __lt__(a, b):
        return a <= b and not b <= a

    cls.__lt__ = __lt__
    return cls


def equality_from_key(cls, key=lambda x: x._key):
    def __eq__(self, other):
        return key(self) == key(other)

    cls.__eq__ = __eq__

    def __ne__(self, other):
        return key(self) != key(other)

    cls.__ne__ = __ne__

    return cls


def preorder_from_key(cls, key=lambda x: x._key):
    def __lt__(self, other):
        return key(self) < key(other)

    cls.__lt__ = __lt__

    def __le__(self, other):
        return key(self) <= key(other)

    cls.__le__ = __le__

    def __gt__(self, other):
        return key(self) > key(other)

    cls.__gt__ = __gt__

    def __ge__(self, other):
        return key(self) >= key(other)

    cls.__ge__ = __ge__

    return cls


def order_from_key(cls, key=lambda x: x._key):
    equality_from_key(cls, key)
    preorder_from_key(cls, key)
    return cls


@dataclasses.dataclass
@discrete_order
class DiscreteOrder:
    value: typing.Any

    def __init__(self, value):
        self.value = value
