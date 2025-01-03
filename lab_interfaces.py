import abc
import re

import util.markdown


class RequestMatcher:
    """
    Interface defining a matcher for request tag names.

    Required attributes:
    * protection_patterns:
        An iterable collection of wildcard pattern used to protect request tags
        on GitLab Chalmers from modification by developers (students).
        The union of these patterns must cover all strings for which the match method returns True.

    TODO once GitLab implements regex patterns for tag protection: replace interface by a single regex.
    """

    @abc.abstractmethod
    def parse(self, tag):
        """
        Determines whether the given tag name matches this request matcher.
        If it matches, returns an implementation-specific value different from None.
        Otherwise, returns None.

        Tags with name containing the path component separator '/' are never considered as requests.
        They are sorted out before this method is called.
        """


class RegexRequestMatcher(RequestMatcher):
    def __init__(self, protection_patterns, regex, regex_flags=0):
        """
        Build a request matcher from a specified regex.

        Arguments:
        * protection:
            Iterable of wildcard pattern used to protect request tags
            from modification by students.
        * regex:
            Regex with which to match the request tag.
        * regex_flags:
            Flags to use for regex matching.
        """
        self.protection_patterns = list(protection_patterns)
        self._regex = regex
        self._regex_flags = regex_flags

    def parse(self, tag):
        return re.fullmatch(self._regex, tag, self._regex_flags)


class RequestHandler:
    """
    This interface specifies a request handler.
    A request handler matches some requests (tags in lab group repository)
    as specified by its associated request matcher.
    For any unhandled request, the lab instance calls
    the request handler via the 'handle_request' method.
    The request handler must then handle the request
    in some implementation-defined manner.
    For example, it may post response issues for the lab instance.

    Required attributes:
    * request_matcher:
        The request matcher to be used for this type of request.
    * response_titles:
        Return a dictionary whose values are printer-parsers for issue titles.
        Its values should be string-convertible.
        The request handler may only produce response issues by calling
        a method in the lab instance that produces it via a key
        to the dictionary of issue title printer-parsers.
        If this attribute is provided dynamically, its keys must be stable.
        The attribute must be stable after setup has been called.

        The domains of the printer-parsers are string-valued dictionaries
        that must include the key 'tag' for the name of the associated request.

    Required for multi-language labs:
    * language_failure_key:
        Key in self.response_titles identifying language detection failure issues.
        If there is not a unique problem commit ancestor, the lab system rejects the submission with such an issue.
        This happens before the request handler handles the request.

        Its associated issue-title printer-parser must have printer-parser with domain ditionaries containing no extra keys.

        If this attribute does not exist or is None, it is up to the request handler to deal with language detection failure.
        For this, use the list request_and_responses.languages of detected language candidates.
    """

    def setup(self, lab):
        """
        Setup this testing handler.
        Called by the Lab class before any other method is called.
        """
        # TODO: design better architecture that avoids these late assignments.
        # pylint: disable-next=attribute-defined-outside-init
        self.lab = lab

    @abc.abstractmethod
    def handle_request(self, request_and_responses):
        """
        Handle a testing request.
        Takes an instance of group_project.request_and_responses as argument.

        This method may call request_and_responses for the following:
        * Work with the git repository for any tag under tag_name.
          This may read tags and create new tagged commits.
          Use methods (TODO) of the lab instance to work with this as a cache.
        * Make calls to response issue posting methods (TODO) of the lab instance.

        After calling this method, the lab instance will create
        a tag <group-id>/<tag_name>/handled to mark the request as handled.
        This method may return a JSON-dumpable value.
        If so, its dump will be stored as the message of the above tag.
        """


class SubmissionHandler(RequestHandler):
    # pylint: disable=abstract-method
    """
    This interface specifies a request handler for handling submissions.

    Required attributes (in addition to the ones of RequestHandler):

    * review_response_key
        Key in self.response_titles identifying submissions review issues (produced by graders).
        These are also known as "grading issues".

        Submission review issues must have printer-parser
        with domain a dictionary containing a key 'outcome'.
        The type of its value is specific to the submission handler.
        It must be JSON-encodable (combination of dict, list, and primitive types).

        To not set up review issues, set review_response_key to None.
        In that case, the only possible grading pathway
        is via the result of the submission handler.

    * grading_columns
        Customized columns for the live submissions table.
        A collection of instances of live_submissions_table.Column.

    The handle_request method must returns a JSON-encodable dictionary.
    This dictionary must have the following key:

    - 'accepted':
        Boolean indicating if the submission system
        should accept or reject the submission.

        Note that this is different from passing and failing.
        A rejected submission does not count as an actual submission.
        This is important if only a certain number of submissions are allowed,
        or a valid submission is required before a certain date.

    - 'review_needed' (if 'accepted' is True):
        Boolean indicating if the handler wants a grader to
        take a look at the submission and decide its outcome.

    - 'outcome_response_key' (if 'accepted' is True and 'review_needed' is False):
        Response key of the response issue posted by the submission handler
        that notifies the students of their submission outcome.

        The associated issue title printer-parser needs to have domain
        a dictionary with an 'outcome' entry as for a submission review issue.
        Existing review issues always override the submission outcome
        of the submission handler, even if 'review_needed' is not True.
    """


class HandlingException(Exception, util.markdown.Markdown):
    # pylint: disable=abstract-method
    """
    Raised for errors caused by a problems with a submission.
    Should be reportable in issues in student repositories.
    """
