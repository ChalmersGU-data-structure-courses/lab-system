
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
    '''

    def setup(self, lab):
        '''
        Setup this testing handler.
        Called by the Lab class before any other method is called.
        '''
        self.lab = lab

    def get_request_matcher(self):
        '''
        Returns the request matcher to be used for this type of request.

        The default implementation returns the attribute 'request_matcher'.
        It is then up to the class implementation to fill in this attribute.
        '''
        return self.request_matcher

    def get_response_titles(self):
        '''
        Return a dictionary whose values are printer-parsers for issue titles.
        Its keys should be string-convertible.
        The request handler may only produce response issues by calling
        a method in the lab instance that produces it via a key
        to the dictionary of issue title printer-parsers.

        The domains of the printer-parsers are string-valued dictionaries
        that must include the key 'tag' for the name of the associated request.

        The default implementation returns the attribute 'response_titles'.
        It is then up to the class implementation to fill in this attribute.
        '''
        return self.response_titles

    def handle_request(self, tag_name):
        '''
        Handle a testing request.
        This may call the lab class for the following:
        * Work with the git repository for any tag under tag_name.
          This may read tags and create new tagged commits.
          Use methods (TODO) of the lab instance to work with this as a cache.
        * Make calls to response issue posting methods (TODO) of the lab instance.
        '''
        raise NotImplementedError()

class SubmissionHandler(RequestHandler):
    '''
    This interface specifies a request handler for handling submissions.
    The only extra bit is a specification of the grading columns in the live submissions table.
    '''

    def get_grading_columns(self):
        '''
        Customized columns for the live submissions table.
        Return an iterable of instances of live_submissions_table.Column.

        The default implementation returns the attribute 'grading_columns'.
        It is then up to the class implementation to fill in this attribute.
        '''
        return self.grading_columns
