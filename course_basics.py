from enum import Enum, auto

import markdown

class CompilationRequirement(Enum):
    ignore  = auto()
    warn    = auto()  # Warn students via an issue if a submission does not compile.
    require = auto()  # Do not accept submissions that do not compile.

class SubmissionHandlingException(Exception):
    # Return a markdown-formatted error message for use within a Chalmers GitLab issue.
    # This method should be overwritten in descendant classes.
    def markdown(self):
        return markdown.escape_code_block(str(self))
