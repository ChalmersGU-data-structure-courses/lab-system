import abc
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import ClassVar

import dominate

import util.general


def add_class(element: dominate.util.dom_tag, class_name: str) -> None:
    """
    Add a class name to an element.
    The element should be an instance of dominate.dom_tag.
    """
    x = element.attributes.get("class", "")
    element.set_attribute("class", x + " " + class_name if x else class_name)


def format_url(text, url, new: bool = True) -> dominate.tags.a:
    """
    Creates a value of dominate.tags.a from a pair of two strings.
    The first string is the text to display, the second the URL.
    Configure it to open the link a new tab/window.
    """
    a = dominate.tags.a(text, href=url)
    if new:
        a["target"] = "_blank"
    return a


class Cell(abc.ABC):
    @abc.abstractmethod
    def value(self): ...

    def inhabited(self) -> bool:
        return True

    def sort_key(self) -> util.general.Comparable | None:
        return None


class Column[Row](abc.ABC):
    @abc.abstractmethod
    def name(self) -> str: ...

    def sortable(self) -> bool:
        return False

    @abc.abstractmethod
    def cell(self, row: Row) -> Cell: ...

    def inhabited(self, rows: Iterable[Row]) -> bool:
        for row in rows:
            if self.cell(row).inhabited():
                return True
        return False

    def ranks(self, rows: Iterable[Row]) -> dict[Row, int]:
        assert self.sortable()

        def key(row: Row) -> util.general.Comparable:
            sort_key = self.cell(row).sort_key()
            assert sort_key is not None
            return sort_key

        return util.general.canonical_keys(rows, key=key)


class HTMLCell(Cell):
    @abc.abstractmethod
    def format(self, cell: dominate.tags.td) -> None: ...


class HTMLColumn[Row](Column[Row]):
    @abc.abstractmethod
    def format_header(self, cell: dominate.tags.th) -> None: ...

    @abc.abstractmethod
    def cell(self, row: Row) -> HTMLCell: ...


class Table[Row, C: Column[Row]]:
    @abc.abstractmethod
    def columns(self) -> C: ...

    @abc.abstractmethod
    def rows(self) -> Iterable[Row]: ...


PATH_DATA: Path = Path(__file__).parent


def embed_raw(s: str) -> dominate.util.text:
    return dominate.util.raw("\n" + s)


def embed_css(s: str) -> dominate.tags.style:
    return dominate.tags.style(embed_raw(s))


def embed_js(s: str) -> dominate.tags.script:
    return dominate.tags.script(embed_raw(s))


@dataclass
class HTMLTableRenderer[Row, C: HTMLColumn[Row]]:
    columns: Iterable[C]
    rows: Iterable[Row]

    skip_empty_columns: bool = False
    skip_empty_rows: bool = False
    sort_order: list[str] | None = None
    id: str | None = None

    PATH_DATA_SORT_JS: ClassVar[Path] = PATH_DATA / "sort.js"
    PATH_DATA_SORT_CSS: ClassVar[Path] = PATH_DATA / "sort.css"

    @classmethod
    def format_head(cls, head: dominate.tags.head) -> None:
        with head:
            embed_css(cls.PATH_DATA_SORT_JS.read_text())
            embed_js(cls.PATH_DATA_SORT_CSS.read_text())

    @cached_property
    def actual_columns(self) -> list[C]:
        def gen():
            for column in self.columns:
                if not self.skip_empty_columns or column.inhabited(self.rows):
                    yield column

        return list(gen())

    @cached_property
    def actual_column_names(self) -> set[str]:
        return {column.name() for column in self.actual_columns}

    @cached_property
    def actual_sort_order(self) -> list[str] | None:
        if self.sort_order is None:
            return None

        return [
            column_name
            for column_name in self.sort_order
            if column_name in self.actual_column_names
        ]

    def row_inhabited(self, row: Row) -> bool:
        for column in self.columns:
            if column.cell(row).inhabited():
                return True
        return False

    @cached_property
    def actual_rows(self) -> list[Row]:
        def gen():
            for row in self.rows:
                if not self.skip_empty_rows or self.row_inhabited(row):
                    yield row

        return list(gen())

    @cached_property
    def column_ranks(self) -> dict[str, dict[Row, int]]:
        return {
            column.name: column.ranks()
            for column in self.actual_columns
            if column.sortable()
        }

    @cached_property
    def sorted_rows(self) -> list[Row]:
        if self.actual_sort_order is None:
            return self.actual_rows

        def key(row: Row) -> list[int]:
            return [
                self.column_ranks[column_name][row]
                for column_name in self.actual_sort_order
            ]

        return sorted(self.actual_rows, key=key)

    def td(self, row: Row, column: C) -> None:
        with dominate.tags.td() as cell:
            cell.is_pretty = False
            add_class(cell, column.name)
            if column.sortable():
                cell["data-sort-key"] = str(self.column_ranks[column.name][row])
            column.cell(row).format(cell)

    def tr(self, row: Row) -> None:
        with dominate.tags.tr():
            for column in self.actual_columns:
                self.td(row, column)

    def tbody(self) -> None:
        with dominate.tags.tbody():
            for row in self.sorted_rows:
                self.tr(row)

    def th(self, column: C) -> None:
        with dominate.tags.th() as cell:
            add_class(cell, column.name())
            if column.sortable():
                add_class(cell, "sortable")
                # want to write: is_prefix([name], actual_sort_order)
                if [column.name()] == self.actual_sort_order[:1]:
                    add_class(cell, "sortable-order-asc")
            column.format_header(cell)

    def thead(self) -> None:
        with dominate.tags.thead():
            for column in self.actual_columns:
                self.th(column)

    def render(self) -> dominate.tags.table:
        table = dominate.tags.table()
        if self.id is not None:
            table["id"] = self.id
        with table:
            self.thead()
            self.tbody()
