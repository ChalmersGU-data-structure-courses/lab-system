import collections
import csv
import itertools
import gspread
import logging
import re

import canvas
import exam_uploader
import general
import gitlab_config as config

logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)

# Tolerance for floating-point calculations.
epsilon = 0.0001

grading_sheet = '1aE0uurSwx3sro6WiAX9S0PAiPdo-YVCoZkwxLVJI3iQ'

questions = [i + 1 for i in range(8)]
questions_basic = [q for q in questions if q <= 6]
questions_advanced = [q for q in questions if q > 6]

column_id = 0

def column_question_score(q):
    return 1 + 3 * (q - 1)

def column_question_feedback(q):
    return 1 + 3 * (q - 1) + 1

def parse_id(s):
    m = re.fullmatch('V(\\d+)N(\\d+)', s)
    return (int(m.group(1)), int(m.group(2))) if m else None

def parse_score(s):
    assert s != '', 'Found ungraded question.'
    if s == '-':
        return None
    return float(s)

def score_value(s):
    return 0 if s == None else s

def question_score_max(q):
    return 2 if q in questions_basic else 3

def process_row(row):
    id = parse_id(row[column_id])
    if not id:
        return

    def process_question(q):
        score = parse_score(row[column_question_score(q)])
        feedback = row[column_question_feedback(q)]
        return (score, feedback)

    yield (id, dict((q, process_question(q)) for q in questions))

def load_data():
    worksheet = gspread.oauth().open_by_key(grading_sheet).get_worksheet(0)
    rows = worksheet.get_all_values(value_render_option = 'FORMULA')
    return dict(x for row in rows for x in process_row(row))

def score_sum(x, qs):
    return sum(score_value(x[q][0]) for q in qs)

Result = collections.namedtuple('Result', field_names = ['questions', 'points', 'points_basic', 'points_advanced', 'grade'])

def get_results():
    lookup = dict(((v, n), integration_id) for (v, n, integration_id, _) in exam_uploader.read_lookup(exam_uploader.lookup_file))
    data = load_data()

    def process_question(q, score, feedback):
        if score == None:
            feedback = 'Missing.'
        v = score_value(score)
        v_max = question_score_max(q)
        if not feedback:
            assert v == v_max, "No feedback given despite points deducted."
            feedback = 'Perfect.'
        return (v, v_max, feedback)

    def process(id, x):
        points_basic = score_sum(x, questions_basic)
        points_advanced = score_sum(x, questions_advanced)

        passing = points_basic >= 7.25 - epsilon
        distinction = points_advanced + int(points_basic - 8 + epsilon) / 2 >= 4 - epsilon

        return Result(
            questions = dict((q, process_question(q, *x[q])) for q in questions),
            points = score_sum(x, questions),
            points_basic = points_basic,
            points_advanced = points_advanced,
            grade = ('VG' if distinction else 'G') if passing else 'U',
        )

    return dict((lookup[id], process(id, x)) for (id, x) in data.items())

def results_by_user_id(course, use_cache = True):
    return dict((course.user_integration_id_to_id[integration_id], result) for (integration_id, result) in get_results().items())

def results_for_grading_protocol(input, output, use_cache = True):
    c = canvas.Canvas(config.canvas_url)
    exam = canvas.Course(c, config.canvas_exam_course_id, use_cache = use_cache)
    results = results_by_user_id(exam)

    gradings = dict((exam.user_details[user_id].sis_user_id, result) for (user_id, result) in results.items())
    input_personnummers = list(map(lambda s: s.replace('-', ''), input.read_text().splitlines()))

    def row(user, result):
        output = [user.sis_user_id, user.sortable_name]
        output.append(f'{result.points_basic:.5g}' if result else '-')
        output.append(f'{result.points_advanced:.5g}' if result else '-')
        output.append(f'{result.grade}' if result else '-')
        return output

    with output.open('w') as file:
        out = csv.writer(file)
        for personnummer in input_personnummers:
            user = exam.user_details[exam.user_sis_id_to_id[personnummer]]
            result = gradings.pop(personnummer, None)
            out.writerow(row(user, result))

        for (personnummer, result) in gradings.items():
            user = exam.user_details[exam.user_sis_id_to_id[personnummer]]
            out.writerow(row(user, result))

# Should use author id, but the author id looks weird/different from the user id.
def post_grading(use_cache = True, replace = False, replace_author_name = 'Christian Sattler'):
    c = canvas.Canvas(config.canvas_url)
    exam = canvas.Course(c, config.canvas_exam_course_id, use_cache = use_cache)
    assignments = exam.get_assignments(include = ['overrides'], use_cache = use_cache)
    results = results_by_user_id(exam, use_cache = use_cache)

    def identify_submission(a):
        override = general.from_singleton(a.overrides)
        user_id = general.from_singleton(override.student_ids)
        submission = general.from_singleton(exam.get_submissions(a.id, use_cache = False))
        assert submission.user_id == user_id, f'Submission user id {submission.user_id} does not match assignment user id {user_id}'
        if submission.workflow_state != 'unsubmitted' or user_id in results:
            yield (user_id, submission)

    submissions = general.sdict(x for a in assignments for x in identify_submission(a))
    assert set(submissions.keys()) == set(results.keys()), 'Found mismatch between submissions and graded students.'

    for user_id in submissions:
        submission = submissions[user_id]
        result = results[user_id]
        if replace or submission.workflow_state != 'graded':
            if replace:
                for comment in submission.submission_comments:
                    if comment.author_name == replace_author_name:
                        c.delete(['courses', exam.course_id, 'assignments', submission.assignment_id, 'submissions', user_id, 'comments', comment.id])
            endpoint = ['courses', exam.course_id, 'assignments', submission.assignment_id, 'submissions', user_id]
            params = {
                'comment[text_comment]': format_feedback(result),
                'submission[posted_grade]': result.points,
            }
            c.put(endpoint, params = params)

def format_feedback(r):
    def format_line(description, score, score_max):
        return f'{description}: {score:.5g} points (out of {score_max:.5g})'

    def format_summary_line(kind, qs):
        return format_line(f'* {kind} part', sum(r.questions[q][0] for q in qs), sum(r.questions[q][1] for q in qs))

    def format_question(q, v, v_max, feedback):
        return '{}\n\n{}\n'.format(format_line(f'## Question {q}', v, v_max), feedback)

    return '\n'.join(itertools.chain([
        'Summary:',
        format_summary_line('Basic', questions_basic),
        format_summary_line('Advanced', questions_advanced),
        '',
        f'Final grade (assuming you pass the labs): {r.grade}',
        '',
        'For detailed feedback, please see the rest of this report.',
        ''
    ], (format_question(q, *r.questions[q]) for q in questions)))

def analysis():
    thresholds_basic = [0, 1, 2, 3, 4, 5, 6, 6.5, 7, 7.25, 7.5, 8, 9, 10, 11, 12]
    thresholds_advanced = [0, 1, 2, 3, 3.5, 4, 5, 6]

    histogram_basic = dict((t, 0) for t in thresholds_basic)
    histogram_advanced = dict((t, 0) for t in thresholds_advanced)

    count_basic = 0
    count_advanced = 0

    data = load_data()
    for (id, x) in data.items():
        scores_basic = [score_value(x[q][0]) for q in questions_basic]
        scores_advanced = [score_value(x[q][0]) for q in questions_advanced]

        score_basic = sum(scores_basic)
        score_advanced = sum(scores_advanced)
        
        for t in thresholds_basic:
            if score_basic  >= t:
                histogram_basic[t] = histogram_basic[t] + 1
            for t in thresholds_advanced:
                if score_advanced >= t:
                    histogram_advanced[t] = histogram_advanced[t] + 1

        vg = score_advanced + round(score_basic - 8) / 2
        vg_fix = score_advanced + int(score_basic - 8) / 2

        if score_basic >= 7.249:
            count_basic = count_basic + 1
        if vg_fix >= 4:
            count_advanced = count_advanced + 1

        if score_basic >= 7.249 and score_advanced < 4 and score_advanced >= 2.5:
            print(f'{id}: {score_basic:.4g}, {score_advanced:.4g}, {vg:.4g}, {vg_fix:.4g}')

    print(count_advanced)

    #if precise >= 7 and precise < 7.25:
    #    print('{}: {}; {}'.format(id, precise, scores_basic))

    #rounding = sum(round(2 * score_value(a)) / 2 for (a, b) in x.values())
    #print(precise - rounding)


#        return Course.GradingSheet(
#            group_rows = self.parse_group_rows([row[0] for row in rows]),
#            grading_columns = self.parse_grading_columns(rows[0]),
#            rows = rows,
#        )
