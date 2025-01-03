import dataclasses
from typing import Optional

import util.hashed_file_cache
import util.print_parse


class UsersCache(util.hashed_file_cache.HashedFileCacheSerializer):
    # TODO: use this.
    @util.print_parse.dataclass_dict
    @dataclasses.dataclass
    class User:
        id: int
        username: str

    # cached data
    data: list["User"]

    # supplemental data, determined by the cached data.
    username_from_id: dict[int, str]
    id_from_username: dict[str, int]
    last_known_id: Optional[int]

    def _supplement_initialize(self):
        self.username_from_id = {}
        self.id_from_username = {}
        self.last_known_id = None

    def _supplement_add_item(self, id, username):
        self.username_from_id[id] = username
        self.id_from_username[username] = id
        if self.last_known_id is None:
            self.last_known_id = id
        else:
            self.last_known_id = max(self.last_known_id, id)

    def deserialize(self, bytes_):
        super().deserialize(bytes_)
        self._supplement_initialize()
        for id, username in self.data:
            self._supplement_add_item(id, username)

    def _initialize(self):
        try:
            self.read()
        except self.CacheEmptyError:
            self.data = []
            self._supplement_initialize()
            self.update()

    def __init__(self, cache_dir, gitlab_graphql_client):
        super().__init__(
            path=cache_dir,
            serializer=util.print_parse.compose(
                util.print_parse.json_coding_nice,
                util.print_parse.string_coding,
            ),
        )
        self.client = gitlab_graphql_client
        self._initialize()

    def update(self):
        """
        Returns a list of new pairs (id, username).
        """
        with self.update_manager():
            new_items = list(
                self.client.retrieve_all_users_from(
                    last_requested=self.update_date,
                    last_known_id=self.last_known_id,
                )
            )
            self.data.extend(new_items)
            for id, username in new_items:
                self._supplement_add_item(id, username)

            if not new_items:
                raise self.DataUnchanged()

        return new_items
