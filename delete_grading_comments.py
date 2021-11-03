import logging

from general import print_json
from canvas import Canvas, Course, Assignment
import config

logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)

assignment_id = 'lab 2' #23431

header_group = 'Group'
header_grader = 'Grader'
header_grade = '0/1'
header_comment = 'Comments for students'
header_group_formatter = 'Lab group {}'

canvas = Canvas('chalmers.instructure.com')
course = Course(canvas, config.course_id)
assignment = Assignment(canvas, config.course_id, assignment_id)
groups = assignment.groups


raw_submissions = canvas.get_list(['courses', assignment.course_id, 'assignments', assignment.assignment_id, 'submissions'], params = {'include[]': ['submission_comments', 'submission_history', 'visibility']}, use_cache = False)
submissions = dict((submission.user_id, submission) for submission in raw_submissions)

assignment.build_submissions(use_cache = True)
for group in assignment.submissions:
    for user in groups.group_users[group]:
        s = submissions[user]
        for comment in s.submission_comments:
            if 'The above grading was performed by' in comment.comment: 
                print_json(comment)
                canvas.delete(['courses', assignment.course_id, 'assignments', assignment.assignment_id, 'submissions', user, 'comments', comment.id])
