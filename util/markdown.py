from collections.abc import Iterable
import dataclasses
import enum
import re
from typing import Sequence

import more_itertools

import util.general


class Markdown:
    """An interface for classes whose instances admit representations in Markdown."""

    def markdown(self):
        """
        The representation of this object in Markdown.
        Should be a marked up version of self.__str__().
        """
        raise NotImplementedError()


def find_delimiter(s, char, least=0):
    """
    Find the shortest repeating sequence of 'char' that does not appear in 's'.
    This can then be used as a fencing delimiter.
    The optional argument 'least' specifies the least number of repetitions to use.
    """

    def values():
        yield least
        for match in re.finditer(re.escape(char) + "+", s):
            yield len(match.group(0)) + 1

    return char * max(values())


def heading(s, level=1):
    return util.general.join_lines(["#" * level + " " + s])


def escape_code_block(s, char="`"):
    delimiter = find_delimiter(s, char, least=3)
    return util.general.join_lines([delimiter, s.rstrip(), delimiter])


def join_blocks(blocks: Iterable[str]):
    """All lines in each block must be terminated by a newline character."""
    return "".join(more_itertools.intersperse("\n", blocks))


def quote(block: str):
    return util.general.join_lines("> " + line for line in block.splitlines())


def quote_blocks(blocks: Iterable[str]):
    """All lines in each block must be terminated by a newline character."""
    return quote(join_blocks(blocks))


# TODO
def escape(s: str) -> str:
    return s


def link(title, url):
    return f"[{title}]({url})"


class Alignment(enum.Enum):
    LEFT = enum.auto()
    RIGHT = enum.auto()
    CENTER = enum.auto()


@dataclasses.dataclass
class ColumnSpec:
    title: str
    align: Alignment | None = None


def table(column_specs: Iterable[ColumnSpec], rows: Iterable[Sequence[str]]):
    """Doesn't do any escaping."""
    column_specs = list(column_specs)
    rows = list(rows)

    lengths = [
        max(len(str(x)) for x in [column_spec.title, *(row[i] for row in rows)])
        for (i, column_spec) in enumerate(column_specs)
    ]

    def wrap_with_space(s):
        return " " + s + " "

    def wrap_with_alignment(s, alignment):
        if alignment is Alignment.RIGHT:
            return "-" + s + ":"
        if alignment is Alignment.CENTER:
            return ":" + s + ":"
        return "-" + s + "-"

    def join_with_pipe(entries):
        return "".join(
            util.general.intercalate(entries, middle="|", start="|", end="|")
        )

    def format_row(entries):
        def f():
            for i, entry in enumerate(entries):
                column_spec = column_specs[i]
                just = str.rjust if column_spec.align is Alignment.RIGHT else str.ljust
                yield wrap_with_space(
                    just("" if entry is None else str(entry), lengths[i])
                )

        return join_with_pipe(f())

    def lines():
        yield format_row(column_spec.title for column_spec in column_specs)
        yield join_with_pipe(
            wrap_with_alignment("-" * lengths[i], column_spec.align)
            for (i, column_spec) in enumerate(column_specs)
        )
        for row in rows:
            yield format_row(row)

    return util.general.join_lines(lines())
