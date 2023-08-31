from pathlib import Path
import subprocess

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
        {'tag': '\\s+'},
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
                    return request_and_responses.__getattr__(name)

            argument = Wrapper()

        sub_handler.handle_request(argument)

    def handle_request(self, request_and_responses):
        with request_and_responses.checkout_manager() as src:
            return self._handle_request(request_and_responses, src)
