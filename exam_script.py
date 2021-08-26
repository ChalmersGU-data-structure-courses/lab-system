import general
import logging
from  pathlib import Path

import exam._2021_08_27.dit181.data as exam_config_dit181
import exam._2021_08_27.let375.data as exam_config_let375
import exam._2021_08_27.dat038.data as exam_config_dat038
import exam._2021_08_27.tda417.data as exam_config_tda417
import exam._2021_08_27.dit961.data as exam_config_dit961
from exam.canvas import Exam

exam_configs = {
    'dit181': exam_config_dit181,
    'let375': exam_config_let375,
    'dat038': exam_config_dat038,
    'tda417': exam_config_tda417,
    'dit961': exam_config_dit961,
}

logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)

exams = dict((key, Exam(exam_config)) for (key, exam_config) in exam_configs.items())

for e in exams.values():
    #e.allocate_students()
    #e.instantiate_template(share_dir = Path() / 'exam' / '_2021_08_27' / 'share_dir', share_url = 'http://uxul.org/~noname/exam/')
    e.upload_instances()

    #e.allocate_students()
#e.instantiate_template(share_dir = Path() / 'exam' / '_2021_08_27' / 'share_dir', share_url = 'http://uxul.org/~noname/exam/')
#e.upload_instances()
