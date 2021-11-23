import re

class RequestMatcher:
    '''
    Interface defining a matcher for request tag names.

    Required attributes:
    * protection_patterns:
        An iterable collection of wildcard pattern used to protect request tags
        on GitLab Chalmers from modification by developers (students).
        The union of these patterns must cover all strings for which the match method returns True.

    TODO once GitLab implements regex patterns for tag protection: replace interface by a single regex.
    '''

    def parse(self, tag_name):
        '''
        Determines whether the given tag name matches this request matcher.
        If it matches, returns an implementation-specific value different from None.
        Otherwise, returns None.

        Tags with name containing the path component separator '/' are never considered as requests.
        They are sorted out before this method is called.
        '''
        raise NotImplementedError()

class RegexRequestMatcher(RequestMatcher):
    def __init__(self, protection_patterns, regex, regex_flags = 0):
        '''
        Build a request matcher from a specified regex.

        Arguments:
        * protection:
            Iterable of wildcard pattern used to protect request tags
            from modification by students.
        * regex:
            Regex with which to match the request tag.
        * regex_flags:
            Flags to use for regex matching.
        '''
        self.protection_patterns = list(protection_patterns)
        self.parse = lambda tag: re.fullmatch(regex, tag, regex_flags)

class RequestHandler:
    '''
    This interface specifies a request handler.
    A request handler matches some requests (tags in lab group repository)
    as specified by its associated request matcher.
    For any unhandled request, the lab instance calls
    the request handler via the 'handle_request' method.
    The request handler must then handle the request
    in some implementation-defined manner.
    For example, it may post response issues for the lab instance.

    Required attributes:
    * name:
        Name (string) of this kind of request.
        For example, 'submission'.
        Used for log messages.
    * request_matcher:
        The request matcher to be used for this type of request.
    * response_titles:
        Return a dictionary whose values are printer-parsers for issue titles.
        Its keys should be string-convertible.
        The request handler may only produce response issues by calling
        a method in the lab instance that produces it via a key
        to the dictionary of issue title printer-parsers.

        The domains of the printer-parsers are string-valued dictionaries
        that must include the key 'tag' for the name of the associated request.
    '''

    def setup(self, lab):
        '''
        Setup this testing handler.
        Called by the Lab class before any other method is called.
        '''
        self.lab = lab

    def handle_request(self, group_project, request_name):
        '''
        Handle a testing request.
        This may call the lab class for the following:
        * Work with the git repository for any tag under tag_name.
          This may read tags and create new tagged commits.
          Use methods (TODO) of the lab instance to work with this as a cache.
        * Make calls to response issue posting methods (TODO) of the lab instance.

        After calling this method, the lab instance will create
        a tag <group-id>/<tag_name>/handled to mark the request as handled.
        This method may return a JSON-dumpable value.
        If so, its dump will be stored as the message of the above tag.
        '''
        raise NotImplementedError()

class SubmissionHandler(RequestHandler):
    '''
    This interface specifies a request handler for handling submissions.
    The only extra bit is a specification of the grading columns in the live submissions table.

    Required attributes:
    * grading_columns
        Customized columns for the live submissions table.
        A collection of instances of live_submissions_table.Column.
    '''
