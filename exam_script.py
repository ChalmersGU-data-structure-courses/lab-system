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

def search_user(exam, pattern):
    def f():
        for user in exam.course.user_details.values():
            if pattern in user.name:
                yield user
    return list(f())

def select_user_id(exam, pattern):
    rs = search_user(exam, pattern)
    assert len(rs) == 1
    return rs[0].id

for key, e in exams.items():
    if key != 'dit181':
        continue
    print(key)
    
    #e.allocate_students()
    e.instantiate_template(share_dir = Path() / 'exam' / '_2021_08_27' / 'share_dir', share_url = 'http://uxul.org/~noname/exam/', solution = True)
    #e.upload_instances(delete_old = False)
    #e.create_assignments(publish = True, update = True)
    #e.delete_assignments()

    #e.allocate_students()
#e.instantiate_template(share_dir = Path() / 'exam' / '_2021_08_27' / 'share_dir', share_url = 'http://uxul.org/~noname/exam/')
#e.upload_instances()

e = exams['dit181']
