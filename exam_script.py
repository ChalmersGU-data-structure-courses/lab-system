import logging
from pathlib import Path

import exam._2021_04_07_dat038_tdaa417_reexam.data as exam_config
from exam.canvas import Exam

logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)

share_dir = Path('/home/noname/DIT181/exam/uxul')
share_url = 'http://uxul.org/~noname/exam/'

grading_table = Path('/home/noname/DIT181/table.csv')

file = Path('/home/noname/data-structures/code/Lab-grading/exam/_2021_04_07_dat038_tdaa417_reexam/submissions/20/exam-SebastianTomasNielsen-2021-04-07.pdf')

e = Exam(exam_config)
#e.download_submissions(submissions_dir, use_cache = True)
#e.normalize_submissions(submissions_dir)
e.check_selector_infos()
e.prepare_grading_table(grading_table, fill_in_missing_questions = True)
#a = e.guess_selector_infos(submissions_dir)
#e.write_selector_infos(a)
