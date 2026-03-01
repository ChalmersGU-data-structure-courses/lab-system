from collections.abc import Iterable
import contextlib
import dataclasses
import enum
import logging
from pathlib import Path
import re

import chalmers_pdb.tools
import chalmers_pdb.cached_client
import gitlab_.graphql
import graphql_.client
from graphql_.tools import lift, over_list, query, tupling
import lab_interfaces
import util.general
import util.print_parse

logger = logging.getLogger(__name__)

logging.basicConfig()
logging.getLogger().setLevel(logging.WARN)


@dataclasses.dataclass(frozen=True)
class User:
    id: int
    username: str
    created_at: str
    last_activity_on: str  # rarely None
    human: bool  # some bot users
    name: str


def retrieve_users(client) -> Iterable[User]:
    ds = client.ds
    fields = [
        client.user_core_id,
        ds.UserCore.username,
        ds.UserCore.created_at,
        ds.UserCore.last_activity_on,
        ds.UserCore.human,
        ds.UserCore.name,
    ]

    def callback(cursor=None):
        return client.execute(
            lift(query)(
                tupling(ds.Query.users(sort="CREATED_ASC", after=cursor).select)(
                    over_list(tupling(ds.UserCoreConnection.nodes.select)(*fields)),
                    lift(ds.UserCoreConnection.pageInfo.select)(ds.PageInfo.endCursor),
                ),
            )
        )

    for x in graphql_.client.retrieve_all_from_cursor(callback):
        yield User(*x)


class UserType(enum.Enum):
    BOT = object()
    EXTERNAL = object()


UNKNOWN_USERNAMES = {
    "thomas.king",
    "kuebra.seyhan",
    "manuel.pitz",
    "martin.ronnback",
    "jakob.angeby",
    "mathias.hoppe",
    "m.bentvelzen",
    "per.wallentin",
    "bo.bijlenga",
    "ninos.poli",
    "loic.ho-von",
    "luca.caltagirone",
    "jonas.holmborn",
    "prathisha.reddy",
    "tomas.u.jonsson",
    "arvind.balachandran",
}

CLOUD_ADMINS = {
    "cloudadmin.thokut": "thokut",
    "cloudadmin.willeny": "willeny",
}


class CannotConfirm(Exception):
    pass


def confirm_bot(user):
    if not user.human or user.username in ["lab-system", "research_paper_bot"]:
        return UserType.BOT
    raise CannotConfirm(f"Not obviously a bot: {user.username}")


def confirm_external_domain(username):
    try:
        [_, domain] = username.split("_")
    except ValueError:
        raise CannotConfirm(
            f"{username} does not have unique '_' (as a stand-in for '@')"
        ) from None
    if not "." in domain:
        raise CannotConfirm(f"Cannot confirm domain {domain}")
    return UserType.EXTERNAL


def confirm_external_workplace(username):
    try:
        [_, workplace] = username.split("-")
    except ValueError:
        raise CannotConfirm(f"{username} does not have unique '-'") from None
    if not workplace in ["umu", "uni-mainz"]:
        raise CannotConfirm(f"Cannot confirm workplace {workplace}")
    return UserType.EXTERNAL


def confirm_cid(pdb_client, cid):
    if not re.fullmatch("([_a-z])[-a-z0-9_]{0,15}", cid):
        raise CannotConfirm(f"{cid} does not conform to regular expression for CIDs")

    results = pdb_cached_client.person_dig(
        {"cid": {"name": cid}},
        {"cid": {"name": True}},
    )
    try:
        util.general.from_singleton(results)
        return cid
    except util.general.UniquenessErrorNone:
        return CannotConfirm(f"{cid} not found in PDB")


def confirm_email(pdb_client, user):
    results = pdb_cached_client.person_dig(
        {"official_emails_regexp_nocase": f"^{re.escape(user)}@"},
        {"cid": {"name": True}},
    )
    try:
        result = util.general.from_singleton(results)
    except util.general.UniquenessErrorNone:
        pass
    else:
        return result["cid"][0]["name"]
    raise CannotConfirm(f"{user}@host not found in PDB")


def resolve(user):
    with contextlib.suppress(CannotConfirm):
        return confirm_bot(user)

    with contextlib.suppress(CannotConfirm):
        return confirm_external_domain(user.username)

    with contextlib.suppress(CannotConfirm):
        return confirm_external_workplace(user.username)

    with contextlib.suppress(CannotConfirm):
        return confirm_cid(pdb_client, user.username)

    try:
        cid = util.general.remove_suffix(user.username, "1")
    except ValueError:
        pass
    else:
        with contextlib.suppress(CannotConfirm):
            return confirm_cid(pdb_client, cid)

    with contextlib.suppress(CannotConfirm):
        return confirm_email(pdb_client, user.username)

    return None


def process():
    print(f"trying to resolve {len(unresolved)} users")
    for user in list(unresolved):
        print(f"Resolving {user.username}...")
        result = resolve(user)
        if result is not None:
            unresolved.remove(user)
            resolved[user.username] = result
    print(f"there are {len(unresolved)} unresolved users remaining")


def print_unresolved():
    for user in unresolved:
        print(user.username, user.name, user.created_at, user.last_activity_on)


def external():
    for user in users:
        if user.human:
            if "_" in user.username:
                [user, domain, *extra] = user.username.split("_")
                print(f"{user}@{domain}")
                if extra:
                    print(f"  EXTRA: {extra}")


auth = lab_interfaces.CourseAuth.from_secrets(Path("secrets.toml"))

client = gitlab_.graphql.Client(
    domain="git.chalmers.se",
    token=auth.gitlab_private_token,
    schema_full=True,
)

pdb_client = chalmers_pdb.new_rpcc_client.RPCC(url="https://pdb.chalmers.se:4434")
pdb_client.login(user=auth.pdb.username, password=auth.pdb.password)

pdb_cached_client = chalmers_pdb.cached_client.CachedClient(
    pdb_client,
    Path("cache_pdb"),
)


users: list[User] = list(retrieve_users(client))

unresolved: set[User] = set(users)

# Map from username to CID or UserType.
resolved: dict[str, str | UserType] = {}

process()

assert {x.username for x in unresolved} == UNKNOWN_USERNAMES | CLOUD_ADMINS.keys()
print("all usernames have been classified or marked separately")
