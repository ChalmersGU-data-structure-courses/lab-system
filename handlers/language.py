import dominate

import handlers.general
import live_submissions_table


class LanguageColumn(live_submissions_table.Column):
    sortable = True

    def format_header_cell(self, cell):
        with cell:
            dominate.util.text("Language")

    def get_value(self, group):
        submission = group.submission_current(deadline=self.config.deadline)
        language = submission.handled_result.get("language", "")
        return live_submissions_table.StandardColumnValue(language)


def wrap_column_types(column_types):
    """
    Takes a dictionary of column classes indexed by language.
    Wraps them into a column class that dispatches according to the submission language.
    """

    class ColumnWrapper(live_submissions_table.Column):
        """
        A column dispatching according to the submission language.
        Header cell is taken from first language in given dictionary.
        """

        def __init__(self, table):
            super().__init__(table)
            self.columns = {
                language: column_type(table)
                for (language, column_type) in column_types.items()
            }
            self.sortable = all(column.sortable for column in self.columns.values())

        def format_header_cell(self, cell):
            column = next(iter(self.columns.values()))
            return column.format_header_cell(cell)

        def get_value(self, group):
            submission = group.submission_current(deadline=self.config.deadline)
            language = submission.handled_result.get("language")
            try:
                column = self.columns[language]
            except KeyError:
                return live_submissions_table.StandardColumnValue()

            return column.get_value(group)

    return ColumnWrapper


class SubmissionHandler(handlers.general.SubmissionHandler):
    def __init__(self, sub_handlers, shared_columns, show_solution=True):
        """
        Arguments:
        * sub_handlers: dictionary mapping languages to subhandlers.
        * shared_columns:
            Iterable of strings.
            Columns in the live submission table that should be dispatched to sub handlers.
        * show_solution: whether to show the solution inthe live submission table.
        """
        self.sub_handlers = sub_handlers
        self.shared_columns = list(shared_columns)
        self.show_solution = show_solution

    def setup(self, lab):
        super().setup(lab)
        for sub_handler in self.sub_handlers.values():
            sub_handler.setup(lab)

        def columns():
            yield ("language", LanguageColumn)
            for column in self.shared_columns:
                column_types = {
                    language: sub_handler.grading_columns[column]
                    for (language, sub_handler) in self.sub_handlers.items()
                }
                yield (column, wrap_column_types(column_types))

        self.grading_columns = live_submissions_table.with_standard_columns(
            dict(columns()),
            with_solution=self.show_solution,
        )

    def handle_request(self, request_and_responses):
        sub_handler = self.sub_handlers[request_and_responses.language]
        return sub_handler.handle_request(request_and_responses)


class RobogradingHandler(handlers.general.RobogradingHandler):
    def __init__(self, sub_handlers):
        """Takes a dictionary mapping languages to sub-handlers."""
        self.sub_handlers = sub_handlers

    def setup(self, lab):
        super().setup(lab)
        for sub_handler in self.sub_handlers.values():
            sub_handler.setup(lab)

    def handle_request(self, request_and_responses):
        sub_handler = self.sub_handlers[request_and_responses.language]
        return sub_handler.handle_request(request_and_responses)
