import re
from typing import Iterable

import more_itertools

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
    return char * max([
        least,
        *(len(match.group(0)) + 1 for match in re.finditer('{}+'.format(re.escape(char)), s))
    ])

def escape_code_block(s, char = '`'):
    delimiter = find_delimiter(s, char, least = 3)
    return general.join_lines([delimiter, s.rstrip(), delimiter])

def join_blocks(blocks: Iterable[str]):
    '''All lines in each block must be terminated by a newline character.'''
    return ''.join(more_itertools.intersperse('\n', blocks))

# TODO
def escape(s: str) -> str:
    return s
