import general
import logging
from pathlib import Path

import exam._2021_04_07_dat038_tdaa417_reexam.data as exam_config
from exam.canvas import Exam

logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)

share_dir = Path('/home/noname/DIT181/exam/uxul')
share_url = 'http://uxul.org/~noname/exam/'

grading_table = Path('/home/noname/DIT181/table.csv')

grading_report = Path('/home/noname/data-structures/code/Lab-grading/exam/_2021_04_07_dat038_tdaa417_reexam/report.csv')
grading_report = Path('/home/noname/data-structures/code/Lab-grading/exam/_2021_04_07_dat038_tdaa417_reexam/report.csv')

e = Exam(exam_config)
#e.upload_gradings()
#e.instantiate_template(share_dir = share_dir, share_url = share_url, solution = True)

#e.download_submissions(submissions_dir, use_cache = True)
#e.normalize_submissions(submissions_dir)
#e.check_selector_infos()
#e.prepare_grading_table(grading_table, fill_in_missing_questions = True)
#a = e.guess_selector_infos(submissions_dir)
#e.write_selector_infos(a)

#e.write_grading_report(
#    Path('/home/noname/data-structures/code/Lab-grading/exam/_2021_04_07_dat038_tdaa417_reexam/report.csv'),
#    include_non_allocations = True,
#    include_non_submissions = True
#)
