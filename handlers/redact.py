"""
Removal of personal information from submissions
before they are sent to a model (see handlers.genai_feedback).

Students are told not to put personal information in their code.
This is a safety net on top of that, not a guarantee:
* email addresses are replaced everywhere,
* names, usernames and login ids of the members of the student project
  (from Chalmers GitLab and Canvas) are replaced everywhere,
* the values of header fields such as "Authors:" or "Lab group:"
  and group numbers such as "Group 12" are replaced.
It does not find names of other people outside header fields,
misspelled names or nicknames.

Matches are replaced by markers, so that line numbers stay the same
and the model can still tell the student where to remove something.
"""

import collections
import logging
import re
import unicodedata
from typing import Iterable


logger = logging.getLogger(__name__)

marker_email = "[email]"
marker_name = "[name]"
marker_removed = "[removed]"

pattern_email = re.compile(r"[\w.%+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}\b")

# A header field such as "Authors : ...", at the start of a line,
# possibly after a comment marker.
# The negative lookahead excludes Haskell type signatures (name :: ...).
pattern_header = re.compile(
    r"""
    ^(?P<key>
        [ \t]*(?:--+|\#+|//+|\*|\{-)?[ \t]*
        (?:
            authors?|author\(s\)|names?|students?|maintainers?|e-?mail|cid
            |(?:lab[ \t]*)?group(?:[ \t]*(?:number|nr\.?|no\.?))?
            |författare|namn|grupp(?:[ \t]*nr\.?)?
        )
        [ \t]*:(?!:)
    )
    (?P<value>[ \t]*\S.*?)[ \t]*$
    """,
    re.IGNORECASE | re.MULTILINE | re.VERBOSE,
)

pattern_group = re.compile(
    r"\b(?P<key>(?:lab[ \t]*)?(?:group|grupp)[ \t]*(?:number|nr\.?|no\.?|\#)?[ \t]*)"
    r"\d+\b",
    re.IGNORECASE,
)


def fold(s: str) -> str:
    """Remove accents: 'Åsa Öberg' becomes 'Asa Oberg'."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


def name_variants(names: Iterable[str]) -> set[str]:
    """
    The strings to replace for the given names: each name,
    its parts (first name, last name, ...) and their forms without accents.
    Parts shorter than two characters are skipped.
    """

    def variants():
        for name in names:
            name = name.strip()
            for s in [name, *re.split(r"[\s,]+", name)]:
                yield s
                yield fold(s)

    return {s for s in variants() if len(s) >= 2}


class Redactor:
    """
    Replaces personal information in texts.
    Counts what it replaced (for logging; the matches themselves are not kept).
    """

    def __init__(self, names: Iterable[str] = ()):
        def pattern(variants, flags=0):
            if not variants:
                return None
            variants = sorted(variants, key=len, reverse=True)
            return re.compile(
                r"(?<!\w)(?:" + "|".join(map(re.escape, variants)) + r")(?!\w)",
                flags,
            )

        # Short names (such as Li or Bo) are often also ordinary words
        # or identifiers, so they are only matched with the same case
        # (or in capitals).
        variants = name_variants(names)
        long = {s for s in variants if len(s) >= 4}
        short = {t for s in variants - long for t in [s, s.upper()]}
        self.patterns_names = [
            p
            for p in [pattern(long, re.IGNORECASE), pattern(short)]
            if p is not None
        ]
        self.counts = collections.Counter()

    def sub(self, kind, pattern, replacement, text):
        (text, n) = pattern.subn(replacement, text)
        self.counts[kind] += n
        return text

    def __call__(self, text: str) -> str:
        text = self.sub("email addresses", pattern_email, marker_email, text)
        for pattern in self.patterns_names:
            text = self.sub("names", pattern, marker_name, text)
        text = self.sub(
            "header fields",
            pattern_header,
            lambda m: m["key"] + " " + marker_removed,
            text,
        )
        text = self.sub(
            "group numbers",
            pattern_group,
            lambda m: m["key"] + marker_removed,
            text,
        )
        return text

    def summary(self) -> str:
        found = [f"{n} {kind}" for (kind, n) in self.counts.items() if n]
        return ", ".join(found) if found else "nothing"


def group_member_names(group) -> list[str]:
    """
    The names, usernames and login ids of the student members of a group project,
    from Chalmers GitLab and (if available) Canvas.
    Returns what could be found; failures are logged.
    """
    names = []
    try:
        members = list(group.members)
    except Exception:  # pylint: disable=broad-exception-caught
        logger.warning("Could not get the members of the project.", exc_info=True)
        return names

    course = group.lab.course
    for member in members:
        names.extend([member.name, member.username])
        try:
            canvas_user = course.canvas_user_by_gitlab_username.get(member.username)
        except Exception:  # pylint: disable=broad-exception-caught
            logger.warning("Could not look up members on Canvas.", exc_info=True)
            canvas_user = None
        if canvas_user is not None:
            for attr in ["name", "sortable_name", "short_name"]:
                value = getattr(canvas_user, attr, None)
                if value:
                    names.append(value)
            login_id = course.canvas_user_login_id(canvas_user)
            if login_id:
                names.append(login_id)
    return names
