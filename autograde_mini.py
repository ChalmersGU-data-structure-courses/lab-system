import json
import difflib
import re
import os
from os import access, X_OK
import os.path
from os.path import join as pjoin, basename, dirname, isdir, isfile, relpath, abspath
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
        H('th', 'Test output'),
        H('th', 'Runtime errors')
    ])]
    print("Model solution")
    autograde("solution", cfg.solution, cfg)
    for group in cfg.labgroups:
        print(group)
        if cfg.repo:
            submission = get_latest_submission(cfg.repo, group)
            submissionfolder = switch_to_submission(cfg.repo, group, submission)
            name = "%s %s" % (group, submission)
        else:
            submissionfolder=pjoin(cfg.submissions, group)
            name = group
        rows += [autograde(name, submissionfolder, cfg)]

    with open(pjoin(cfg.outfolder, 'index.html'), 'w') as OUT:
        print(
            HEADER,
            H('h1', f'{cfg.labname} autograding'),
            H('p', ['Files to submit:', H('strong', ', '.join(sorted(cfg.required)))]),
            H('p', ['Total submissions:', H('strong', str(len(cfg.labgroups)))]),
            H('table', rows, klass='results'),
            FOOTER,
            file=OUT
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
        print(content, file=F)
    return src, dest

def autograde(group, submissionfolder, cfg):
    outfolder = pjoin(cfg.outfolder, group)
    os.mkdir(outfolder)

    # Copy template files to outfolder
    for f in cfg.templates:
        shutil.copyfile(pjoin(cfg.problem, f), pjoin(outfolder, f))
    for f in cfg.datadirs:
        os.symlink(relpath(pjoin(cfg.problem, f), outfolder), pjoin(outfolder, f))

    # Copy submitted files to outfolder
    submitted = {}
    for f in glob(pjoin(submissionfolder, '*.*')):
        src, dest = copy_submission_to_outfolder(f, outfolder, cfg)
        submitted[dest] = f

    # Create the result table row
    row = [
        # Group
        H('td', [group.replace(' ', NBSP)])
    ]

    # Run test scripts
    runtime_errors = []
    print(f' - run tests', end='', flush=True)
    for script in cfg.testscripts:
        outfile = output(script)
        print(f' .', end='', flush=True)
        if isinstance(script, str):
            script = script.split()
        try:
            process = subprocess.run(script, cwd=outfolder, env=os.environ, timeout=cfg.timeout, capture_output=True)
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
        with open(pjoin(outfolder, outfile), 'a') as F:
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
            diff_and_link(pjoin(outfolder, f), pjoin(cfg.outfolder, "solution", f),
                              'OUT', 'GOLD', pjoin(outfolder, f), cfg)
            for f in sorted(set(output(f) for f in cfg.testscripts))
        )),
        H('td', joinBR(runtime_errors)),
    ]

    return H('tr', '\n'.join(row))

def output(script):
    return basename(script).split(".")[0] + ".out"


GIT_DIFF_CMD = 'git diff --no-index --histogram --unified=1000 --ignore-space-at-eol'.split()
DIFF2HTML_CMD = 'diff2html --style side --summary open --input file'.split()

def diff_and_link(afile, bfile, atitle, btitle, diffile, cfg):
    diffile += '.diff'
    diffurl = relpath(diffile, cfg.outfolder)
    try:
        atext = readfile(afile)
    except FileNotFoundError:
        print("not found:", afile)
        return H('span', f'({basename(afile)})', klass='grey')
    try:
        btext = readfile(bfile)
    except FileNotFoundError:
        return H('span', f'({basename(bfile)})', klass='grey')
    if atext.strip() == btext.strip():
        diffile += '.txt'
        with open(diffile, 'w') as F:
            print(atext, file=F)
        return f'{NBSP}={NBSP}' + H('a', basename(afile), href=diffurl, klass='grey')

    if USE_GIT_DIFF2HTML:
        cmd = GIT_DIFF_CMD + [afile, bfile]
        process = subprocess.run(cmd, capture_output=True)
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
        diffurl += '.html'

    else: # use difflib
        alines = atext.splitlines()
        blines = btext.splitlines()
        sim = difflib.SequenceMatcher(a=alines, b=blines).ratio()
        difftable = difflib.HtmlDiff().make_table(alines, blines, atitle, btitle)
        difftable = difftable.replace('<td nowrap="nowrap">', '<td class="diff_column">')
        difftable = difftable.replace(NBSP, ' ')
        # difftable = re.sub(r'(<span class="diff_(?:add|sub)">)(\s+)', r'\2\1', difftable)
        diffile += '.html'
        with open(diffile, 'w') as F:
            print(
                HEADER,
                H('h1', diffurl),
                difftable,
                FOOTER,
                file=F
            )

    return f'{100*sim:.0f}%{NBSP}' + H('a', basename(afile), href=diffurl)



HEADER = """
<html>
<head>
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
    attrs = ''.join(f' {k}="{v}"' for k,v in attrs.items())
    return f'<{elem}{attrs}>{content}</{elem}>'



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


def read_args():
    parser = argparse.ArgumentParser(description='Split the downloaded Canvas submissions into groups.')
    parser.add_argument('labgroups', metavar='group', nargs='*',
                        help='the lab groups to check (default: all)')
    parser.add_argument('--lab', metavar='DIR', required=True,
                        help='the folder containing the lab')
    parser.add_argument('--submissions', metavar='DIR', required=False,
                        help='the folder containing the submissions')
    parser.add_argument('--grading', metavar='DIR', required=False,
                        help='the folder containing the grading repository')
    parser.add_argument('--out', metavar='DIR', dest='outfolder', required=True,
                        help='the destination folder (must not exist)')
    parser.add_argument('--timeout', metavar='T', type=int, default=5, 
                        help='the timeout (in seconds) for running test scripts (default: 5)')
    args = parser.parse_args()

    assert isdir(args.lab), "The --lab folder must exist!"
    assert args.submissions or args.grading, "Either --submissions or --grading must be given!"
    assert not (args.submissions and args.grading), "Only one of --submissions or --grading may be given!"
    if args.submissions:
        args.repo = None
        assert isdir(args.submissions), "The --submissions folder must exist!"
    if args.grading:
        assert isdir(args.grading), "The --grading folder must exist!"

        from git import Repo
        args.repo = Repo(args.grading)
    assert not os.path.exists(args.outfolder), "The --out folder must not exist!"

    def labgroup_sortkey(g):
        digs = re.sub(r'\D', '', g)
        n = int(digs) if digs else 0
        return (n, g)

    if not args.labgroups:
        if args.repo:
            args.labgroups = list(set(get_lab_groups_from_repo(args.repo)))
        else:
            args.labgroups = [basename(f) for f in glob(pjoin(args.submissions, '*'))]
    args.labgroups.sort(key=labgroup_sortkey)
    return args

def get_lab_groups_from_repo(repo):
    # Get all lab groups - "group-38" etc. - may return duplicates
    for tag in repo.tags:
        path = tag.path
        if path.startswith("refs/tags/group-"):
            yield path.split("/")[2]

def get_latest_submission(repo, group):
    # Get the latest submission of a group
    latest_num = None
    latest_name = None

    for tag in repo.tags:
        name = tag.path
        if name.startswith("refs/tags/" + group + "/") and name.endswith("/tag"):
            submission_name = name.split("/")[3]
            sub = "submission"

            if submission_name[:len(sub)].lower() == sub:
                submission_num = int(submission_name[len(sub):].replace("-","").replace("_",""))
                if latest_num is None or latest_num < submission_num:
                    latest_num = submission_num
                    latest_name = submission_name
                    latest_fullname = name

    return latest_name

def switch_to_submission(repo, group, submission):
    # Switch to a particular submission. Returns the directory where
    # the submission can be found.

    assert not repo.is_dirty(), "The git repository has changes!"
    assert repo.untracked_files == [], "The git repository has untracked files!"

    repo.git.checkout("%s/%s/tag" % (group, submission))
    return repo.working_tree_dir

def main():
    # These are passed into the child process
    os.environ['PYTHONDONTWRITEBYTECODE']='1'
    if 'PYTHONPATH' in os.environ:
        os.environ['PYTHONPATH'] += ':.'
    else:
        os.environ['PYTHONPATH'] = '.'

    cfg = read_args()

    cfg.problem = pjoin(cfg.lab, "problem")
    cfg.solution = pjoin(cfg.lab, "solution")
    cfg.testdir = pjoin(cfg.lab, "test")
    cfg.templates = [basename(f) for f in glob(pjoin(cfg.problem, '*.*'))]
    cfg.required = [basename(f) for f in glob(pjoin(cfg.solution, '*.*'))]
    cfg.datadirs = [basename(f) for f in glob(pjoin(cfg.problem, '*')) if isdir(f)]
    cfg.testscripts = [abspath(f) for f in glob(pjoin(cfg.testdir, '*')) if isfile(f) and access(f, X_OK)]

    cfg.labname = open(pjoin(cfg.lab, "name")).read().strip()
    cfg.labfiles = set(basename(f) for f in glob(pjoin(cfg.solution, 'solution', '*.*')))

    autograde_all(cfg)


if __name__ == '__main__':
    main()

