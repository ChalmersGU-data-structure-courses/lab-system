import dataclasses

import util.print_parse
from chalmers_pdb.new_rpcc_client import RPCC


@util.print_parse.dataclass_json
@dataclasses.dataclass(frozen=True, kw_only=True)
class Auth:
    username: str
    password: str


class PDBException(LookupError):
    pass


class Client:
    pdb: RPCC

    def __init__(self, *, url: str = "https://pdb.chalmers.se:4434", auth: Auth):
        self.pdb = RPCC(url)
        self.pdb.login(user=auth.username, password=auth.password)

    def personnummer_to_cid(self, personnummer):
        try:
            rs = self.pdb.account_dig(
                {"cid_of": {"all_pnrs": personnummer}},
                {"name": True},
            )
            (r,) = rs
            return r["name"]
        except (KeyError, ValueError) as e:
            raise PDBException(
                f"Could not obtain CID for personnummer {personnummer}: got {rs}"
            ) from e

    def details(self, cid):
        try:
            rs = self.pdb.person_dig(
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
            return rs
        except (KeyError, ValueError) as e:
            raise PDBException(
                f"Could not obtain details for CID {cid}: got {rs}"
            ) from e
