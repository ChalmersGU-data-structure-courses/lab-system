import dataclasses
import datetime
import functools
import logging
from typing import Optional, Iterable, Tuple

from gql.transport.requests import RequestsHTTPTransport

import util.general
import util.print_parse
import graphql_.client
from graphql_.tools import query, distribute, tupling, lift, over_list
from util.this_dir import this_dir


logger = logging.getLogger(__name__)


@functools.cache
def pp_id(scope):
    return util.print_parse.regex_int(f"gid://gitlab/{scope}/{{}}")


pp_date = util.print_parse.datetime("%Y-%m-%d %H:%M:%S.%f000 %z")


def cursor(cls):
    cls = dataclasses.dataclass(cls)
    cls = util.print_parse.dataclass_json(cls)
    cls.pp_cursor = util.print_parse.maybe(
        util.print_parse.compose(
            cls.pp_json,
            util.print_parse.base64_standard_str,
        )
    )
    return cls


@cursor
class CreatedCursor:
    id: int
    created_at: datetime.datetime = util.print_parse.dataclass_field(pp_date)


@cursor
class GroupCursor:
    id: int
    name: str


class Client(graphql_.client.ClientBase):
    def __init__(self, domain, token, schema_full=False):
        """
        Loading the full schema 'gitlab_schema.graphql' takes 2s on my laptop.
        Therefore, we maintain an extract 'gitlab_schema_extract.graphql' for the queries this class supports.
        """
        transport = RequestsHTTPTransport(
            url=f"https://{domain}/api/graphql",
            verify=True,
            retries=0,  # TODO: change to a higher value
            auth=util.general.BearerAuth(token),
        )
        version = "" if schema_full else "_extract"
        filename = f"gitlab_schema{version}.graphql"
        path_schema = this_dir / "graphql_" / filename
        super().__init__(transport, path_schema)

    def query_complexity(self):
        return distribute(self.ds.Query.queryComplexity.select)(
            self.ds.QueryComplexity.limit,
            self.ds.QueryComplexity.score,
        )

    @functools.cached_property
    def user_core_id(self):
        return (self.ds.UserCore.id, pp_id("User").parse)

    @functools.cached_property
    def user_core_created_at(self):
        return (self.ds.UserCore.created_at, pp_date.parse)

    def retrieve_all_users_page(self, cursor: Optional[CreatedCursor] = None):
        ds = self.ds
        return self.execute(
            lift(query)(
                tupling(
                    ds.Query.users(
                        sort="CREATED_ASC",
                        after=CreatedCursor.pp_cursor.print(cursor),  # type: ignore[attr-defined]
                    ).select
                )(
                    over_list(
                        tupling(ds.UserCoreConnection.nodes.select)(
                            self.user_core_id,
                            ds.UserCore.username,
                        )
                    ),
                    lift(ds.UserCoreConnection.pageInfo.select)(
                        (ds.PageInfo.endCursor, CreatedCursor.pp_cursor.parse),  # type: ignore[attr-defined]
                    ),
                ),
            )
        )

    def retrieve_all_users_from(
        self,
        last_requested: Optional[datetime.datetime] = None,
        safety_interval: datetime.timedelta = datetime.timedelta(minutes=10),
        last_known_id: Optional[int] = None,
    ) -> Iterable[Tuple[int, str]]:
        """
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
        """
        cursor = None
        if last_requested is not None:
            cursor = CreatedCursor(created_at=last_requested - safety_interval, id=0)  # type: ignore

        def f(item):
            (id, username) = item
            return last_known_id is None or id > last_known_id

        yield from filter(
            f,
            graphql_.client.retrieve_all_from_cursor(
                self.retrieve_all_users_page,
                cursor,
            ),
        )

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
    #                 after = GroupCursor.pp_cursor.print(cursor),
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
    #                     (ds.PageInfo.endCursor, GroupCursor.pp_cursor.parse),
    #                 ),
    #             )
    #         )))

    #     yield from retrieve_all_from_cursor(callback, None)
