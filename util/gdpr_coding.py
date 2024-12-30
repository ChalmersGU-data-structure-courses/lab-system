import dataclasses
import functools
import itertools
import json
import logging
from typing import Any, Callable

import atomicwrites

import util.print_parse


logger = logging.getLogger(__name__)


@dataclasses.dataclass
class GDPRCoding:
    # Printer-parser that encodes identifiers for use in non-GDPR-cleared documents.
    # The most common example is Google Sheets.
    identifier: util.print_parse.PrintParse

    # Sort key to use for the encoded identifiers.
    sort_key: Callable[Any, Any] = lambda x: x


class NameCoding:
    encode: dict[Any, str]
    decode: dict[str, Any]

    def __init__(self, path, first_and_last_name):
        """
        Arguments:
        * path:
              Persistent location to use to store this name coding.
              This is needed to reconstruct the mapping over program starts.
        * first_and_last_name:
              Function from ids to pairs of strings.
              Returns the pair of the first name and last name of the given id.

        The coding will attempt to use name initials.
        """
        self.path = path
        self.first_and_last_name = first_and_last_name

        self._load()

    @functools.cached_property
    def gdpr_coding(self):
        return GDPRCoding(
            identifier=util.print_parse.PrintParse(
                print=self.encode.__getitem__,
                parse=self.decode.__getitem__,
            ),
            sort_key=lambda s: (s[1], s[0], 0 if len(s) == 2 else int(s[2:])),
        )

    def _load(self):
        try:
            with self.path.open() as file:
                self.encode = json.load(file)
        except FileNotFoundError:
            self.encode = {}

        self.decode = {code: id for (id, code) in self.encode.items()}

    def _save(self):
        with atomicwrites.atomic_write(self.path, overwrite=True) as file:
            json.dump(self.encode, file, ensure_ascii=False, indent=4)

    def _add(self, id):
        (name_first, name_last) = self.first_and_last_name(id)

        def codings():
            initials = name_first[0].upper() + name_last[0].upper()
            yield initials
            for i in itertools.count(1):
                yield initials + str(i)

        for coding in codings():
            if not coding in self.decode:
                logger.debug(f"Adding coding {coding} for {id}")
                self.encode[id] = coding
                self.decode[coding] = id
                break

    def add_ids(self, ids):
        ids = list(ids)
        logger.debug(f"Ensuring codings for: {ids}")

        def key(id):
            (name_first, name_last) = self.first_and_last_name(id)
            return (name_last, name_first)

        for id in sorted(ids, key=key):
            if not id in self.encode:
                self._add(id)

        self._save()
