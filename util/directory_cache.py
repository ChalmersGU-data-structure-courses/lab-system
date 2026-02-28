from abc import abstractmethod
from contextlib import contextmanager
import json
import logging
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile
from typing import Iterator, IO

from util.general import JSON

logger = logging.getLogger(__name__)


class StoreMiss(Exception):
    pass


class Store[Key, Value]:
    @abstractmethod
    def read(self, key: Key) -> Value: ...

    @abstractmethod
    def write(self, key: Key, value: Value) -> None: ...

    def exists(self, key: Key) -> bool:
        try:
            self.read(key)
        except StoreMiss:
            return False
        return True


class Query[Key, Value]:
    @abstractmethod
    def key(self) -> Key: ...

    @abstractmethod
    def compute(self) -> Value: ...

    def log_item(self) -> str:
        return str(self.key())


class StoreQueryMixin[Key, Value](
    Store[Key, Value]
):  # pylint: disable = abstract-method
    def compute(self, query: Query[Key, Value], key: Key | None = None) -> Value:
        logger.info(f"Computing {query.log_item()}.")
        if key is None:
            key = query.key()
        r = query.compute()
        self.write(key, r)
        return r

    def get(self, query: Query[Key, Value], update: bool = False) -> Value:
        key = query.key()
        if not update:
            try:
                return self.read(key)
            except StoreMiss:
                pass
        return self.compute(query, key)


class DirectoryFileStore:
    path: Path
    text: bool

    def __init__(self, path: Path, text: bool = True):
        self.path = path
        self.text = text
        self.path.mkdir(exist_ok=True)

    def _get_path(self, key: PurePosixPath) -> Path:
        assert not key.is_absolute()
        assert all(part not in [".", ".."] for part in key.parts)
        return self.path / key

    def _open_args(self, mode: str):
        match self.text:
            case True:
                yield ("mode", mode)
                yield ("encoding", "utf-8")
            case False:
                yield ("mode", mode + "b")

    def _open(self, path: Path, mode: str) -> IO:
        match self.text:
            case True:
                return path.open(mode=mode, encoding="utf-8")
            case False:
                return path.open(mode=mode + "b")

    @contextmanager
    def file_read(self, key: PurePosixPath) -> Iterator[IO]:
        path = self._get_path(key)
        yield path.open(**dict(self._open_args("r")))

    @contextmanager
    def file_write(self, key: PurePosixPath) -> Iterator[IO]:
        path = self._get_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmpfile = NamedTemporaryFile(
            **dict(self._open_args("w")),
            dir=path.parent,
            prefix=path.name + ".",
            suffix=".tmp",
            delete=False,
        )
        path_tmp = Path(tmpfile.name)
        try:
            try:
                yield tmpfile
            finally:
                tmpfile.close()
        except:
            path_tmp.unlink()
            raise
        path_tmp.replace(path)

    def exists(self, key: PurePosixPath) -> bool:
        try:
            with self.file_read(key):
                pass
            return True
        except FileNotFoundError:
            return False


class DirectoryStore(DirectoryFileStore, StoreQueryMixin[PurePosixPath, str | bytes]):
    def read(self, key: PurePosixPath) -> str | bytes:
        try:
            with self.file_read(key) as file:
                return file.read()
        except FileNotFoundError:
            raise StoreMiss() from None

    def write(self, key: PurePosixPath, value: str | bytes) -> None:
        with self.file_read(key) as file:
            file.write(value)


class DirectoryJSONStore(DirectoryFileStore, StoreQueryMixin[PurePosixPath, JSON]):
    def __init__(self, path: Path):
        super().__init__(path, True)

    def read(self, key: PurePosixPath) -> JSON:
        try:
            with self.file_read(key) as file:
                return json.load(file)
        except FileNotFoundError:
            raise StoreMiss() from None

    def write(self, key: PurePosixPath, value: JSON) -> None:
        with self.file_write(key) as file:
            json.dump(value, file, indent=2)
