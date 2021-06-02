import general
import logging

import exam._2021_06_03_exam.dit181.data as exam_config
from exam.canvas import Exam

logging.basicConfig()
logging.getLogger().setLevel(logging.DEBUG)

e = Exam(exam_config)
#e.allocate_students()
e.instantiate_template()
#e.upload_instances()
