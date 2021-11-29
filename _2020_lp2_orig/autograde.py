import json
import difflib
import re
import os
import os.path
from os.path import join as pjoin, basename, dirname, isdir, isfile, relpath
import shutil
import subprocess
import argparse
from glob import glob


# Set this to False if you haven't installed diff2html-cli:
#   https://www.npmjs.com/package/diff2html-cli
# (or if you want to use Python's internal difflib of some reason)
USE_GIT_DIFF2HTML = True

def autograde_all(cfg):
    os.mkdir(cfg.outfolder)
    rows = [H('tr', [
        H('th', 'Group'),
        H('th', 'Late'),
        H('th', 'Members'),
        H('th', 'Missing'),
        H('th', 'Unknown'),
        H('th', 'Compared with skeleton'),
        H('th', 'Compared with solution'),
        H('th', 'Compared with previous') if cfg.previous else '',
        H('th', 'Test output') if cfg.testfile else '',
        H('th', 'Compilation & runtime errors' if cfg.testfile else 'Compilation errors'),
    ])]
    for group in cfg.labgroups:
        print(group)
        rows += [autograde(group, cfg)]

    with open(pjoin(cfg.outfolder, 'index.html'), 'w') as OUT:
        print(
            HEADER % relpath(os.curdir, cfg.outfolder),
            H('h1', f'{cfg.labname} autograding: {basename(cfg.submissions.rstrip("/"))}'),
            H('p', ['Files to submit:', H('strong', ', '.join(sorted(cfg.required)))]),
            H('p', ['Total submissions:', H('strong', str(len(cfg.labgroups)))]),
            H('table', rows, klass = 'results'),
            FOOTER,
            file = OUT
        )

def copy_submission_to_outfolder(f, outfolder, cfg):
    # upper-/lowercase of destination should depend on what is required
    src = basename(f)
    for dest in cfg.templates + cfg.required:
        if src.lower() == dest.lower():
            break
        else:
            dest = src
    # copy the file contents
    content = readfile(f)
    if f.endswith('.java'):
        # remove packages in java files
        content = re.sub(r'^(package[^;]*;)', r'/* \1 */', content)
    with open(pjoin(outfolder, dest), 'w') as F:
        print(content, file = F)
    return src, dest

def autograde(group, cfg):
    group = group.replace(LATE, '')
    late_submission = isdir(pjoin(cfg.submissions, group + LATE))
    outfolder = pjoin(cfg.outfolder, group)
    os.mkdir(outfolder)

    # Copy template files to outfilder
    for f in cfg.templates:
        shutil.copyfile(pjoin(cfg.skeleton, f), pjoin(outfolder, f))
    for f in cfg.datadirs:
        os.symlink(relpath(pjoin(cfg.skeleton, f), outfolder), pjoin(outfolder, f))

    # Copy submitted files to outfolder
    submitted = {}
    for d in [cfg.previous, cfg.submissions]:
        if not d:
            continue
        for f in glob(pjoin(d, group, '*.*')) + glob(pjoin(d, group + LATE, '*.*')):
            src, dest = copy_submission_to_outfolder(f, outfolder, cfg)
            submitted[dest] = f

    # Create the result table row
    row = [
        # Group
        H('td', [group.replace(' ', NBSP)]),

        # Late
        H('td', ['LATE' if late_submission else '']),

        # Members
        H('td', joinBR(sorted(cfg.group_students[group]))),

        # Missing
        H('td', joinBR(
            H('a', f, href = pjoin(cfg.solution, f))
            for f in cfg.required if f not in submitted
        )),

        # Unknown
        H('td', joinBR(
            H('a', f, href = pjoin(outfolder, f))
            for f in sorted(submitted) if f not in cfg.templates and f not in cfg.required
        )),

        # Compared with skeleton
        H('td', joinBR(
            diff_and_link(
                pjoin(outfolder, f), pjoin(cfg.skeleton, f),
                'SUBMISSION', 'SKELETON', pjoin(outfolder, f),
            )
            for f in sorted(submitted) if f in cfg.templates and f not in cfg.required
        )),

        # Compared with solution
        H('td', joinBR(
            diff_and_link(
                pjoin(outfolder, f), pjoin(cfg.solution, f),
                'SUBMISSION', 'SOLUTION', pjoin(outfolder, f),
            )
            for f in sorted(submitted) if f in cfg.required
        )),
    ]

    # If there are previous submissions
    if cfg.previous:
        row += [
            H('td', joinBR(
                diff_and_link(
                    pjoin(outfolder, f), pjoin(cfg.previous, group, f),
                    'NEW SUBMISSION', 'PREVIOUS', pjoin(outfolder, f + '.prev')
                )
                for f, original in sorted(submitted.items())
                if original.startswith(cfg.submissions)
                if isfile(pjoin(cfg.previous, group, basename(original)))
            )),
        ]

    # Compile java files
    print(' - compile java files')
    javafiles = list(f for f in set(submitted) | set(cfg.templates) | set(cfg.required) if f.endswith('.java'))
    process = subprocess.run(['javac'] + javafiles, cwd = outfolder, capture_output = True)
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
        print(' - run tests', end = '', flush = True)
        for outfile, script in cfg.testscripts:
            print(' .', end = '', flush = True)
            if isinstance(script, str):
                script = script.split()
            try:
                process = subprocess.run(script, cwd = outfolder, timeout = cfg.timeout, capture_output = True)
            except subprocess.TimeoutExpired:
                print('timeout', end = '', flush = True)
                runtime_errors += [
                    H('strong', f'Timeout (>{cfg.timeout}s): {outfile}'),
                ]
                continue
            if process.returncode:
                print('error', end = '', flush = True)
                errlines = process.stderr.decode().splitlines(keepends = True)
                del errlines[30:]
                runtime_errors += [
                    H('strong', f'Runtime error: {outfile}'),
                    H('pre', ''.join(errlines)),
                ]
            with open(pjoin(outfolder, outfile), 'a') as F:
                print(f'===== {" ".join(script)[:70]}...', file = F)
                print(process.stdout.decode(), file = F)
                if process.stderr:
                    print(file=F)
                    print(' STDERR '.center(60, '='), file = F)
                    print(process.stderr.decode(), file = F)
                print(file = F)
        print()

        row += [
            H('td', joinBR(
                diff_and_link(
                    pjoin(outfolder, f), pjoin(dirname(cfg.testfile.name), f + GOLD),
                    'OUT', 'GOLD', pjoin(outfolder, f),
                )
                for f in sorted(set(f for (f, _) in cfg.testscripts))
            )),
            H('td', joinBR(runtime_errors)),
        ]

    else:
        # No compilation errors, and no test script
        row += [H('td', '')]

    return H('tr', '\n'.join(row))

GIT_DIFF_CMD = 'git diff --no-index --histogram --unified=1000 --ignore-space-at-eol'.split()
DIFF2HTML_CMD = 'diff2html --style side --summary open --input file'.split()

def diff_and_link(afile, bfile, atitle, btitle, diffile):
    diffile += '.diff'
    try:
        atext = readfile(afile)
    except FileNotFoundError:
        return H('span', f'({basename(afile)})', klass = 'grey')
    try:
        btext = readfile(bfile)
    except FileNotFoundError:
        return H('span', f'({basename(bfile)})', klass = 'grey')
    if atext.strip() == btext.strip():
        diffile += '.txt'
        with open(diffile, 'w') as F:
            print(atext, file = F)
        return f'{NBSP}={NBSP}' + H('a', basename(afile), href = diffile, klass = 'grey')

    if USE_GIT_DIFF2HTML:
        cmd = GIT_DIFF_CMD + [afile, bfile]
        process = subprocess.run(cmd, capture_output = True)
        with open(diffile, 'wb') as F:
            F.write(process.stdout)
        difflines = process.stdout.splitlines()
        sim = 1 - sum(line.startswith(b'+') or line.startswith(b'-') for line in difflines) / len(difflines)
        cmd = DIFF2HTML_CMD + [
            '--highlightCode', str(afile.endswith('.java')).lower(),
            '--file', diffile + '.html',
            '--', diffile,
        ]
        subprocess.run(cmd)
        diffile += '.html'

    else:  # use difflib
        alines = atext.splitlines()
        blines = btext.splitlines()
        sim = difflib.SequenceMatcher(a = alines, b = blines).ratio()
        difftable = difflib.HtmlDiff().make_table(alines, blines, atitle, btitle)
        difftable = difftable.replace('<td nowrap="nowrap">', '<td class="diff_column">')
        difftable = difftable.replace(NBSP, ' ')
        # difftable = re.sub(r'(<span class="diff_(?:add|sub)">)(\s+)', r'\2\1', difftable)
        diffile += '.html'
        with open(diffile, 'w') as F:
            print(
                HEADER % '.',
                H('h1', diffile),
                difftable,
                FOOTER,
                file = F,
            )

    return f'{100*sim:.0f}%{NBSP}' + H('a', basename(afile), href = diffile)

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
    return '<br/>'.join(line for line in lines if line)

def H(elem, content, **attrs):
    if isinstance(content, list):
        content = '\n'.join(content)
    if 'klass' in attrs:
        attrs['class'] = attrs['klass']
        del attrs['klass']
    attrs = ''.join(f' {k}="{v}"' for (k, v) in attrs.items())
    return f'<{elem}{attrs}>{content}</{elem}>'

def readfile(fil):
    with open(fil, "br") as F:
        bstr = F.read()
    try:
        return bstr.decode()
    except UnicodeDecodeError:
        try:
            return bstr.decode(encoding = "latin1")
        except UnicodeDecodeError:
            return bstr.decode(errors = "replace")

LATE = ' LATE'
GOLD = '.gold'

def read_args():
    parser = argparse.ArgumentParser(description='Split the downloaded Canvas submissions into groups.')
    parser.add_argument('labgroups', metavar = 'group', nargs = '*',
                        help='the lab groups to check (default: all)')
    parser.add_argument('--students', metavar = 'JSON', type = argparse.FileType('r'), required = True,
                        help = 'json file with student data')
    parser.add_argument('--skeleton', metavar = 'DIR', required = True,
                        help = 'the folder containing the code templates, and the data directories')
    parser.add_argument('--solution', metavar = 'DIR', required = True,
                        help = 'the folder containing the solution')
    parser.add_argument('--submissions', metavar = 'DIR', required = True,
                        help = 'the folder containing the (cleaned) submissions')
    parser.add_argument('--previous', metavar = 'DIR',
                        help = 'the folder containing the previous submissions (if this is a resubmission)')
    parser.add_argument('--testfile', metavar = 'PY', type = argparse.FileType('r'),
                        help = 'the python file containing the test scripts')
    parser.add_argument('--timeout', metavar = 'T', type = int, default = 5,
                        help = 'the timeout (in seconds) for running test scripts (default: 5)')
    parser.add_argument('--out', metavar = 'DIR', dest = 'outfolder', required = True,
                        help = 'the destination folder (must not exist)')
    args = parser.parse_args()

    assert isdir(args.skeleton), "The --skeleton folder must exist!"
    assert isdir(args.submissions), "The --submissions folder must exist!"
    assert isdir(args.solution), "The --solution folder must exist!"
    if args.previous:
        assert isdir(args.previous), "The --previous folder must exist!"
    assert not os.path.exists(args.outfolder), "The --out folder must not exist!"

    def labgroup_sortkey(g):
        digs = re.sub(r'\D', '', g)
        n = int(digs) if digs else 0
        return (n, g)

    if not args.labgroups:
        args.labgroups = [basename(f) for f in glob(pjoin(args.submissions, '*'))]
    args.labgroups.sort(key = labgroup_sortkey)
    return args

def main():
    cfg = read_args()

    cfg.templates = [basename(f) for f in glob(pjoin(cfg.skeleton, '*.*'))]
    cfg.required = [basename(f) for f in glob(pjoin(cfg.solution, '*.*'))]
    cfg.datadirs = [basename(f) for f in glob(pjoin(cfg.skeleton, '*')) if isdir(f)]
    if cfg.testfile:
        testdict = {}
        exec(cfg.testfile.read(), testdict)
        cfg.testscripts = testdict['tests']
    else:
        cfg.testscripts = []

    cfg.labname = basename(cfg.skeleton.rstrip('/'))
    cfg.labfiles = set(basename(f) for f in glob(pjoin(cfg.solution, 'solution', '*.*')))

    cfg.group_students = {}
    lab_students = json.loads(cfg.students.read())
    for st in lab_students.values():
        cfg.group_students.setdefault(st['group'], []).append(st['sortname'])

    autograde_all(cfg)

if __name__ == '__main__':
    main()
