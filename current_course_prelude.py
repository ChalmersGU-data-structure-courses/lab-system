import logging

import course

from this_dir import this_dir
import dit182.config as config


logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)

c = course.Course(config, dir = this_dir / 'dit182')
