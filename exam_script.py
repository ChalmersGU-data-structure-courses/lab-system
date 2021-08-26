import general
import logging
from  pathlib import Path

#import exam._2021_08_27.dit181.data as exam_config
import exam._2021_08_27.dit961.data as exam_config
from exam.canvas import Exam

logging.basicConfig()
logging.getLogger().setLevel(logging.DEBUG)

e = Exam(exam_config)
#e.allocate_students()
e.instantiate_template(share_dir = Path() / 'exam' / '_2021_08_27' / 'share_dir', share_url = 'http://uxul.org/~noname/exam/')
#e.upload_instances()
