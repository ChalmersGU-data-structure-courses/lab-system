import inspect

_NOT_FOUND = object()


class instance_memoizer:
    """
    A memoizer for an instance function.
    Exposes the underlying cache via the attribute 'cache'.
    Keys for the cache are computed ia the instance method 'key' from arguments for the decorated method;
    """

    def __init__(self, instance, function):
        self._instance = instance
        self._function = function
        self.__doc__ = function.__doc__

        self._signature = inspect.signature(self._function)
        self._self_name = next(iter(self._signature.parameters))
        self.cache = {}

    def key(self, *args, **kwargs):
        """
        The key in the dictionary 'cache' for the given arguments.
        """
        params = self._signature.bind(self, *args, **kwargs)
        params.apply_defaults()
        params.arguments.pop(self._self_name)
        return tuple(params.arguments.values())

    def __call__(self, *args, **kwargs):
        key = self.key(*args, **kwargs)
        r = self.cache.get(key, _NOT_FOUND)
        if not r is _NOT_FOUND:
            return r

        r = self._function(self._instance, *args, **kwargs)
        self.cache[key] = r
        return r

    def set(self, value, *args, **kwargs):
        """
        Set the cache entry for the given arguments.
        The value is passed in the first argument position.
        """
        self.cache[self.key(*args, **kwargs)] = value

    def evict(self, *args, **kwargs):
        """
        Evict the cache entry for the given arguments.
        """
        self.cache.pop(self.key(*args, **kwargs), None)


class instance_cache:
    """
    A decorator for instance-local instance method memoizing cache.
    Replaces the instance method by an instance of instance_memoizer.
    """

    def __init__(self, function):
        self.function = function
        self.__doc__ = function.__doc__

    def __set_name__(self, owner, name):
        self.name = name

    def __get__(self, instance, owner=None):
        if instance is None:
            return self

        x = instance_memoizer(instance, self.function)
        instance.__dict__[self.name] = x
        return x
