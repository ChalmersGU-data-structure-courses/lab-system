import base64
import dataclasses
import functools
import itertools
import logging
from pathlib import Path
from typing import Iterable

import gql
from gql.transport.requests import RequestsHTTPTransport
from gql.dsl import (
    dsl_gql,
    DSLSchema,
    DSLType,
    DSLQuery,
    DSLInlineFragment,
    DSLSelectable,
)
import more_itertools

import canvas.client_rest as canvas
import util.general
import print_parse


logger = logging.getLogger(__name__)


def query(*args, **kwargs):
    return dsl_gql(DSLQuery(*args, **kwargs))


def id_newstyle(type, id):
    return base64.standard_b64encode(f"{type._type}-{id}".encode()).decode()


def wrap_query_execution(f, field):
    return lambda *fields: f(field.select(*fields))[field.name]


def wrap_query_execution_many(f, field_iter):
    for field in field_iter:
        f = wrap_query_execution(f, field)
    return f


@dataclasses.dataclass
class QueryNode:
    type: DSLType
    id: int
    fields: Iterable[DSLSelectable]


class Client:
    def __init__(self, canvas_client):
        self.canvas = canvas_client
        self.transport = RequestsHTTPTransport(
            url=f"https://{self.canvas.domain}/api/graphql",
            verify=True,
            retries=0,  # TODO: change to a higher value
            auth=canvas.BearerAuth(self.canvas.auth_token),
        )
        self.client = gql.Client(
            transport=self.transport,
            schema=(Path(__file__).parent / "graphql/canvas-schema").read_text(),
        )
        self.ds = DSLSchema(self.client.schema)

        self.queue_node_queries = []
        self.queue_node_results = []

    @functools.cached_property
    def session(self):
        return self.client.connect_sync()

    def close(self):
        if "session" in self.__dict__:
            self.session.close()
            del self.session

    def execute(self, query):
        return self.session.execute(query)

    def execute_query(self, *args, **kwargs):
        return self.execute(query(*args, **kwargs))

    def execute_query_single(self, field):
        return self.execute(query(field))[field.name]

    # def node(self, type, id, fields, alias = None):
    #     x = self.ds.Query.node(id = id_newstyle(type, id))
    #     if alias:
    #         x = x.alias(alias)
    #     return x.select(
    #         DSLInlineFragment().on(type).select(*fields),
    #     )

    def node_legacy(self, type, id, alias=None):
        x = self.ds.Query.legacyNode(_id=id, type=str(type._type))
        if alias:
            x = x.alias(alias)
        return lambda *fields: x.select(
            DSLInlineFragment().on(type).select(*fields),
        )

    def execute_query_node(self, type, id):
        return lambda *fields: self.execute_query_single(
            self.node_legacy(type, id)(*fields)
        )

    def execute_query_nodes(self, queries: Iterable[QueryNode]):
        def name(i):
            return f"q{i}"

        queries = more_itertools.countable(queries)
        result = self.execute_query(
            **{
                name(i): self.node_legacy(query.type, query.id)(query.fields)
                for (i, query) in enumerate(queries)
            }
        )
        for i in more_itertools.take(queries.items_seen, itertools.count()):
            yield result[name(i)]

    def queue_query_node(self, type, id, fields):
        i = len(self.queue_node_queries)
        self.queue_node_queries.append(QueryNode(type=type, id=id, fields=fields))
        results = self.queue_node_results

        def access_result():
            return results[i]

        return access_result

    def flush_queue_node(self):
        if self.queue_node_queries:
            self.queue_node_results.extend(
                self.execute_query_nodes(self.queue_node_queries)
            )
        self.queue_node_queries = []
        self.queue_node_results = []

    def course(self, id):
        return self.ds.Query.course(id=id)

    def execute_query_course(self, id):
        return wrap_query_execution(self.execute_query, self.course(id))

    def execute_query_course_user_connection(self, id):
        return wrap_query_execution_many(
            self.execute_query_course(id),
            [
                self.ds.Course.usersConnection,
                self.ds.UserConnection.nodes,
            ],
        )

    def retrieve_course_users(self, id):
        ds = self.ds
        r = self.execute_query_course(id)(
            ds.Course.sectionsConnection.select(
                ds.SectionConnection.nodes.select(
                    ds.Section._id,
                    ds.Section.name,
                ),
            ),
            ds.Course.usersConnection.select(
                ds.UserConnection.nodes.select(
                    ds.User._id,
                    ds.User.name,
                    ds.User.email,
                    ds.User.sisId,
                    ds.User.sortableName,
                    ds.User.shortName,
                    ds.User.integrationId,
                    ds.User.loginId,
                    ds.User.enrollments(courseId=id).select(
                        ds.Enrollment.state,
                        ds.Enrollment.type,
                        ds.Enrollment.section.select(
                            ds.Section._id,
                        ),
                    ),
                ),
            ),
        )

        # Lift section _id and rename it as int to id.
        # Keep only meaningful enrollments.
        def process_enrollment(enrollment):
            # TODO: how to refer to enum values using DSL?
            if enrollment[ds.Enrollment.state.name] in [
                "active",
                "inactive",
                "completed",
            ]:
                enrollment[ds.Enrollment.section.name] = int(
                    enrollment[ds.Enrollment.section.name][ds.Section._id.name]
                )
                yield enrollment

        # Keep only users with meaningful enrollments.
        # Change _id to id and convert it to int.
        def process_entry(entry):
            entry[ds.User.enrollments.name] = [
                enrollment_new
                for enrollment in entry[ds.User.enrollments.name]
                for enrollment_new in process_enrollment(enrollment)
            ]
            if entry[ds.User.enrollments.name]:
                entry["id"] = int(entry.pop(ds.User._id.name))
                yield entry

        return (
            [
                (
                    int(x[ds.Section._id.name]),
                    x[ds.Section.name.name],
                )
                for x in r[ds.Course.sectionsConnection.name][
                    ds.SectionConnection.nodes.name
                ]
            ],
            [
                entry_new
                for entry in r[ds.Course.usersConnection.name][
                    ds.UserConnection.nodes.name
                ]
                for entry_new in process_entry(entry)
            ],
        )

    def retrieve_course_group_sets(self, id):
        ds = self.ds
        f = wrap_query_execution_many(
            self.execute_query_course(id),
            [
                ds.Course.groupSetsConnection,
                ds.GroupSetConnection.nodes,
            ],
        )
        return [
            (
                int(entry[ds.GroupSet._id.name]),
                entry[ds.GroupSet.name.name],
            )
            for entry in f(
                ds.GroupSet._id,
                ds.GroupSet.name,
            )
        ]

    @property
    def group_set(self):
        return functools.partial(self.node, self.ds.GroupSet)

    def execute_query_group_set(self, id):
        return self.execute_query_node(self.ds.GroupSet, id)

    @functools.cached_property
    def groups_specify(self):
        ds = self.ds
        return ds.GroupSet.groupsConnection.select(
            ds.GroupConnection.nodes.select(
                ds.Group.name,
                ds.Group.membersConnection.select(
                    ds.GroupMembershipConnection.nodes.select(
                        ds.GroupMembership.user.select(ds.User._id),
                    ),
                ),
            ),
        )

    def groups_extract(self, x):
        ds = self.ds
        return util.general.sdict(
            (
                entry[ds.Group.name.name],
                frozenset(
                    int(member[ds.GroupMembership.user.name][ds.User._id.name])
                    for member in entry[ds.Group.membersConnection.name][
                        ds.GroupMembershipConnection.nodes.name
                    ]
                ),
            )
            for entry in x[ds.GroupSet.groupsConnection.name][
                ds.GroupConnection.nodes.name
            ]
        )

    def retrieve_group_set_groups_and_members(self, id):
        return self.groups_extract(
            self.execute_query_group_set(id)(self.groups_specify)
        )

    def retrieve_group_set_with_groups_and_members_via_name_in_course(
        self, id, group_set_name
    ):
        """
        Faster than the sequence
        - retrieve_course_group_sets
        - retrieve_group_set_groups_and_members
        if we expect no other group set in the specified course.
        """
        ds = self.ds
        f = wrap_query_execution_many(
            self.execute_query_course(id),
            [
                ds.Course.groupSetsConnection,
                ds.GroupSetConnection.nodes,
            ],
        )

        def candidates():
            for entry in f(
                ds.GroupSet._id,
                ds.GroupSet.name,
                self.groups_specify,
            ):
                if entry[ds.GroupSet.name.name] == group_set_name:
                    yield entry

        try:
            (group_set,) = candidates()
        except ValueError:
            raise ValueError(
                f"no group set named {group_set_name} in course {id}"
            ) from None

        return (
            group_set[ds.GroupSet._id.name],
            group_set[ds.GroupSet.name.name],
            self.groups_extract(group_set),
        )


class CourseUsers:
    roles_student = ["StudentEnrollment"]
    roles_teacher = ["Examiner", "TeacherEnrollment", "TaEnrollment"]

    @staticmethod
    def has_some_role(user, roles):
        return any(enrollment["role"] in roles for enrollment in user["enrollments"])

    @classmethod
    def _is_student(cls, user):
        return CourseUsers.has_some_role(user, cls.roles_student)

    @classmethod
    def _is_teacher(cls, user):
        return CourseUsers.has_some_role(user, cls.roles_teacher)

    @classmethod
    def has_short_name(cls, user):
        return user["shortName"] != user["name"]

    @classmethod
    def informal_name(cls, user):
        if CourseUsers.has_short_name(user):
            return user["shortName"]
        return user["sortableName"].split(",")[-1].strip()

    @classmethod
    def format_user(
        cls,
        user,
        primary_name=True,
        name=True,
        short_name=True,
        id=True,
        login_id=True,
        email=False,
        integration_id=False,
        sis_id=False,
    ):
        def f():
            if name and not primary_name:
                yield "name " + str(user["name"])
            if short_name and CourseUsers.has_short_name(user):
                yield "short name " + user["shortName"]
            if id and primary_name:
                yield "id " + str(user["id"])
            if login_id:
                yield "login_id " + user["login_id"]
            if email:
                yield "email " + user["email"]
            if integration_id:
                yield "integration id " + user["integrationId"]
            if sis_id:
                yield "SIS id " + user["sisId"]

        infos = list(f())
        extra = " ({})".format(", ".join(infos)) if infos else ""
        return user["name" if primary_name else "id"] + extra

    def __init__(self, data):
        (sections, users) = data

        self.section_names = dict(sections)
        self.sections_by_name = util.general.sdict(map(util.general.swap, sections))
        self.section_users = {id: list() for (id, name) in sections}

        self.users = {}
        self.users_by_name = {}
        self.users_by_sortable_name = {}
        self.users_by_integration_id = {}
        self.users_by_sis_id = {}

        for user in users:
            self.users[user["id"]] = user
            self.users_by_name[user["name"]] = user
            self.users_by_sortable_name[user["sortableName"]] = user
            self.users_by_integration_id[user["integrationId"]] = user
            self.users_by_sis_id[user["sisId"]] = user
            for enrollment in user["enrollments"]:
                self.section_users[enrollment["section"]].append(user)

    def section_id(self, id):
        return id if isinstance(id, int) else self.sections_by_name(id)

    def user(self, id):
        return self.users[id] if isinstance(id, int) else id

    def is_student(self, id):
        return self._is_student(self.user(id))

    def is_teacher(self, id):
        return self._is_teacher(self.user(id))

    def _subdict(self, pred):
        return {id: user for (id, user) in self.user_details.items() if pred(user)}

    @functools.cached_property
    def students(self):
        return self._subdict(CourseUsers.is_student)

    @functools.cached_property
    def teachers(self):
        return self._subdict(CourseUsers.is_teacher)

    def section_users(self, section):
        return self.section_users[self.section_id(section)]


class GroupSet:
    def __init__(self, data, pp_group_name: print_parse.PrintParse = None):
        self.pp_group_name = pp_group_name
        (id, name, groups) = data

        self.id = id
        self.name = name

        if self.pp_group_name is None:
            self.groups = groups
        else:
            self.groups = {
                self.pp_group_name.parse(group_name): members
                for (group_name, members) in groups.values()
            }

        self.group_by_user = {}
        for group, members in self.groups.items():
            for user_id in members:
                self.group_by_user[user_id] = group

    def str(self, group):
        if self.pp_group_name is None:
            return group
        return self.pp_group_name.print(group)

    # def create_group(self, name):
    #     logger.info(f'Creating group with name {name} in group set {self.group_set.name}')
    #     self.canvas.post(['group_categories', self.group_set.id, 'groups'], json = {
    #         'name': name,
    #         #'description': None,
    #         'join_level': 'parent_context_auto_join',
    #     })
