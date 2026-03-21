"""
Tools for working with regular expressions.
This is not quite a DSL yet.
The user is responsible for ensuring correct precedence.
"""

from collections.abc import Iterable
import re


def character_set(chars: Iterable[str], invert: bool = False) -> str:
    def f():
        yield "["
        if invert:
            yield "^"
        for c in chars:
            yield re.escape(c)
        yield "]"

    return str().join(f())


def no_capture(pattern: str) -> str:
    return f"(?:{pattern})"


def sequence(patterns: Iterable[str]) -> str:
    return str().join(patterns)


def alternatives(patterns: Iterable[str]) -> str:
    return "|".join(patterns)


def many(pattern: str, at_least_one: bool = False) -> str:
    suffix = "+" if at_least_one else "*"
    return pattern + suffix
