
import json
import difflib
import sys
import re
import os
from os.path import relpath
import shutil
import subprocess
import argparse
from glob import glob
import signal

from pathlib import Path

# Set this to False if you haven't installed diff2html-cli:
#   https://www.npmjs.com/package/diff2html-cli
# (or if you want to use Python's internal difflib of some reason)
USE_GIT_DIFF2HTML = True


def autograde_all(cfg):
    rows = [H('tr', [
        H('th', 'Group'),
        H('th', 'Late'),
        H('th', 'Members'),
        H('th', 'Missing'),
        H('th', 'Unknown'),
        H('th', 'Compared with skeleton'),
        H('th', 'Compared with solution'),
        H('th', 'Compared with previous'),
        H('th', 'Test output') if cfg.testfile else '',
        H('th', 'Compilation & runtime errors' if cfg.testfile else 'Compilation errors'),
        H('th', 'Comments'),
    ])]
    for group in cfg.labgroups:
        print(group)
        rows += [autograde(group, cfg)]

    with (cfg.dir / 'index.html').open('w') as OUT:
        print(
            HEADER % relpath(Path(), cfg.dir),
            H('h1', f'{cfg.labname} autograding: {cfg.dir.name}'),
            H('p', ['Files to submit:', H('strong', ', '.join(sorted(cfg.required)))]),
            H('p', ['Total submissions:', H('strong', str(len(cfg.labgroups)))]),
            H('table', rows, klass='results'),
            FOOTER,
            file=OUT
        )


def copy_submission_to_outfolder(f, outfolder, cfg):
    # upper-/lowercase of destination should depend on what is required
    src = f.name
    for dest in cfg.templates + cfg.required:
        if src.lower() == dest.lower():
            break
        else:
            dest = src
    # copy the file contents
    content = readfile(f)
    if f.name.endswith('.java'):
        # remove packages in java files
        content = re.sub(r'^(package[^;]*;)', r'/* \1 */', content)
    with (outfolder / dest).open('w') as F:
        print(content, file=F)
    return src, dest



def autograde(group, cfg):
    dir = cfg.dir / group
    late_file = dir / 'late.txt'
    members_file = dir / 'members.txt'
    current = dir / 'current'
    previous = dir / 'previous'
    staging = dir / 'staging'
    staging.mkdir()

    # Copy template files to outfilder
    for f in cfg.templates:
        shutil.copy(cfg.skeleton / f, staging / f)
    for f in cfg.datadirs:
        os.symlink((cfg.skeleton / f).relative_to(staging), staging / f)

    # Copy submitted files to outfolder
    submitted = dict()
    for d in [previous, current]:
        if not d.exists(): continue
        for f in d.iterdir():
            src, dest = copy_submission_to_outfolder(f, staging, cfg)
            submitted[dest] = f

    # Create the result table row
    row = [
        # Group
        H('td', [group.replace(' ', NBSP)]),

        # Late
        H('td', [late_file.open().read() if late_file.exists() else '']),

        # Members
        H('td', joinBR(sorted(members_file.open().readlines()))),

        # Missing
        H('td', joinBR(
            H('a', f, href = cfg.solution / f)
            for f in cfg.required if f not in submitted
        )),

        # Unknown
        H('td', joinBR(
            H('a', f, href = staging / f)
            for f in sorted(submitted) if f not in cfg.templates and f not in cfg.required
        )),

        # Compared with skeleton
        H('td', joinBR(
            diff_and_link(staging / f, cfg.skeleton / f, 'SUBMISSION', 'SKELETON', staging / f)
            for f in sorted(submitted) if f in cfg.templates and f not in cfg.required
        )),

        # Compared with solution
        H('td', joinBR(
            diff_and_link(staging / f, cfg.solution / f, 'SUBMISSION', 'SOLUTION', staging / f)
            for f in sorted(submitted) if f in cfg.required
        )),
    ]

    for f, original in sorted(submitted.items()):
        print(str(original.parent) + ", " + str(current))
        print(str(previous / original.name))
        if original.parent == current and (previous / original.name).is_file():
            print("hit")

    # If there are previous submissions
    row += [
        H('td', joinBR(
            diff_and_link(staging / f, previous / f, 'NEW SUBMISSION', 'PREVIOUS', staging / (f + '.prev'))
            for f, original in sorted(submitted.items())
            if original.parent == current
            if (previous / original.name).is_file()
        ) if previous.exists() else ''),
    ]
    
    # Compile java files
    print(' - compile java files')
    javafiles = list(f for f in set(submitted) | set(cfg.templates) | set(cfg.required) if f.endswith('.java'))
    process = subprocess.run(['javac'] + javafiles, cwd=staging, capture_output=True)
    compilation_errors = bool(process.returncode)
    if compilation_errors:
        print('   + compilation error')
        row += [
            H('td', '') if cfg.testfile else '',
            H('td', joinBR((
                H('strong', 'Compilation error'),
                H('pre', process.stderr.decode())
            ))),
        ]

    elif cfg.testfile:
        # Run test scripts
        runtime_errors = []
        print(f' - run tests', end='', flush=True)
        for outfile, script in cfg.testscripts:
            print(f' .', end='', flush=True)
            if isinstance(script, str):
                script = script.split()
            try:
                process = subprocess.run(script, cwd=staging, timeout=cfg.timeout, capture_output=True)
            except subprocess.TimeoutExpired:
                print(f'timeout', end='', flush=True)
                runtime_errors += [
                    H('strong', f'Timeout (>{cfg.timeout}s): {outfile}'),
                ]
                continue
            if process.returncode:
                print(f'error', end='', flush=True)
                errlines = process.stderr.decode().splitlines(keepends=True)
                del errlines[30:]
                runtime_errors += [
                    H('strong', f'Runtime error: {outfile}'),
                    H('pre', ''.join(errlines)),
                ]
            with (staging / outfile).open('a') as F:
                print(f'===== {" ".join(script)[:70]}...', file=F)
                print(process.stdout.decode(), file=F)
                if process.stderr:
                    print(file=F)
                    print(' STDERR '.center(60, '='), file=F)
                    print(process.stderr.decode(), file=F)
                print(file=F)
        print()

        row += [
            H('td', joinBR(
                diff_and_link(staging / f, cfg.testfile.name.with_name(f + GOLD), 'OUT', 'GOLD', staging / f)
                for f in sorted(set(f for f, _ in cfg.testscripts))
            )),
            H('td', joinBR(runtime_errors)),
        ]

    else:
        # No compilation errors, and no test script
        row += [H('td', '')]

    comment_files = ['new-comments.txt', 'previous-comments.txt']
    r = []
    for comment_file in comment_files:
        path = dir / comment_file
        if path.exists():
            r.append(H('a', comment_file, href = path))
    row += [H('td', joinBR(r))]

    return H('tr', '\n'.join(row))


GIT_DIFF_CMD = 'git diff --no-index --histogram --unified=1000 --ignore-space-at-eol'.split()
DIFF2HTML_CMD = 'diff2html --style side --summary open --input file'.split()

def append_suffix(path, suffix):
    return path.parent / (path.name + suffix)

def diff_and_link(afile, bfile, atitle, btitle, diffile):
    diffile = append_suffix(diffile, '.diff')
    try:
        atext = readfile(afile)
    except FileNotFoundError:
        return H('span', f'({afile.name})', klass='grey')
    try:
        btext = readfile(bfile)
    except FileNotFoundError:
        return H('span', f'({bfile.name})', klass='grey')
    if atext.strip() == btext.strip():
        diffile = append_suffix(diffile, '.txt')
        with diffile.open('w') as F:
            print(atext, file=F)
        return f'{NBSP}={NBSP}' + H('a', afile.name, href=diffile, klass='grey')

    if USE_GIT_DIFF2HTML:
        cmd = GIT_DIFF_CMD + [afile, bfile] # str(...)?
        process = subprocess.run(cmd, capture_output=True)
        with diffile.open('wb') as F:
            F.write(process.stdout)
        difflines = process.stdout.splitlines()
        sim = 1 - sum(line.startswith(b'+') or line.startswith(b'-') for line in difflines) / len(difflines)
        cmd = DIFF2HTML_CMD + [
            '--highlightCode', str(afile.name.endswith('.java')).lower(),
            '--file', append_suffix(diffile, '.html'),
            '--', diffile,
        ]
        subprocess.run(cmd)
        diffile = append_suffix(diffile, '.html')

    else: # use difflib
        alines = atext.splitlines()
        blines = btext.splitlines()
        sim = difflib.SequenceMatcher(a=alines, b=blines).ratio()
        difftable = difflib.HtmlDiff().make_table(alines, blines, atitle, btitle)
        difftable = difftable.replace('<td nowrap="nowrap">', '<td class="diff_column">')
        difftable = difftable.replace(NBSP, ' ')
        # difftable = re.sub(r'(<span class="diff_(?:add|sub)">)(\s+)', r'\2\1', difftable)
        diffile = append_suffix(diffile, '.html')
        with diffile.open('w') as F:
            print(
                HEADER % str(Path()),
                H('h1', diffile),
                difftable,
                FOOTER,
                file=F
            )

    return f'{100*sim:.0f}%{NBSP}' + H('a', afile.name, href=diffile)



HEADER = """
<html>
<head>
<base href="%s" target="_blank">
<meta charset="UTF-8">
<title>Grading</title>
<style>
.diff td  { padding: 0 5 }  /* Perhaps: font-family: monospace */
.diff_sub { background-color: #FAA } /* left side only */
.diff_add { background-color: #FAA } /* right side only */
.diff_chg { background-color: #AFA } /* change */
.diff_column { white-space: pre-wrap; width: 50%% }
.results  { border-collapse: collapse }
.results th, .results td { border: 1px black solid; padding: 5; vertical-align: top }
.results pre { font-size: smaller; white-space: pre-wrap }
.nowrap { white-space: nowrap }
.grey { opacity: 0.5 }
</style>
</head>
<body>
"""

FOOTER = """
</body>
</html>
"""

NBSP = '&nbsp;'

def joinBR(lines):
    return '<br/>'.join(l for l in lines if l)

def H(elem, content, **attrs):
    if isinstance(content, list):
        content = '\n'.join(content)
    if 'klass' in attrs:
        attrs['class'] = attrs['klass']
        del attrs['klass']
    attrs = ''.join(f' {k}="{str(v)}"' for k,v in attrs.items())
    return f'<{elem}{attrs}>{content}</{elem}>'



def readfile(fil):
    with fil.open("br") as F:
        bstr = F.read()
    try:
        return bstr.decode()
    except UnicodeDecodeError:
        try:
            return bstr.decode(encoding="latin1")
        except UnicodeDecodeError:
            return bstr.decode(errors="replace")


GOLD = '.gold'

def read_args():
    parser = argparse.ArgumentParser(description='Split the downloaded Canvas submissions into groups.')
    parser.add_argument('labgroups', metavar='group', nargs='*',
                        help='the lab groups to check (default: all)')
    parser.add_argument('--skeleton', metavar='DIR', required=True, type=Path,
                        help='the folder containing the code templates, and the data directories')
    parser.add_argument('--solution', metavar='DIR', required=True, type=Path,
                        help='the folder containing the solution')
    parser.add_argument('--dir', metavar='DIR', required=True, type=Path,
                        help='the folder containing the prepared submissions')
    parser.add_argument('--testfile', metavar='PY', type=argparse.FileType('r'),
                        help='the python file containing the test scripts')
    parser.add_argument('--timeout', metavar='T', type=int, default=5, 
                        help='the timeout (in seconds) for running test scripts (default: 5)')
    args = parser.parse_args()

    assert args.dir.is_dir(), "The --dir folder must exist!"
    assert args.skeleton.is_dir(), "The --skeleton folder must exist!"
    assert args.solution.is_dir(), "The --solution folder must exist!"

    def labgroup_sortkey(g):
        digs = re.sub(r'\D', '', g)
        n = int(digs) if digs else 0
        return (n, g)

    if not args.labgroups:
        args.labgroups = [f.name for f in args.dir.iterdir()]
    args.labgroups.sort(key=labgroup_sortkey)
    return args


def main():
    cfg = read_args()

    cfg.templates = [f.name for f in cfg.skeleton.iterdir() if f.is_file()]
    cfg.required = [f.name for f in cfg.solution.iterdir()]
    cfg.datadirs = [f.name for f in cfg.skeleton.iterdir() if f.is_dir()]
    if cfg.testfile:
        testdict = {}
        exec(cfg.testfile.read(), testdict)
        cfg.testscripts = testdict['tests']
    else:
        cfg.testscripts = []

    cfg.labname = cfg.skeleton.name
    cfg.labfiles = set(cfg.required)

    # cfg.group_students = {}
    # lab_students = json.loads(cfg.students.read())
    # for st in lab_students.values():
    #     cfg.group_students.setdefault(st['group'], []).append(st['sortname'])

    autograde_all(cfg)


if __name__ == '__main__':
    main()

