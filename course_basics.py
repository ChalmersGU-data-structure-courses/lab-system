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
    def setup(self, src, bin):
        '''Setup tester.

        Arguments:
        * src (input):
            Source directory of the official problem.
        * bin (input):
            Compiled directory of the official problem.
            Not used for interpreted languages.

        Use this to perform setup operations, for example compilation of the tester source code.
        How persistent this setup is up to the implementation.
        The minimum is the lifespan of the Tester object.
        This operation should be idempotent.
        '''

    def test(self, src, bin, out):
        '''Test a submission (student submission or official solution).

        Arguments:
        * src (input):
            Source directory of the submission.
        * bin (input):
            Compiled directory of the submission.
            Not used for interpreted languages.
        * out (output):
            Empty directory where to create the test outputs.

        If test outputs cannot be generated because of a problem with the submission,
        raise an instance of SubmissionHandlingException.

        This is the only function in this interface allowed to raise SubmissionHandlingException.
        '''
        raise NotImplementedError()

    def index_div_column_title(self):
        '''Generate column title in submission index HTML table.

        Returns an instance of dominate.tags.div.
        '''

    def index_div_diff_summary(self, gold, test, get_diff_link):
        '''Summarize test output diff for use in the submission index HTML table.

        Arguments:
        * gold (input):
            Directory containing gold test outputs (generated from official solution).
        * test (input):
            Directory containing test outputs (generated from a student submission).
        * get_diff_link:
            Function taking as argument a relative path and returning a URL to GitLab that shows
            the diff between the relative path in the test directory over the gold directory.

        The contents of gold and test are as generated by the test method.

        Returns an instance of dominate.tags.div.
        '''
        raise NotImplementedError()
