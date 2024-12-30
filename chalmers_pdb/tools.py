from gitlab_config_personal import pdb_login

from chalmers_pdb.new_rpcc_client import RPCC


pdb = RPCC("https://pdb.chalmers.se:4434")
pdb.login(*pdb_login)


class PDBException(LookupError):
    pass


def personnummer_to_cid(personnummer):
    try:
        rs = pdb.account_dig({"cid_of": {"all_pnrs": personnummer}}, {"name": True})
        (r,) = rs
        return r["name"]
    except (KeyError, ValueError) as e:
        raise PDBException(
            f"Could not obtain CID for personnummer {personnummer}: got {rs}"
        ) from e
