import http_logging
import logging

from canvas import *

logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)

course_id = 10681
assignment_id = 'lab 1' #23431
deadline = datetime.now(timezone.utc) - timedelta(days=2) #example deadline, can be None
output_dir = 'output' #needs to not exist

canvas = Canvas('chalmers.instructure.com')
a = Assignment(canvas, course_id, assignment_id)
a.build_submissions()
a.prepare_submissions(output_dir, deadline)
