import logging

import course

from this_dir import this_dir
import lp2.config as config


logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)

c = course.Course(config, dir = this_dir / 'lp2')

lab_1_j = c.labs[(1, config.LabLanguage.JAVA)]
lab_1_p = c.labs[(1, config.LabLanguage.PYTHON)]

lab_2_j = c.labs[(2, config.LabLanguage.JAVA)]
lab_2_p = c.labs[(2, config.LabLanguage.PYTHON)]

lab_3_j = c.labs[(3, config.LabLanguage.JAVA)]
lab_3_p = c.labs[(3, config.LabLanguage.PYTHON)]
