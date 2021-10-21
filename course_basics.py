
class CompilationRequirement(Enum):
    ignore  = auto(),
    warn    = auto(),  # Warn students via an issue if a submission does not compile.
    require = auto(),  # Do not accept submissions that do not compile.

class SubmissionHandlingException(Exception):
    # Return a markdown-formatted error message for use within a Chalmers GitLab issue.
    def markdown(self):
        None
