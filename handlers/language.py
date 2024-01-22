from pathlib import Path
import subprocess

import dominate

import general
import lab_interfaces
import live_submissions_table
import markdown
import print_parse

import handlers.general


def detect_language(path_source: Path, dir_submission: Path):
    '''
    Detect the language used by a student submission.
    Runs 'tools/detect_language.py' in the labs repository.

    Arguments:
    * path_source:
        Path to the lab source directory.
        Must contain an executable 'detect_language.py'.
    * dir_submission: path to the student submission
    '''
    process = subprocess.run([
        path_source / 'detect_language.py',
        dir_submission
    ], text = True, capture_output = True)
    language = process.stdout.strip() if process.returncode == 0 else None
    errors = process.stderr if process.stderr else None
    return (language, errors)

def pp_submission_fail():
    '''Printer parser for submissions not accepted due to language detection failure.'''
    return print_parse.regex_keyed(
        'Your submission {tag} was not accepted: language detection failure',
        {'tag': '[^: ]+'},
    )

    return print_parse.singleton('Your submission could not be accepted: language detection failure')

def format_errors(fatal, language, errors):
    def msg_fatal():
        if language is None:
            return 'We could not detect the language of your project'
        return f'Your project language {language} is not recognized'

    def msg():
        if fatal:
            return msg_fatal()
        if not errors is None:
            return 'The language detector raised some warnings'
    msg = msg()

    def blocks():
        terminator = '.' if errors is None else ':'
        if msg is not None:
            yield msg + terminator
        if not errors is None:
            yield markdown.escape_code_block(errors)

    return markdown.join_blocks(blocks())

class LanguageColumn(live_submissions_table.Column):
    sortable = True

    def format_header_cell(self, cell):
        with cell:
            dominate.util.text('Language')

    def get_value(self, group):
        submission = group.submission_current(deadline = self.config.deadline)
        language = submission.handled_result.get('language', '')
        return live_submissions_table.StandardColumnValue(language)

def wrap_column_types(column_types):
    '''
    Takes a dictionary of column classes indexed by language.
    Wraps them into a column class that dispatches according to the submission language.
    '''
    class ColumnWrapper(live_submissions_table.Column):
        '''
        A column dispatching according to the submission language.
        Header cell is taken from first language in given dictionary.
        '''
        def __init__(self, table):
            super().__init__(table)
            self.columns = {language: column_type(table) for (language, column_type) in column_types.items()}
            self.sortable = all(column.sortable for column in self.columns.values())

        def format_header_cell(self, cell):
            column = next(iter(self.columns.values()))
            return column.format_header_cell(cell)

        def get_value(self, group):
            submission = group.submission_current(deadline = self.config.deadline)
            language = submission.handled_result.get('language')
            try:
                column = self.columns[language]
            except KeyError:
                return live_submissions_table.StandardColumnValue()

            return column.get_value(group)

    return ColumnWrapper

class SubmissionHandler(handlers.general.SubmissionHandler):
    submission_failure_key = 'submission_failure'

    @property
    def response_titles(self):
        return super().response_titles | {self.submission_failure_key: pp_submission_fail()}

    def __init__(self, sub_handlers, shared_columns, show_solution = True):
        '''
        Arguments:
        * sub_handlers: dictionary mapping languages to subhandlers.
        * shared_columns:
            Iterable of strings.
            Columns in the live submission table that should be dispatched to sub handlers.
        * show_solution: whether to show the solution inthe live submission table.
        '''
        self.sub_handlers = sub_handlers
        self.shared_columns = list(shared_columns)
        self.show_solution = show_solution

    def setup(self, lab):
        super().setup(lab)
        for sub_handler in self.sub_handlers.values():
            sub_handler.setup(lab)

        def columns():
            yield ('language', LanguageColumn)
            for c in self.shared_columns:
                yield (c, wrap_column_types({
                    language: sub_handler.grading_columns[c]
                    for (language, sub_handler) in self.sub_handlers.items()
                }))

        # def choose_solution(submission):
        #     with submission.checkout_manager() as src:
        #         (language, errors) = detect_language(self.lab.config.path_source, src)
        #         if language is None:
        #             return None

        #         try:
        #             # TODO: remove hard-coding.
        #             return (language, self.lab.groups['solution'].submission_handler_data.requests_and_responses[f'submission-{language}'])
        #         except (KeyError, AttributeError):
        #             raise ValueError(f'Diff with solution: no solution found for language {language}')

        self.grading_columns = live_submissions_table.with_standard_columns(
            dict(columns()),
            with_solution = self.show_solution,
            #choose_solution = choose_solution,
        )

    def _handle_request(self, request_and_responses, src):
        # If a submission failure already exists, we are happy.
        if self.submission_failure_key in request_and_responses.responses:
            return {'accepted': False}

        # Detect language.
        (language, errors) = detect_language(self.lab.config.path_source, src)
        try:
            sub_handler = self.sub_handlers[language]
        except KeyError:
            msg = format_errors(True, language, errors)

            # Is this the official solution?
            report_msg = general.join_lines(['Could not detect language in official solution:', *msg.splitlines()])
            request_and_responses.logger.debug(report_msg)
            if request_and_responses.handler_data is None:
                raise lab_interfaces.HandlingException(report_msg)
            else:
                request_and_responses.post_response_issue(
                    response_key = self.submission_failure_key,
                    description = msg,
                )
            return {'accepted': False}

        return {'language': language} | sub_handler.handle_request(request_and_responses)

    def handle_request(self, request_and_responses):
        with request_and_responses.checkout_manager() as src:
            return self._handle_request(request_and_responses, src)

class RobogradingHandler(handlers.general.RobogradingHandler):
    def __init__(self, sub_handlers):
        '''Takes a dictionary mapping languages to subhandlers.'''
        self.sub_handlers = sub_handlers

    def setup(self, lab):
        super().setup(lab)
        for sub_handler in self.sub_handlers.values():
            sub_handler.setup(lab)

    def _handle_request(self, request_and_responses, src):
        # If a response issue already exists, we are happy.
        if self.response_key in request_and_responses.responses:
            return

        # Detect language.
        (language, errors) = detect_language(self.lab.config.path_source, src)
        try:
            sub_handler = self.sub_handlers[language]
        except KeyError:
            self.post_response(request_and_responses, format_errors(True, language, errors))
            return

        argument = request_and_responses
        if errors is not None:
            # Hack to prepend error message
            msg = format_errors(False, language, errors)

            class Wrapper:
                def post_response_issue(self, response_key, title_data = dict(), description = str()):
                    return request_and_responses.post_response_issue(
                        response_key,
                        title_data = title_data,
                        description = msg + description,
                    )

                def __getattr__(self, name):
                    return getattr(request_and_responses, name)

            argument = Wrapper()

        sub_handler.handle_request(argument)

    def handle_request(self, request_and_responses):
        with request_and_responses.checkout_manager() as src:
            return self._handle_request(request_and_responses, src)
