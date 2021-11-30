import re

import general


class Markdown:
    '''An interface for classes whose instances admit representations in Markdown.'''

    def markdown(self):
        '''
        The representation of this object in Markdown.
        Should be a marked up version of self.__str__().
        '''
        raise NotImplementedError()


def find_delimiter(s, char, least = 0):
    '''
    Find the shortest repeating sequence of 'char' that does not appear in 's'.
    This can then be used as a fencing delimiter.
    The optional argument 'least' specifies the least number of repetitions to use.
    '''
    return char * max(
        (len(match.group(0)) for match in re.finditer('{}+'.format(re.escape(char)), s)),
        default = least
    )

def escape_code_block(s, char = '`'):
    delimiter = find_delimiter(s, char, least = 3)
    return general.join_lines((delimiter, s, delimiter))
