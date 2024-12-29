import abc
import re
from collections import namedtuple

import util.general
import util.markdown
import util.print_parse


class SubmissionHandlingException(Exception):
    """
    Interface to use for all errors arising from submissions
    in the handler interfaces defined in this module.
    """

    def markdown(self):
        """
        Return a markdown-formatted error message for use within a Chalmers GitLab issue.
        This method should be overwritten in descendant classes.

        String formatting via str(exception) continues to be used in other places,
        so should also be supported.
        """
        return util.markdown.escape_code_block(str(self))


class RequestMatcher:
    """
    Interface defining a matcher for request tag names.

    Required attributes:
    * name:
        Name (string) of this kind of request.
        For example, 'submission'.
        Used for log messages.
    * protection_patterns:
        An iterable collection of wildcard pattern used to protect request tags
        on GitLab Chalmers from modification by developers (students).
        The union of these patterns must cover all strings for which the match method returns True.

    TODO once GitLab implements regex patterns for tag protection: replace interface by a single regex.
    """

    @abc.abstractmethod
    def parse(self, tag_name):
        """
        Determines whether the given tag name matches this request matcher.
        If it matches, returns an implementation-specific value different from None.
        Otherwise, returns None.

        Tags with name containing the path component separator '/' are never considered as requests.
        They are sorted out before this method is called.
        """


class RegexRequestMatcher(RequestMatcher):
    # pylint: disable=abstract-method

    def __init__(self, name, protection_patterns, regex, regex_flags=0):
        """
        Build a request matcher from a specified regex.

        Arguments:
        * name:
            Name of this kind of request.
        * protection:
            Iterable of wildcard pattern used to protect request tags from modification by students.
        * regex:
            Regex with which to match the request tag.
        * regex_flags:
            Flags to use for regex matching.
        """
        self.name = name
        self.protection_patterns = list(protection_patterns)
        self.parse = lambda tag: re.fullmatch(regex, tag, regex_flags)


CompilationRequirement = namedtuple(
    "CompilationRequirement",
    ["required", "response_title", "response_prefix"],
    defaults=[None, None],
)
CompilationRequirement.__doc__ = """
    Interface defining a compilation requirement specification.

    Required attributes:
    * required:
        Booleain indicating whether successful compilation is required for the submission to be accepted.
    * response_title:
        Printer-parser (util.print_parse.PrintParse) for a response issue notifying students of compilation failure.
        The domain of the printer-parser is a map with a single key 'tag' with value the request tag name.
        If None, then no notification is given.
    * response_prefix:
        Used only if response_title is not None.
        Markdown-formatted prefix for the content of the above response issue.
        Should include terminating linefeed.
        The Markdown-formatted exception is included afterwards.
    """

compilation_requirement_ignore = CompilationRequirement(required=False)

compilation_requirement_warn = CompilationRequirement(
    required=False,
    response_title=util.print_parse.regex_keyed(
        "Your submission {tag} does not compile",
        {"tag": "[^: ]*"},
        flags=re.IGNORECASE,
    ),
    response_prefix=util.general.join_lines(
        [
            "**Your submission does not compile.**",
            "For details, see the below error report.",
            "If you believe this is a mistake, please contact the responsible teacher."
            "",
            "Try to correct these errors and resubmit using a new tag.",
            "If done in time, we will disregard this submission attempt and grade only the new one.",
        ]
    ),
)

compilation_requirement_require = CompilationRequirement(
    required=True,
    response_title=util.print_parse.regex_keyed(
        "Your submission {tag} does not compile",
        {"tag": "[^: ]*"},
        flags=re.IGNORECASE,
    ),
    response_prefix=util.general.join_lines(
        [
            "**Your submission does not compile and can therefore not be accepted.**",
            "For details, see the below error report.",
            "If you believe this is a mistake, please contact the responsible teacher.",
        ]
    ),
)


class Compiler:
    """
    Interface defining a submission compiler.

    Required attributes:
    * requirement: value of type CompilationRequirement.
    """

    def setup(self, lab):
        """
        Setup compiler.

        Arguments:
        * lab (input):
            Lab instance.
            Can be used to retrieve lab configuration via lab.config.
            See _lab_config in gitlab_config.py.template for the available fields.
            For example, you may use lab.config.path_source to find the lab source directory.
            This may be used determine the needed compilation pathway automatically.
        """

    @abc.abstractmethod
    def compile(src, bin):
        """
        Compile a submission (problem, solution, or student submission).

        Arguments:
        * src (input):
            Source directory of the submission.
        * bin (output):
            Target compilation directory.

        A compiler should not modify the source directory.
        However, the current implementation of the java compiler writes to src and ignores bin.
        TODO: fix this.

        Compilation errors should be raised as instances of SubmissionHandlingException.
        """


class SubmissionHandler:
    """Interface defining a submission handler (after compilation)."""

    @abc.abstractmethod
    def _setup(self, lab, src, bin):
        """
        Setup submission handler.

        Arguments:
        * lab (input):
            Lab instance.
            Can be used to retrieve lab configuration via lab.config.
            See _lab_config in gitlab_config.py.template for the available fields.
            For example, you may use lab.config.path_source to find the lab source directory.
            This may be used to store testing files in a subfolder.
        * src (input):
            Source directory of the problem.
        * bin (input):
            Compiled directory of the problem.
            Not used for interpreted languages.

        Use this to perform setup operations, for example compilation of tester or robograder source code.
        How persistent this setup is up to the implementation.
        The minimum is the lifespan of the Tester object.
        This operation should be idempotent.
        """


class Tester(SubmissionHandler):
    """
    Interface defining a tester.

    Testers run the submission with predetermined input.
    The test output is recorded in output files.
    The test output of the official solution is taken as gold output.
    """

    def tag_component(self):
        """
        Path component to append to a tag to name the test output commit.

        For example, for a submission tagged group-3/submission2,
        the test commit might be tagged group-3/submission2/test.
        """
        return "test"

    @abc.abstractmethod
    def test(self, src, bin, out):
        """
        Test a submission (problem, solution, or student submission).

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
        """

    def index_div_column_title(self):
        """
        Generate column title in submission index HTML table.

        Returns an instance of dominate.tags.div.
        """
        import dominate.tags

        return dominate.tags.div("Testing")

    @abc.abstractmethod
    def index_div_column_entry(self, gold, test, get_diff_link):
        """
        Summarize test output diff for use in the submission index HTML table.

        Arguments:
        * gold (input):
            Directory containing gold test outputs (generated from official solution).
        * test (input):
            Directory containing test outputs (generated from a student submission).
        * get_diff_link:
            Function taking as argument a relative path and returning a URL to Chalmers GitLab that shows
            the diff between the relative path in the test directory over the gold directory.

        The contents of gold and test are as generated by the test method.

        Returns an instance of dominate.tags.div.
        """


class Robograder(SubmissionHandler):
    # pylint: disable=abstract-method
    """
    Interface defining a robograder.

    Required attributes:
    * response_title:
        Printer-parser (util.print_parse.PrintParse) for the robograding response issue title.
        The domain of the printer-parser is a map with a single key 'tag' with value the request tag name.

    Only implementations of the following subinterfaces are supported for now:
    * SubmissionGradingRobograder (submission-grading robograder),
    * StudentCallableRobograder (student-callable robograder).
      Made into direct child of SubmissionHandler for now.
    """

    def __init__(self):
        """Provides a default implementation of self.response_title."""
        self.response_title = (
            util.print_parse.regex_keyed(
                "Robograder: reporting for {tag}",
                {"tag": "[^: ]*"},
                flags=re.IGNORECASE,
            ),
        )

    @abc.abstractmethod
    def run(self, src, bin):
        """
        Robograde a submission (problem, solution, or student submission).

        Arguments:
        * src (input):
            Source directory of the submission.
        * bin (input):
            Compiled directory of the submission.
            Not used for interpreted languages.

        Returns a Markdown-formatted string for use in a GitLab issue.

        If the robograding cannot be generated because of a problem with the submission,
        raise an instance of SubmissionHandlingException.
        """


class SubmissionGradingRobograder(Robograder):
    # pylint: disable=abstract-method
    """
    Interface defining a submission-grading robograder.

    This is triggered by a submission.
    """

    def index_div_column_title(self):
        """
        Generate column title in submission index HTML table.

        Returns an instance of dominate.tags.div.
        """
        import dominate.tags

        return dominate.tags.div("Robograding")

    def index_div_column_entry(self, response_issue_link):
        """
        Summarize robograding for use in the submission index HTML table.

        Arguments:
        * response_issue_link: URL to Chalmers GitLab issue with the robograding.

        Returns an instance of dominate.tags.div.

        The default implementation is usually what you want.
        """


class StudentCallableRobograder(SubmissionHandler):
    """
    Interface defining a student-callable robograder.

    Required attributes:
    * request_matcher: Request matcher for student robograding requests.
    * response_title:
        Printer-parser (util.print_parse.PrintParse) for the robograding response issue title.
        The domain of the printer-parser is a map with a single key 'tag' with value the request tag name.
    """

    def __init__(self):
        """
        Provides default implementations of:
        * self.request_matcher
        * self.response_title
        """
        self.request_matcher = RegexRequestMatcher(
            "test", ["test*", "Test*"], "(?:t|T)est[^: ]*"
        )
        self.response_title = util.print_parse.regex_keyed(
            "Robograder: reporting for {tag}",
            {"tag": "[^: ]*"},
            flags=re.IGNORECASE,
        )

    @abc.abstractmethod
    def _run(self, src, bin):
        """
        Robograde a submission (problem, solution, or student submission).

        Arguments:
        * src (input):
            Source directory of the submission.
        * bin (input):
            Compiled directory of the submission.
            Not used for interpreted languages.

        Returns a Markdown-formatted string for use in a GitLab issue.

        If the robograding cannot be generated because of a problem with the submission,
        raise an instance of SubmissionHandlingException.
        """
