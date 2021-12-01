import re

import general
import lab_interfaces
import print_parse


# ## Common default configurations for lab handlers.
#
# Can be overwritten for individual handlers.

submission_request = lab_interfaces.RegexRequestMatcher(
    ['submission*', 'Submission*'],
    '(?:s|S)ubmission[^/: ]*',
)
'''The standard request matcher for submissions.'''

review_response_key = 'grading'
'''The standard response key for a submission review.'''

def grading_response_for_outcome(outcome_name):
    '''The standard grading response printer-parser for a given outcome name printer-parser. '''
    return print_parse.compose(
        print_parse.on(general.component('outcome'), outcome_name),
        print_parse.regex_non_canonical_keyed(
            'Grading for {tag}: {outcome}',
            'grading\\s+(?:for|of)\\s+(?P<tag>[^: ]*)\\s*:\\s*(?P<outcome>[^:\\.!]*)[\\.!]*',
            flags = re.IGNORECASE,
        )
    )

testing_request = lab_interfaces.RegexRequestMatcher(
    ['test*', 'Test*'],
    '(?:t|T)est[^/: ]*',
)
'''The standard request matcher for a testing (or robograding) request.'''

robograder_response_title = print_parse.regex_keyed(
    'Robograder: reporting for {tag}',
    {'tag': '[^: ]*'},
    flags = re.IGNORECASE,
)
'''The standard robograding response printer-parser.'''
