import dataclasses
from typing import Optional

import hashed_file_cache
import general
import print_parse


class UsersCache(hashed_file_cache.HashedFileCacheSerializer):
    # TODO: use this.
    @print_parse.dataclass_dict
    @dataclasses.dataclass
    class User:
        id: int
        username: str

    # cached data
    data: list['User']

    # supplemental data, determined by the cached data.
    username_from_id: dict[int, str]
    id_from_username: dict[str, int]
    last_known_id: Optional[int]

    def _supplement_initialize(self):
        self.username_from_id = dict()
        self.id_from_username = dict()
        self.last_known_id = None

    def _supplement_add_item(self, id, username):
        self.username_from_id[id] = username
        self.id_from_username[username] = id
        if self.last_known_id is None:
            self.last_known_id = id
        else:
            self.last_known_id = max(self.last_known_id, id)

    def deserialize(self, bytes):
        super().deserialize(bytes)
        self._supplement_initialize()
        for (id, username) in self.data:
            self._supplement_add_item(id, username)

    def _initialize(self):
        try:
            self.read()
        except self.CacheEmptyError:
            self.data = list()
            self._supplement_initialize()
            self.update()

    def __init__(self, cache_dir, gitlab_graphql_client):
        super().__init__(
            path = cache_dir,
            serializer = print_parse.compose(print_parse.json_coding_nice, print_parse.string_coding),
        )
        self.client = gitlab_graphql_client
        self._initialize()

    def update(self):
        '''
        Returns a list of new pairs (id, username).
        '''
        with self.update_manager():
            new_items = list(self.client.retrieve_all_users_from(
                last_requested = self.update_date,
                last_known_id = self.last_known_id,
            ))
            self.data.extend(new_items)
            for (id, username) in new_items:
                self._supplement_add_item(id, username)

            if not new_items:
                raise self.DataUnchanged()

        return new_items

import gitlab.graphql
from gitlab_config_personal import canvas.client_rest as canvas_auth_token, gitlab_private_token

with general.timing():
    c = gitlab.graphql.Client('git.chalmers.se', gitlab_private_token)

u = UsersCache('gitlab_users', c)

with general.timing():
    u.update()
with general.timing():
    u.clear()
with general.timing():
    u.update()
