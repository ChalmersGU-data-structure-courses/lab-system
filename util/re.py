"""
Tools for working with regular expressions.
This is not quite a DSL yet.
The user is responsible for ensuring correct precedence.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

import util.escaping_formatter

# Copied from standard library with whitespace removed.
#
# SPECIAL_CHARS
# closing ')', '}' and ']'
# '-' (a range in character set)
# '&', '~', (extended character set operations)
# '#' (comment) and WHITESPACE (ignored) in verbose mode
_special_chars_map = {i: "\\" + chr(i) for i in b"()[]{}?*+-|^$\\.&~#"}


def escape(pattern):
    """
    Escape special characters in a string.

    Version of standard library function that does not escape whitespace.
    """
    if isinstance(pattern, str):
        return pattern.translate(_special_chars_map)
    pattern = str(pattern, "latin1")
    return pattern.translate(_special_chars_map).encode("latin1")


def character_set(chars: Iterable[str], invert: bool = False) -> str:
    def f():
        yield "["
        if invert:
            yield "^"
        for c in chars:
            yield re.escape(c)
        yield "]"

    return str().join(f())


def capture(pattern: str, key: str | None = None) -> str:
    def parts():
        yield "("
        if key is not None:
            yield f"?P<{key}>"
        yield pattern
        yield ")"

    return str().join(parts())


def no_capture(pattern: str) -> str:
    return f"(?:{pattern})"


def sequence(patterns: Iterable[str]) -> str:
    return str().join(patterns)


def alternatives(patterns: Iterable[str]) -> str:
    return "|".join(patterns)


def many(pattern: str, at_least_one: bool = False) -> str:
    suffix = "+" if at_least_one else "*"
    return pattern + suffix


def maybe(pattern: str) -> str:
    return pattern + "?"


class RegexEscapingFormatter(util.escaping_formatter.EscapingFormatter):
    """
    A formatter for regular expressions where literal text
    spans are just that and escaped into regular expressions.
    """

    def escape_literal(self, s):
        return escape(s)


@dataclass
class RegexFormatter(RegexEscapingFormatter):
    capturing: bool = True

    def postprocess_field(self, obj, field_name):
        if self.capturing:
            key = None if field_name.isdigit() else field_name
            return capture(obj, key=key)
        return no_capture(obj)
