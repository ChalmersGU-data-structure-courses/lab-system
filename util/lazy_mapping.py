from collections.abc import KeysView, ItemsView, ValuesView, Mapping, MutableMapping
from functools import cached_property


class LazyMapping[Key, Value](Mapping[Key, Value]):
    """
    A mapping that is loaded lazily.
    Implement the abstract method load.
    Methods that can return without doing a load do so.
    """

    @cached_property
    def mapping(self) -> dict[Key, Value]:
        return {}

    @cached_property
    def complete(self) -> bool:
        return False

    def load_internal(self):
        """Load the missing entries in self.complete."""
        raise NotImplementedError()

    def load(self):
        """
        Load the mapping.
        Preserves the existing entries and fills in the rest.
        """
        self.load_internal()
        self.complete = True

    def __contains__(self, key):
        if not key in self.mapping and not self.complete:
            self.load()
        return key in self.mapping

    def __getitem__(self, key):
        if not key in self.mapping and not self.complete:
            self.load()
        return self.mapping[key]

    def __len__(self):
        if not self.complete:
            self.load()
        return len(self.mapping)

    def __iter__(self):
        if not self.complete:
            self.load()
        return iter(self.mapping)

    def keys(self):
        return KeysView(self.mapping)

    def items(self):
        return ItemsView(self.mapping)

    def values(self):
        return ValuesView(self.mapping)


# pylint: disable-next=abstract-method
class LazyMutableMapping[Key, Value](
    LazyMapping[Key, Value],
    MutableMapping[Key, Value],
):
    def clear(self):
        self.mapping.clear()
        self.complete = False

    def __setitem__(self, key, value):
        self.mapping[key] = value

    def __delitem__(self, key):
        del self.mapping[key]
