import logging

import ldap

import path_tools


logger = logging.getLogger(__name__)


class GUIDtoCID(path_tools.AttributeJSONCache):
    # cached attribute
    mapping: dict[str, str]

    def initialize(self):
        self.mapping = {}

    def __init__(self, cache_dir, client):
        super().__init__(
            path=cache_dir / "ldap" / "guid_to_cid",
            attribute="mapping",
            nice=True,
        )
        self.needs_save = False

        self.client = client

    def __get_item__(self, guid):
        return self.mapping[guid]

    def set_entry(self, guid, cid, _missing=object()):
        cid_prev = self.mapping.get(guid, _missing)
        updated = cid != cid_prev
        if updated:
            self.mapping[guid] = cid
        return updated

    def ensure_entries(self, canvas_users):
        def process(self, canvas_user):
            (guid, canvas_name, canvas_name_sortable) = canvas_user
            updated = not guid in self.mapping
            if updated:
                self.mapping[guid] = self.do_lookup(
                    guid, canvas_name, canvas_name_sortable
                )
            return updated

        with self.updating:
            updated = self.time is None or any(map(process, canvas_users))
        if updated:
            self.save()

    def do_lookup(self, guid, canvas_name, canvas_name_sortable=None):
        """Could use improved heuristic."""
        results = self.client.search_ext_s(
            "ou=people,dc=chalmers,dc=se",
            ldap.SCOPE_ONELEVEL,
            ldap.filter.filter_format("(cn=%s)", [canvas_name]),
            attrlist=["uid", "sn", "givenName"],
            sizelimit=5,
        )
        cids = [result[1]["uid"][0].decode("ascii") for result in results]
        try:
            (cid,) = cids
            return cid
        except ValueError:
            logging.warning(
                f"Could not resolve GU ID {guid} with Canvas name {canvas_name}."
            )
            if not results:
                logging.warning("No matches with that name on Chalmers LDAP.")
            else:
                logging.warning(
                    f'Multiple matches name on Chalmers LDAP: {", ".join(cids)}'
                )
            return None
