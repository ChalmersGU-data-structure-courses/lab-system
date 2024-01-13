import dataclasses
import datetime
import functools
import itertools
import logging
from typing import Optional, Iterable, Tuple

import gql
from gql.transport.requests import RequestsHTTPTransport
from gql.dsl import DSLSchema

import more_itertools

import general
import path_tools
import print_parse
from graph_ql.tools import (
    query, with_processing, distribute, tupling, lift, over_list, labelled,
)
from this_dir import this_dir


logger = logging.getLogger(__name__)

@functools.cache
def pp_id(scope):
    return print_parse.regex_int(f'gid://gitlab/{scope}/{{}}')

pp_date = print_parse.datetime('%Y-%m-%d %H:%M:%S.%f000 %z')

def cursor(cls):
    cls = dataclasses.dataclass(cls)
    cls = print_parse.dataclass_json(cls)
    cls.pp = print_parse.maybe(print_parse.compose(
        cls.pp,
        print_parse.base64_standard_str,
    ))
    return cls

@cursor
class CreatedCursor:
    id: int
    created_at: datetime.datetime = print_parse.dataclass_field(pp_date)

@cursor
class GroupCursor:
    id: int
    name: str

def retrieve_all_from_cursor(self, callback, cursor = None):
    '''
    The callback function takes a cursor and returns a pair (results, cursor).
    Here:
    * results is an iterable of results up until the next cursor,
    * cursor is the next cursor, or None if the end was reached.

    Returns an iterable of all the results.
    '''
    while True:
        (results, cursor) = callback(cursor)
        yield from results
        if cursor is None:
            break

class Client:
    def __init__(self, domain, gitlab_token, schema_full = False):
        '''
        Loading the full schema 'gitlab_schema.graphql' takes 2s on my laptop.
        Therefore, we maintain an extract 'gitlab_schema_extract.graphql' for the queries this class supports.
        '''
        self.transport = RequestsHTTPTransport(
            url = f'https://{domain}/api/graphql',
            verify = True,
            retries = 0,  # TODO: change to a higher value
            auth = general.BearerAuth(gitlab_token),
        )

        filename = 'gitlab_schema{}.graphql'.format('' if schema_full else '_extract')
        path_schema = this_dir / 'graph_ql' / filename
        self.client = gql.Client(
            transport = self.transport,
            schema = path_schema.read_text(),
        )
        self.ds = DSLSchema(self.client.schema)

        self.queue_queries = []
        self.queue_results = []

    @functools.cached_property
    def session(self):
        return self.client.connect_sync()

    def close(self):
        if 'session' in self.__dict__:
            self.session.close()
            del self.session

    def execute(self, query, values = None):
        (query, process) = with_processing(query)
        #print(print_ast(query))
        return process(self.session.execute(query, variable_values = values))

    def execute_queries(self, queries):
        def name(i):
            return f'q{i}'

        queries = more_itertools.countable(queries)
        result = self.execute_query(**{
            name(i): query
            for (i, query) in enumerate(queries)
        })
        for i in more_itertools.take(queries.items_seen, itertools.count()):
            yield result[name(i)]

    def queue_query(self, query, process = None):
        (query, process) = with_processing(query)

        i = len(self.queue_queries)
        self.queue_queries.append(query)
        results = self.queue_results

        def access_result():
            return process(results[i])
        return access_result

    def flush_queue(self):
        if self.queue_queries:
            self.queue_results.extend(self.execute(labelled(query)(*self.queue_queries)))
        self.queue_queries = []
        self.queue_results = []

    def query_complexity(self):
        return distribute(self.ds.Query.queryComplexity.select)(
            self.ds.QueryComplexity.limit,
            self.ds.QueryComplexity.score,
        )

    @functools.cached_property
    def user_core_id(self):
        return (self.ds.UserCore.id, pp_id('User').parse)

    @functools.cached_property
    def user_core_created_at(self):
        return (self.ds.UserCore.created_at, pp_date.parse)

    def retrieve_all_users_page(self, cursor: Optional[CreatedCursor] = None):
        ds = self.ds
        return self.execute(lift(query)(
            tupling(ds.Query.users(
                sort = 'CREATED_ASC',
                after = CreatedCursor.pp.print(cursor),  # type: ignore[attr-defined]
            ).select)(
                over_list(tupling(ds.UserCoreConnection.nodes.select)(
                    self.user_core_id,
                    ds.UserCore.username,
                )),
                lift(ds.UserCoreConnection.pageInfo.select)(
                    (ds.PageInfo.endCursor, CreatedCursor.pp.parse),  # type: ignore[attr-defined]
                ),
            ),
        ))

    def retrieve_all_users_from(
        self,
        last_requested: Optional[datetime.datetime] = None,
        safety_interval: datetime.timedelta = datetime.timedelta(minutes = 10),
        last_known_id: Optional[int] = None,
    ) -> Iterable[Tuple[int, str]]:
        '''
        Retrieve all users, optionally starting from last_requested.

        Other arguments:
        * last_known_id: filter output to users with larger id
        * safety_interval:
          Optional interval subtracted from last_requested.
          This should account for:
          - non-monotonicity in the server time.
          - mismatches between local and server time
          - inaccuracies when converting between time formats
        Returns an iterable of pairs of ids and usernames.
        The order of this iterable is not specified.

        The GraphQL API for retrieving objects sucks.
        There seems to be no way of retrieving objects in order of id.
        (I assume that ids are guaranteed to be monotone.)
        And the provided order on created_at does not correspond to a public user_core attribute.
        This is the reason for this complicated setup.
        '''
        if last_requested and safety_interval:
            last_requested = last_requested - safety_interval

        cursor = None
        if last_requested is not None:
            cursor = CreatedCursor(created_at = last_requested, id = 0)  # type: ignore

        while True:
            (users, cursor) = self.retrieve_all_users_page(cursor = cursor)
            for (id, username) in users:
                if last_known_id is None or id > last_known_id:
                    yield (id, username)

            if cursor is None:
                break

    # @functools.cached_property
    # def project_members_direct(self):
    #     ds = self.ds
    #     return nodes(ds.Project.projectMembers())(
    #         lift(ds.MemberInterfaceConnection.nodes.select)(
    #             lift(ds.MemberInterface.user.select)(ds.UserCore.username)
    #         )
    #     )

    # def query_project_members_direct(self, full_path):
    #     return lift(self.ds.Query.project(fullPath = full_path).select)(
    #         self.project_members_direct
    #     )

    # def retrieve_project_members(self, full_path):
    #     return self.execute(lift(query)(
    #         self.query_project_members_direct(full_path)
    #     ))

    # def retrieve_projects_members(self, full_paths):
    #     return self.execute(labelled(query)(*(
    #         self.query_project_members_direct(full_path)
    #         for full_path in full_paths
    #     )))

    # def retrieve_projects_members(self, project_ids):
    #     var = DSLVariableDefinitions()
    #     s = nodes(self.ds.Query.projects(ids = var.ids))(
    #         lift(self.ds.ProjectConnection.nodes.select)(
    #             self.project_members_direct
    #         )
    #     )
    #     q = lift(functools.partial(query_with_variables, var))(
    #         s
    #     )
    #     return self.execute(q, values = {'ids': [pp_id('Project').print(id) for id in project_ids]})

    # def retrieve_all_users(self):
    #     ds = self.ds
    #     return self.execute(lift(query)(
    #         nodes(ds.Query.users(first = 100))(
    #             tupling(ds.UserCoreConnection.nodes.select)(
    #                 self.user_core_id,
    #                 ds.UserCore.username,
    #             )
    #         ),
    #     ))

    # @functools.cached_property
    # def response_issues(self):
    #     ds = self.ds
    #     return nodes(ds.Project.issues(sort = 'CREATED_ASC'))(
    #         distribute(ds.IssueConnection.nodes.select)(
    #             web_url = ds.Issue.webUrl,
    #             author = lift(ds.Issue.author.select)(ds.UserCore.username),
    #             title = ds.Issue.title,
    #             state = ds.Issue.state
    #         )
    #     )

    # def retrieve_issues_in_project(self, path):
    #     return self.execute(lift(query)(
    #         lift(self.ds.Query.project(fullPath = path).select)(
    #             self.response_issues
    #         )
    #     ))

    # def retrieve_all_issues_for_lab(self, groups_path, project_name):
    #     def callback(cursor):
    #         ds = self.ds
    #         return self.execute(lift(query)(lift(ds.Query.group(fullPath = groups_path).select)(
    #             tupling(ds.Group.descendantGroups(
    #                 includeParentDescendants = False,
    #                 after = GroupCursor.pp.print(cursor),
    #             ).select)(
    #                 over_list(tupling(ds.GroupConnection.nodes.select)(
    #                     ds.Group.path,
    #                     graph_ql.tools.nodes_unique(ds.Group.projects(
    #                         search = project_name,
    #                         sort = 'SIMILARITY',
    #                         first = 1,
    #                     ))(
    #                         lift(ds.ProjectConnection.nodes.select)(
    #                             self.response_issues,
    #                         )
    #                     )
    #                 )),
    #                 lift(ds.GroupConnection.pageInfo.select)(
    #                     (ds.PageInfo.endCursor, GroupCursor.pp.parse),
    #                 ),
    #             )
    #         )))

    #     yield from retrieve_all_from_cursor(callback, None)


class GitlabUsers(path_tools.JSONAttributeCache):
    # cached attribute
    users: dict[int, str]

    username_to_id: dict[str, int]

    def initialize(self):
        self.users = dict()
        self.username_to_id = dict()

    def __init__(self, cache_dir, client):
        super().__init__(
            path = cache_dir / 'gitlab' / 'users',
            attribute = 'users',
        )
        self.client = client

    def update(self):
        '''Returns the collection of new usernames.'''
        with self.updating:
            users_new = list(self.client.retrieve_all_users_from(
                last_requested = None if self.users is None else self.time,
            ))

            for (id, username) in users_new:
                self.users[id] = username
                self.username_to_id[username] = id

            return [username for (id, username) in users_new]

from gitlab_config_personal import gitlab_private_token  # noqa: E402

with general.timing(level = logging.INFO):
    c = Client('git.chalmers.se', gitlab_private_token)

#c = client.client
#s = c.connect_sync()

# c.retrieve_all_users()
