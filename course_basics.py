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

class Tester:
    def test(src, bin, out):
        '''Test a submission (student submission or official solution).

        Arguments:
        * src (input):
            Source directory of the submission.
        * bin (input):
            Compiled directory of the submission.
            Not used for interpreted languages.
        * out (output):
            Empty directory where to create the test outputs.
        '''
        raise NotImplementedError()

    def summarize_diff_as_div(gold, test, get_diff_link):
        '''Summarize diffs as a div for use in the submission index HTML document.

        Arguments:
        * gold (input):
            Directory containing gold test outputs (generated from official solution).
        * test (input):
            Directory containing test outputs (generated from a student submission).
        * get_diff_link:
            Function taking as argument a relative path and returning a URL to GitLab that shows
            the diff between the relative path in the test directory over the gold directory.

        Returns an instance of dominate.tags.div.
        '''
        raise NotImplementedError()
