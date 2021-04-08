import datetime
import itertools
from pathlib import Path, PurePosixPath

this_dir = Path(__file__).parent

exam_id = '1WvOb_D4tQScmJUuq8LgtTbMsNCl1r7qurdCpFPsY6jY'
solution_id = '1zX1aPMw6mQd0WMZQLgw5ZmlZxOsxOgwv6lU77ehY7L8'
secret_salt = 'It is cold.'

formats = [
#    ('txt', 'Text file'),
    ('docx', 'Word document'),
    ('odt', 'OpenDocument'),
    ('pdf', 'PDF, for reading'),
]

canvas_url = 'chalmers.instructure.com'
canvas_room = 14679
canvas_extra_time_section = 'Students with extra time'
canvas_secret_salt = 'cypIjYzZbB4We0Mb'

canvas_start = datetime.datetime.fromisoformat('2021-04-07 14:00+02:00')
canvas_duration = datetime.timedelta(hours = 4)
canvas_duration_scanning = datetime.timedelta(minutes = 30)
canvas_grace_period = datetime.timedelta(minutes = 0) # Canvas doesn't have second granularity.
canvas_extra_time = 1.5
canvas_early_assignment_unlock = datetime.timedelta(minutes = 0)

canvas_instance_dir = PurePosixPath('/exam_instances')
canvas_max_points = 18

def canvas_assignment_description(resource_for_format):
    '''
    Returns an HTML string description for use in a Canvas assignment.

    link_for_format is a function returning a pair of filename and URL to the exam version for a given format extension.
    '''
    from dominate.tags import strong, a, div, p, ul, li, span, style, td, th, thead, tr
    from dominate.util import raw, text

    def f(extension, description):
        (filename, link) = resource_for_format(extension)
        return li(a(filename, href = str(link)), f' ({description})')

    return div(
        p(strong('Note'), ': This exam is individualized! Your questions differ from those of other students, but are of equal difficulty.'),
        'Download your individual exam in one of the following formats:',
        ul(*[itertools.starmap(f, formats)]),
        p('Submit your solutions via file upload, preferably as a ', strong('single PDF file'), '. If you do not know how to convert your solutions to PDF, other formats are accepted as well. Please use separate pages for each question.'),
    ).render(pretty = False)

import complexity
import sorting
import priority_queue
import hash_table
import graph

questions = [i + 1 for i in range(8)]

def question_key(q):
    return f'Q{q}'

def question_name(q):
    return f'Question {q}'

question_randomizers = [
    ('Q1', complexity.Question),
    ('Q2', sorting.QuestionQuicksort),
    ('Q2', sorting.QuestionMergeSort),
    ('Q4', priority_queue.Question),
    ('Q5', hash_table.Question),
    ('Q6', graph.QuestionDijkstra),
]

max_versions = 12
allocation_seed = 24782

allocations_file = this_dir / 'allocations.csv'
instance_dir = this_dir / 'instances'
submissions_dir = this_dir / 'submissions'
selectors_file = this_dir / 'selectors.csv'
submissions_packaged_dir = this_dir / 'packaged'
