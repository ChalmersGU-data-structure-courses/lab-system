from datetime import datetime, timedelta
import re
import http_logging
import logging

from general import with_stem, OpenWithNoModificationTime, print_json
from canvas import Canvas, Assignment

logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)

lab1_deadline0 = datetime.fromisoformat("2020-11-11 20:00+01:00")
lab1_deadline1 = datetime.fromisoformat("2020-11-19 20:00+01:00")
lab1_deadline2 = datetime.fromisoformat("2020-11-27 20:00+01:00")

course_id = 10681
assignment_id = 'lab 1' #23431
deadline = lab1_deadline1
output_dir = 'output' #needs to not exist

def cleanup_hook(dir):
    # decapitalize text file suffices
    for path in dir.glob('*.TXT'):
       path.rename(path.with_suffix('.txt'))

    # remove copy suffices
    for path in dir.iterdir():
        if path.is_file() and not path.name.startswith('_'):
            stem = path.stem
            stem = re.sub(r'^(-\d+| \(\d+\))$', '\1', stem)
            path.rename(with_stem(path, stem))

    # remove packages in java files
    for path in dir.glob('*.java'):
        with path.open() as file:
            content = file.read()
        content = re.sub(r'^(package[^;]*;)', r'/* \1 */', content)
        with OpenWithNoModificationTime(path) as file:
           file.write(content)

canvas = Canvas('chalmers.instructure.com')

a = Assignment(canvas, course_id, assignment_id)
a.build_submissions(use_cache = False)
a.prepare_submissions(output_dir, deadline = lab1_deadline1)
