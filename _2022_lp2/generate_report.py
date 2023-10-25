import csv
from pathlib import Path

from prelude import *

#for l in c.labs.values():
#    l.setup()
#    l.parse_requests_and_responses(from_gitlab = False)
#    l.process_requests()

#r = c.grading_report_with_summary()

section_names = ['Chalmers DAT038', 'Chalmers DAT525', 'Chalmers TDA417']

# Make sure all requests are processed.
#for lab in c.labs.values():
#    lab.setup_request_handlers()
#    lab.parse_response_issues()
    #lab.repo_fetch_all()
#    lab.parse_request_tags(False)
#    lab.process_requests()

for section_name in section_names:
    section = c.canvas_course.get_section(section_name)
    canvas_students = c.canvas_course.get_students_in_section(section.id)

    with (c.dir / (section_name + '.in.csv')).open('w') as file:
        writer = csv.DictWriter(file, {'pin': 'Personal identity number', 'Name': 'Name'}, dialect = csv.excel_tab)
        writer.writeheader()
        for canvas_student in canvas_students:
            writer.writerow({'pin': canvas_student.sis_user_id, 'Name': canvas_student.sortable_name})


def summary(scores):
    for lab_number in [1, 2, 3]:
        if not (scores[(lab_number, config.LabLanguage.PYTHON)] or scores[(lab_number, config.LabLanguage.JAVA)]):
        #if not scores[(lab_number, config.LabLanguage.JAVA)]:
            return 0
    return 1

import grading_protocol
grading_protocol.report_course(c, [(section_name + '.in.csv', section_name + '.csv') for section_name in section_names], 'report_extra.csv', summary = summary)


#def get_report(course, section_name):
#    section = course.canvas_course.get_section(section_name)
#    canvas_students = course.canvas_course.get_students_in_section(section.id)
#    print(len(canvas_students))
