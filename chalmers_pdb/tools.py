import dataclasses
from pathlib import Path

import util.print_parse

from .new_rpcc_client import RPCC
from .cached_client import CachedClient


@util.print_parse.dataclass_json
@dataclasses.dataclass(frozen=True, kw_only=True)
class Auth:
    username: str
    password: str


class PDBException(LookupError):
    pass


class Client:
    client: CachedClient

    def __init__(
        self,
        *,
        url: str = "https://pdb.chalmers.se:4434",
        auth: Auth,
        cache_dir: Path = Path("cache_pdb"),
    ):
        def client_constructor():
            client = RPCC(url)
            client.login(user=auth.username, password=auth.password)
            return client

        self.client = CachedClient(client_constructor, cache_dir=cache_dir)

    def personnummer_to_cid(self, personnummer):
        def get(update: bool = False):
            return self.client.account_dig(
                {"cid_of": {"all_pnrs": personnummer}},
                {"name": True},
                update=update,
            )

        for update in [False, True]:
            rs = get(update)
            try:
                (r,) = rs
                return r["name"]
            except (KeyError, ValueError) as e:
                if update is False:
                    continue

                raise PDBException(
                    f"Could not obtain CID for personnummer {personnummer}: got {rs}"
                ) from e

    def details(self, cid):
        return self.client.person_dig(
            {"cid": {"name": cid}},
            {
                "name": True,
                "nid": True,
                "gu_email": True,
                "gu_ids": True,
                "gu_pnr": True,
                "l3_email": True,
                "official_emails": True,
                "official_phones": True,
            },
        )
