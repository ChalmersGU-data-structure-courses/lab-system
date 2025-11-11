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
        variant_name = self.lab.config.variants.name.print(submission.variant)
        return live_submissions_table.StandardColumnValue(variant_name)


def wrap_column_types(column_types):
    """
    Takes a dictionary of column classes indexed by variant.
    Wraps them into a column class that dispatches according to the submission variant.
    """

    class ColumnWrapper(live_submissions_table.Column):
        """
        A column dispatching according to the submission variant.
        Header cell is taken from first variant in given dictionary.
        """

        def __init__(self, table):
            super().__init__(table)
            self.columns = {
                variant: column_type(table)
                for (variant, column_type) in column_types.items()
            }
            self.sortable = all(column.sortable for column in self.columns.values())

        def format_header_cell(self, cell):
            column = next(iter(self.columns.values()))
            return column.format_header_cell(cell)

        def get_value(self, group):
            submission = group.submission_current(deadline=self.config.deadline)
            try:
                column = self.columns[submission.variant]
            except KeyError:
                return live_submissions_table.StandardColumnValue()

            return column.get_value(group)

    return ColumnWrapper


class SubmissionHandler(handlers.general.SubmissionHandler):
    def __init__(self, sub_handlers, shared_columns, show_solution=True):
        """
        Arguments:
        * sub_handlers: dictionary mapping variants to subhandlers.
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
            yield ("variant", LanguageColumn)
            for column in self.shared_columns:
                column_types = {
                    variant: sub_handler.grading_columns[column]
                    for (variant, sub_handler) in self.sub_handlers.items()
                }
                yield (column, wrap_column_types(column_types))

        # pylint: disable-next=attribute-defined-outside-init
        self.grading_columns = live_submissions_table.with_standard_columns(
            dict(columns()),
            with_solution=self.show_solution,
        )

    def handle_request(self, request_and_responses):
        sub_handler = self.sub_handlers[request_and_responses.variant]
        return sub_handler.handle_request(request_and_responses)


class RobogradingHandler(handlers.general.RobogradingHandler):
    def __init__(self, sub_handlers):
        """Takes a dictionary mapping variants to sub-handlers."""
        self.sub_handlers = sub_handlers

    def setup(self, lab):
        super().setup(lab)
        for sub_handler in self.sub_handlers.values():
            sub_handler.setup(lab)

    def handle_request(self, request_and_responses):
        sub_handler = self.sub_handlers[request_and_responses.variant]
        return sub_handler.handle_request(request_and_responses)
