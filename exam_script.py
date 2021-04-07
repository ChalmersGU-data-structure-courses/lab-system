import logging
from pathlib import Path

import exam._2021_04_07_dat038_tdaa417_reexam.data as exam_config
import exam.canvas

logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)

share_dir = Path('/home/noname/DIT181/exam/uxul')
share_url = 'http://uxul.org/~noname/exam/'

e = Exam(exam_config)
