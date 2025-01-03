import json
import unicodedata
import re
import os.path
import subprocess
import argparse
from glob import glob


# First, do the following:
# - download all submissions: go to the lab in Canvas, and click "Download submissions"
# - run 'collect_students_from_canvas.py' and pipe the output to a json file

parser = argparse.ArgumentParser(description='Split the downloaded Canvas submissions into groups.')
parser.add_argument('--students', metavar='JSON', type=argparse.FileType('r'), required=True,
                    help='json file with student data')
parser.add_argument('--in', metavar='DIR', dest='infolder', required=True,
                    help='the folder containing the raw submissions')
parser.add_argument('--out', metavar='DIR', dest='outfolder', required=True,
                    help='the destination folder (must not exist)')
args = parser.parse_args()

assert os.path.isdir(args.infolder), "The --in folder must exist!"
assert not os.path.exists(args.outfolder), "The --out folder must not exist!"

def normalize(s):
    return unicodedata.normalize('NFKC', s)

# Read the students, and map them to their lab group

user_groups = {}
labusers = json.loads(args.students.read())
for user in labusers.values():
    uid = re.sub(r"\W", "", normalize(user['sortname']).lower())
    user_groups[uid] = user['group']

# Move all submissions to their lab group directory

submissions = {}
for filename in glob(os.path.join(args.infolder, "*.*")):
    uid = re.sub(r"_\d+_\d+_.+", "", os.path.basename(filename))
    uid = normalize(uid)
    if uid.lower().endswith("_late"):
        uid = uid[:-5]
        grp = user_groups[uid] + " LATE"
    else:
        grp = user_groups[uid]
    grpdir = os.path.join(args.outfolder, grp)
    os.makedirs(grpdir, exist_ok=True)
    dest = re.sub(r"^[^_]+(_LATE)?_\d+_\d+_", "", os.path.basename(filename), flags=re.IGNORECASE)
    if dest.lower().endswith('.txt'):
        dest = dest.lower()
    cmd = ["cp", filename, os.path.join(grpdir, dest)]
    print(" ".join(cmd))
    subprocess.run(cmd)

# Rename submission files filename-5.xxx to filename.xxx

# repeat three times, beacuse there might be files like filename-2-1.xxx or even filename-4-2-1.xxx
for _repeats in range(2):
    for suffix in range(10):
        for filename in glob(os.path.join(args.outfolder, "*", f"*-{suffix}.*")):
            newname = re.sub(f"-{suffix}(\\.[^.]*)", r"\1", filename)
            print(f"mv {filename} {newname}")
            os.replace(filename, newname)
