
import json
import difflib
import sys
import re
import os
import os.path
from os.path import join as pjoin, basename
import subprocess
import argparse
from glob import glob

# First, you have to download and group all submissions: run 'split_submissions.py"


parser = argparse.ArgumentParser(description='Split the downloaded Canvas submissions into groups.')
parser.add_argument('--users', type=argparse.FileType('r'), required=True,
                    help='json file with student/user data')
parser.add_argument('--subs', required=True,
                    help='the folder containing the (cleaned) submissions')
parser.add_argument('--solution', required=True,
                    help='the folder containing the solution suggestion')
parser.add_argument('--skeleton', required=True,
                    help='the folder containing the code skeleton')
parser.add_argument('--out', dest='outfolder', required=True,
                    help='the destination folder (must not exist)')
args = parser.parse_args()

assert os.path.isdir(args.subs), "The --subs folder must exist!"
assert os.path.isdir(args.solution), "The --solution folder must exist!"
assert os.path.isdir(args.skeleton), "The --skeleton folder must exist!"
assert not os.path.exists(args.outfolder), "The --out folder must not exist!"


labname = basename(args.skeleton)
if not labname:
    labname = basename(os.path.dirname(args.skeleton))
labfiles = set(map(basename, glob(pjoin(args.solution, '*.*'))))


## Read the students, and map the lab groups to their students

group_users = {}
labusers = json.loads(args.users.read())
for user in labusers.values():
    group_users.setdefault(user['group'], []).append(user['sortname'])


## get the groups, and sort by group number

def sortkey(g):
    digs = re.sub(r'\D', '', g)
    n = int(digs) if digs else 0
    return (n, g)

labgroups = list(map(basename, glob(pjoin(args.subs, '*'))))
labgroups.sort(key=sortkey)


CSS = """
.diff td  { padding: 0 5 }  /* Perhaps: font-family: monospace */
.diff_sub { background-color: #FAA } /* left side only */
.diff_add { background-color: #FAA } /* right side only */
.diff_chg { background-color: #AFA } /* change */
.diff_column { white-space: pre-wrap; width: 50% }
.results  { border-collapse: collapse }
.results th, .results td { border: 1px black solid; padding: 5; vertical-align: top }
.results pre { font-size: smaller; white-space: pre-wrap }
.nowrap { white-space: nowrap }
"""

HEADER = f"""
<html>
<head>
<meta charset="UTF-8">
<title>Grading</title>
<style>{CSS}</style>
</head>
<body>
"""

FOOTER = """
</body>
</html>
"""


def readfile(fil):
    with open(fil, "br") as F:
        bstr = F.read()
    try:
        return bstr.decode()
    except UnicodeDecodeError:
        try:
            return bstr.decode(encoding="latin1")
        except UnicodeDecodeError:
            return bstr.decode(errors="replace")

## check each group

os.mkdir(args.outfolder)
with open(pjoin(args.outfolder, "index.html"), "w") as OUT:
    print(HEADER, file=OUT)
    print(f"""
<h1>Grading {labname}</h1>
<p>Files to submit: <strong>{', '.join(sorted(labfiles))}</strong></p>
<p>Total submissions: <strong>{len(labgroups)}</strong></p>
<table class="results"><tr>
<th>Group</th><th>Members</th><th>Missing</th><th>Excessive</th><th>Compilation</th><th>Similarity</th>
</tr>
""", file=OUT)
    for grp in labgroups:
        print(grp)
        print(f'<td class="nowrap">{grp}</td>', file=OUT)

        print('<td>', file=OUT)
        users = group_users[grp[:-5]] if grp.endswith(' LATE') else group_users[grp]
        for i, name in enumerate(sorted(users)):
            if i>0: print('<br/>', file=OUT)
            print(name, file=OUT)
        print('</td>', file=OUT)

        grpdir = pjoin(args.outfolder, grp)
        os.mkdir(grpdir)
        javadir = pjoin(grpdir, 'java')
        os.mkdir(javadir)

        submitted = set(map(basename, glob(pjoin(args.subs, grp, '*.*'))))

        # check missing files, and over-submissions

        missing = sorted(labfiles - submitted)
        print(f'<td>{"<br/>".join(missing)}</td>', file=OUT)

        toomany = sorted(submitted - labfiles)
        print('<td>', file=OUT)
        for i, f in enumerate(toomany):
            if i>0: print(f'<br/>', file=OUT)
            d = pjoin(grp, 'java') if f.endswith('.java') else grp
            print(f'<a href="{d}/{f}">{f}</a>', file=OUT)
        print('</td>', file=OUT)

        # copy files to out directory

        for f in glob(pjoin(args.skeleton, '*.java')):
            subprocess.run(["cp", f, javadir])
        for f in glob(pjoin(args.subs, grp, '*.*')):
            if f.endswith('.java'):
                javacode = readfile(f)
                # remove packages in java files:
                javacode = re.sub(r'^(package[^;]*;)', r'/* \1 */', javacode)
                with open(pjoin(javadir, basename(f)), "w") as F:
                    print(javacode, file=F)
            else:
                subprocess.run(["cp", f, grpdir])

        # try to compile the java files

        print('<td>', file=OUT)
        for f in glob(pjoin(args.subs, grp, '*.java')):
            javafile = basename(f)
            process = subprocess.run(['javac', javafile], cwd=javadir, capture_output=True)
            if process.returncode:
                print(f'<pre>{process.stderr.decode()}</pre>', file=OUT)
        print('</td>', file=OUT)


        # diffing against the solution

        print('<td class="nowrap">', file=OUT)
        linebreak = False
        for i, f in enumerate(sorted(submitted & labfiles)):
            subslines = readfile(pjoin(args.subs, grp, f)).splitlines()
            goldlines = readfile(pjoin(args.solution, f)).splitlines()

            difftable = difflib.HtmlDiff().make_table(
                subslines, goldlines, "SUBMISSION", "SOLUTION")
            difftable = difftable.replace('<td nowrap="nowrap">', '<td class="diff_column">')
            difftable = difftable.replace('&nbsp;', ' ')
            with open(pjoin(grpdir, f + '.html'), "w") as F:
                print(HEADER, file=F)
                print(f'<h1>{grp}: {f}</h1>', file=F)
                print(difftable, file=F)
                print(FOOTER, file=F)

            sim = difflib.SequenceMatcher(a=subslines, b=goldlines).ratio()
            if i>0: print(f'<br/>', file=OUT)
            print(f'<a href="{grp}/{f}.html">{f}</a>: {100*sim:.0f}%', file=OUT)
        print('</td>', file=OUT)

        print('</tr>', file=OUT)
    print(FOOTER, file=OUT)

