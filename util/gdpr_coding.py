from collections.abc import Iterable
import dataclasses
import functools
import itertools
import json
import logging
from pathlib import Path
from typing import Callable

import atomicwrites

import util.general
import util.print_parse


logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class GDPRCoding[Id]:
    # Printer-parser that encodes identifiers for use in non-GDPR-cleared documents.
    # The most common example is Google Sheets.
    identifier: util.print_parse.PrinterParser[Id, int | str]

    # Sort key to use for the non-encoded identifiers.
    # Defaults to the identity (only makes sense if the group id is comparable).
    sort_key: Callable[[Id], util.general.Comparable] = util.general.identity


class NameCoding[Id]:
    path: Path
    first_and_last_name: Callable[[Id], tuple[str, str]]
    sort_by_first_name: bool

    encode: dict[Id, str]
    decode: dict[str, Id]

    def __init__(
        self,
        path: Path,
        first_and_last_name: Callable[[Id], tuple[str, str]],
        sort_by_first_name: bool = False,
    ):
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
        self.sort_by_first_name = sort_by_first_name

        self._load()

    def sort_key(self, id: Id) -> util.general.Comparable:
        s = self.encode[id]
        n = 0 if len(s) == 2 else int(s[2:])
        match self.sort_by_first_name:
            case False:
                return (s[1], s[0], n)
            case True:
                return (s[0], s[1], n)

    @functools.cached_property
    def gdpr_coding(self):
        return GDPRCoding(
            identifier=util.print_parse.PrintParse(
                print=self.encode.__getitem__,
                parse=self.decode.__getitem__,
            ),
            sort_key=self.sort_key,
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

    def _add(self, id: Id):
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

    def add_ids(self, ids: Iterable[Id]):
        ids = list(ids)
        logger.debug(f"Ensuring codings for: {ids}")

        def key(id):
            (name_first, name_last) = self.first_and_last_name(id)
            return (name_last, name_first)

        for id in sorted(ids, key=key):
            if not id in self.encode:
                self._add(id)

        self._save()
