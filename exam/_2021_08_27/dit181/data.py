import datetime
import itertools
from pathlib import Path, PurePosixPath
import re

import general

this_dir = Path(__file__).parent

exam_id = '1rxsF75uardtvgERWVEjBCckFw0Qh7GAm3mBnaegOodc'
solution_id = '1gYMujdbUcIoODHD7IyIJ0FzmsXFhSgpWR3Ah43NSMUU'
secret_salt = 'Rainy night'

formats = [
#    ('txt', 'Text file'),
    ('docx', 'Word document'),
    ('odt', 'OpenDocument'),
    ('pdf', 'PDF, for reading'),
]

canvas_url = 'canvas.gu.se'
canvas_room = 51458
canvas_extra_time_section = 'Students with extra time'
canvas_secret_salt = '1EZB2k9p0KUAfh2b'

canvas_start = datetime.datetime.fromisoformat('2021-08-27 14:00+02:00')
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

questions = [i + 1 for i in range(8)]

def question_key(q):
    return f'Q{q}'

def question_name(q):
    return f'Question {q}'

def question_name_parse(q):
    m = re.fullmatch('Question (\\d+)', s)
    return int(m.group(1)) if m else None

from .. import question2
from .. import question3
from .. import question4
from .. import question5
from .. import question6

question_randomizers = {
    2: (question2.Generator,),
    3: (question3.Generator(),),
    4: (question4.Generator,),
    5: (question5.Generator,),
    6: (question6.Generator,),
}

max_versions = 5
allocation_seed = 37844

allocations_file = this_dir / 'allocations.csv'
instance_dir = this_dir / 'instances'
submissions_dir = this_dir / 'submissions'
selectors_file = this_dir / 'selectors.csv'
submissions_packaged_dir = this_dir / 'packaged'

### Checklist

checklist = this_dir / 'checklist.csv'

checklist_name = 'Efternamn_Fornamn'
checklist_time = 'Inlämningstid'

### Configuration of grading sheet

grading_sheet = '10QVjRDzRhl7hCaCIn1J6GZNFnpo8ku_C9B6MAkG-SOw'
grading_worksheet = 'DIT181'

def grading_rows_headers(rows):
    return [rows[0], rows[1]]

def grading_rows_data(rows):
    return rows[2:]

class GradingLookup:
    def __init__(self, headers_rows):
        def fill_in(xs):
            last = None
            for x in xs:
                if x:
                    last = x
                yield last

        self.header_lookup = dict((key, i) for (i, key) in enumerate(zip(*map(fill_in, headers_rows))))

    def id(self):
        return self.header_lookup[('ID', None)]

    def score(self, q):
        return self.header_lookup[(question_name(q), 'Score')]

    def feedback(self, q):
        return self.header_lookup[(question_name(q), 'Feedback')]

def parse_score(s):
    assert s != '', 'Found ungraded question.'
    if s == '-':
        return None
    return float(s)

def format_score(x):
    return f'{x:.5g}' if x != None else '-'


### Configuration of grading report and assignment scoring

questions_basic = [q for q in questions if q <= 6]
questions_advanced = [q for q in questions if q > 6]

def question_score_max(q):
    return 2 if q <= 6 else 3

def questions_score_max(qs):
    return sum(question_score_max(q) for q in qs)

def score_value(s):
    return 0 if s == None else s

def grading_question_score(grading, q):
    return score_value(grading[q][0])

def grading_questions_score(grading, qs):
    return sum(grading_question_score(grading, q) for q in qs)

grading_questions_score_via_questions = lambda qs: lambda grading: grading_questions_score(grading, qs)

grading_score = grading_questions_score_via_questions(questions)
grading_score_basic = grading_questions_score_via_questions(questions_basic)
grading_score_advanced = grading_questions_score_via_questions(questions_advanced)

def has_threshold(grading, min_basic, min_combined):
    basic = grading_score_basic(grading)
    advanced = grading_score_advanced(grading)
    return basic >= min_basic and advanced + (basic - min_basic) / 2 >= min_combined

def grading_grade(grading):
    if has_threshold(grading, 8, 4):
        return 'VG'
    if has_threshold(grading, 7, 0):
        return 'G'
    return 'U'

def formatted(f):
    return lambda x: format_score(f(x))

grading_report_columns_summary = [
    ('Basic points', formatted(grading_score_basic)),
    ('Advanced points', formatted(grading_score_advanced)),
    ('Grade', grading_grade),
]

grading_report_columns = [(question_name(q), formatted(grading_questions_score_via_questions([q]))) for q in questions] + grading_report_columns_summary

def grading_feedback(grading, resource):
    def format_points(score, score_max):
        if score == None:
            return 'not attempted'
        return f'{format_score(score)} points (out of {format_score(score_max)})'

    def format_line(description, score, score_max):
        return f'{description}: {format_points(score, score_max)}'

    def format_summary_line(kind, qs):
        return format_line(f'* {kind} part', grading_questions_score(grading, qs), questions_score_max(qs))

    def format_question(q):
        (score, feedback) = grading[q]
        yield format_line(f'## {question_name(q)}', score, question_score_max(q))
        yield ''
        if feedback:
            yield feedback
            yield ''

    return general.join_lines(itertools.chain([
        'Summary:',
        format_summary_line('Basic', questions_basic),
        format_summary_line('Advanced', questions_advanced),
        '',
        f'Exam grade: {grading_grade(grading)}',
        '',
        f'Original exam problems: {resource(False)[1]}',
        f'Suggested solutions: {resource(True)[1]}',
        '',
    ], *(format_question(q) for q in questions)))
