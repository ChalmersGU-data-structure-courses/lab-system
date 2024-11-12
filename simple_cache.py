import datetime
from pathlib import Path, PurePath
import json
import logging

import path_tools


logger = logging.getLogger(__name__)


class SimpleCache:
    __filename = "_value"

    def __init__(self, cache_dir):
        self.cache_dir = Path(cache_dir)
        logger.log(logging.INFO, "initializing cache: " + str(cache_dir))
        Path(cache_dir).mkdir(exist_ok=True)

    def __get_path(self, path):
        assert not path.is_absolute()
        assert all(not x in ["", ".", ".."] for x in path.parts)
        return self.cache_dir / path / self.__filename

    #    def __with_file(self, path, mode, callback):
    #        with open(self.__get_path(path), mode) as file:
    #            callback(file)

    #    def exists(self, path):
    #        return self.__get_path(path).exists();

    #    def read(self, path, reader):
    #        with open(self.__get_path(path), 'r') as file:
    #            return reader(file)

    #    def write(self, path, writer, x):
    #        p = self.__get_path(path)
    #        p.parent.mkdir(parents = True, exist_ok = True)
    #        with open(self.__get_path(path), 'w') as file:
    #            writer(file, x)

    def with_cache_bare(self, path, reader, writer, constructor, use_cache=True):
        """
        High-level interface.
        use_cache determines whether the current cache entry is read; it can be:
        * a Boolean
        * a timestamp: only entries at most this old are considered valid
        """
        logger.log(logging.DEBUG, "constructing cached path: " + str(path))
        real_path = self.__get_path(path)

        if isinstance(use_cache, datetime.datetime):
            really_use_cache = (
                real_path.exists() and path_tools.modified_at(real_path) >= use_cache
            )
        else:
            really_use_cache = bool(use_cache) and real_path.exists()

        if really_use_cache:
            logger.log(logging.DEBUG, "reading")
            x = reader(real_path)
        else:
            c = constructor()
            logger.log(logging.DEBUG, "writing")
            p = self.__get_path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            x = writer(real_path, c)

        return x

    def with_cache_file(self, path, constructor, use_cache=True):
        def file_reader(real_path):
            return real_path

        def file_writer(real_path, c):
            return c.rename(real_path)

        def file_constructor():
            temp_file = Path(self.cache_dir / PurePath("__temp"))
            constructor(temp_file)
            return temp_file

        return self.with_cache_bare(
            path, file_reader, file_writer, file_constructor, use_cache
        )

    def with_cache_open(self, path, reader, writer, constructor, use_cache=True):
        def bare_reader(real_path):
            with real_path.open() as file:
                return reader(file)

        def bare_writer(real_path, x):
            with real_path.open("w") as file:
                writer(file, x)
            return x

        return self.with_cache_bare(
            path, bare_reader, bare_writer, constructor, use_cache
        )

    def with_cache_json(self, path, constructor, use_cache=True):
        json_reader = json.load

        def json_writer(file, x):
            return json.dump(x, file, indent=4, sort_keys=True)

        return self.with_cache_open(
            path, json_reader, json_writer, constructor, use_cache
        )


class JSONCache:
    def __init__(self, cache_dir):
        self.cache_dir = Path(cache_dir)
        logger.log(logging.INFO, "initializing cache: " + str(cache_dir))
        Path(cache_dir).mkdir(exist_ok=True)


# Components:
# - procedure for producing value
# - key used for caching
# - cached value
# - caching time: when was the cached value produced?
# - derivates of value
#
# Before using derivatives of a value, we specify how recent we want them to be.


# class CourseUsers:
