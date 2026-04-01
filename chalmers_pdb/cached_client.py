import json
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path, PurePosixPath
from typing import Callable

import chalmers_pdb.new_rpcc_client
import util.directory_cache
import util.print_parse
from util.general import JSON


@dataclass
class Query(util.directory_cache.Query[PurePosixPath, JSON]):
    client: chalmers_pdb.new_rpcc_client.RPCC
    fun: str
    params: list[JSON]
    named_params: dict[str, JSON]

    def key(self) -> PurePosixPath:
        def format_param(param):
            return json.dumps(param)

        def parts():
            yield self.fun
            for param in self.params:
                yield format_param(param)
            for name, param in sorted(self.named_params.items()):
                yield f"{name}={format_param(param)}"

        return util.print_parse.string_list_as_path.print(list(parts()))

    def compute(self) -> JSON:
        # pylint: disable-next=protected-access
        return self.client._call(self.fun, self.params, self.named_params)


@dataclass
class FunctionProxy:
    proxy: "CachedClient"
    fun_name: str

    def doc(self):
        print(self.proxy.server_documentation(self.fun_name))

    def __call__(self, *args, update: bool = False, **kwargs):
        query = Query(
            client=self.proxy._client,
            fun=self.fun_name,
            params=args,
            named_params=kwargs,
        )
        return self.proxy._cache.get(query, update=update)


class CachedClient:
    _client_constructor: Callable[[], chalmers_pdb.new_rpcc_client.RPCC]
    _cache: util.directory_cache.DirectoryJSONStore

    def __init__(
        self,
        client_constructor: lambda: chalmers_pdb.new_rpcc_client.RPCC,
        cache_dir: Path,
    ):
        self._client_constructor = client_constructor
        self._cache = util.directory_cache.DirectoryJSONStore(cache_dir)

    @cached_property
    def _client(self) -> chalmers_pdb.new_rpcc_client.RPCC:
        return self._client_constructor()

    def __getattr__(self, name):
        if name[0] == "_":
            return None
        return FunctionProxy(self, name)
