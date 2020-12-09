from collections import defaultdict
import csv
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from canvas import Canvas, Course, GroupSet
import config
from general import from_singleton
from lab_assignment import LabAssignment

# Parameters
labs = [1, 2, 3, 4]
file_registered_students = Path('registrerade-studenter.txt')

canvas = Canvas(config.canvas_url, )
course = Course(canvas, config.course_id)
group_set = GroupSet(canvas, config.course_id, config.group_set)

with file_registered_students.open() as file:
    csv_reader = csv.DictReader(file, dialect = csv.excel_tab, fieldnames = ['personnummer', 'name', 'course', 'status', 'program'])
    user_map = dict()
    num_in_ladok = 0
    for row in csv_reader:
        num_in_ladok = num_in_ladok + 1
        r = SimpleNamespace(**row)
        users = [user for user in group_set.user_details.values() if str(user.sis_user_id) == str(r.personnummer.replace('-', '').strip())]
        if len(users) >= 1:
            user = from_singleton(users)
            r.user = user
            user_map[r.user.id] = r

    print('{} students registered in Ladok.'.format(num_in_ladok))
    print('{} students registered in Ladok also found registered in Canvas.'.format(len(user_map)))
    print('Restricting to those {} students have a group.'.format(len(list(filter(lambda u: u.user.id in group_set.user_to_group, user_map.values())))))
    print()

    for u in list(user_map.values()):
        if u.user.id in group_set.user_to_group:
            u.group = group_set.user_to_group[u.user.id]
        else:
            del user_map[u.user.id]

    ass = dict()
    for lab in labs:
        ass[lab] = LabAssignment(canvas, config.course_id, lab)
        ass[lab].collect_submissions()

    for u in user_map.values():
        u.lab_attempts = dict()
        for lab in labs:
            a = ass[lab]
            submission = None
            s = a.submissions.get(u.group)
            if s:
                for i in range(len(s.submissions)):
                    submission = s.submissions[i]
                    if submission.entered_grade == 'complete':
                        break
                    submission = None

            if not submission:
                u.lab_attempts[lab] = -1
            else:
                ds = [i for i in range(len(a.deadlines)) if a.deadlines[i] <= submission.graded_at_date]
                u.lab_attempts[lab] = ds[-1]

    def print_lab_statistics(users, lab):
        when_passed = dict()
        when_passed[-1] = 0
        for i in range(len(ass[lab].deadlines)):
            when_passed[i] = 0

        for user in users:
            u = user_map[user]
            when_passed[u.lab_attempts[lab]] += 1

        s = '* Lab {}: {:3} did not yet pass'.format(lab, when_passed[-1])
        for i in range(len(ass[lab].deadlines)):
            if ass[lab].deadlines[i] <= datetime.now(tz = timezone.utc):
                s += ', {:3} passed at attempt {}'.format(when_passed[i], i)
        s += '.'
        print(s)

    def print_labs_statistics(description, users):
        print('{} ({} students):'.format(description, len(users)))
        for lab in labs:
            print_lab_statistics(users, lab)

    print_labs_statistics('Global statistics', user_map.keys())
    print()

    programs = defaultdict(list)
    for u in user_map.values():
        programs[u.program].append(u.user.id)

    for program, users in sorted(programs.items(), key = lambda x: (- len(x[1]), x[0])):
        print_labs_statistics('For program {}'.format(program), users)
        print()
