import logging

import course

from this_dir import this_dir
import lp2.config as config


logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)

c = course.Course(config, dir = this_dir / 'lp2')
