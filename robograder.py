import general
import markdown

class RobograderException(Exception):
    def markdown(self):
        return None

class FileConflict(RobograderException):
    def __init__(self, file):
        self.file = file

    def markdown(self):
        return general.join_lines([
            'I could not robograde your submission because the compiled file',
        ]) + markdown.escape_code_block(self.file) + general.join_lines([
            'conflicts with files I use for testing.'
        ])

class ExecutionError(RobograderException):
    def __init__(self, errors):
        self.errors = errors

    def markdown(self):
        return general.join_lines([
            'Oops, you broke the robograder!',
            '',
            'I encountered a problem while testing your submission.',
            'This could be a problem with myself (a robo-bug) or with your code (unexpected changes to class or methods signatures).',
            'In the latter case, you might elucidate the cause from the below error message.',
            'In the former case, please tell me designers!',
        ]) + markdown.escape_code_block(self.errors)
