#Broken: uses old version of lab.py (around 2021-06).
import csv
import logging
from pathlib import Path

#import course
import lab

import gitlab_config


logging.basicConfig()
logging.getLogger().setLevel(logging.WARNING)

input = Path('/home/noname/DIT181/assignment-protocol-ids.txt')
output = Path('/home/noname/DIT181/assignment-protocol.csv')

def get_passings():
    (course, labs) = lab.labs(gitlab_config)
    grades = dict((k, labs[k].student_grades()) for k in labs)
    on_canvas = course.canvas_course.student_ids
    all = set.union(set(on_canvas), *(set(lab_grades.keys()) for k, lab_grades in grades.items()))

    def f(student):
        return dict((k, grades[k].get(student)) for k in labs)
    return dict((student, f(student)) for student in all)

#p = get_passings()

def report(passings, input, output):
    (course, labs) = lab.labs(gitlab_config)
    passings = dict(passings)
    input_personnummers = list(map(lambda s: s.replace('-', ''), input.read_text().splitlines()))

    def passed_as_grade(k):
        return {
            1: 'G',
            0: 'U',
            None: '',
        }[k]

    def combined_grade(ys):
        for k in [1, None]:
            if all(y == k for y in ys):
                return k
        return 0

    def row(user_id, result):
        user = None
        if isinstance(user_id, int):
            user = course.canvas_course.user_details[user_id]
        output = [
            user.sis_user_id if user else '[not in course]',
            user.sortable_name if user else user_id,
        ]
        xs = list(result.values())
        xs.append(combined_grade(result.values()))
        output.extend(map(passed_as_grade, xs))
        return output

    with output.open('w') as file:
        out = csv.writer(file)
        for personnummer in input_personnummers:
            user_id = course.canvas_course.user_sis_id_to_id[personnummer]
            result = passings.pop(user_id, None)
            out.writerow(row(user_id, result))

        for (user_id, result) in passings.items():
            out.writerow(row(user_id, result))

#    input_personnummers = list(map(lambda s: s.replace('-', ''), input.read_text().splitlines()))

    #results = results_by_user_id(exam)
    #gradings = dict((exam.user_details[user_id].sis_user_id, result) for (user_id, result) in results.items())
