import csv
from pathlib import Path
import PyPDF2
import shlex
import shutil
import subprocess

import general
import exam_uploader

selectors_file = exam_uploader.exam_dir / 'selectors.txt'
packaged_dir = exam_uploader.exam_dir / 'packaged'
sol_dir = exam_uploader.exam_dir / 'sol'

questions = [i + 1 for i in range(9)]
omit = {9}
questions_actual = set(questions) - omit

def format_range(range, adjust = False):
    (a, b) = range
    return f'{a + 1}-{b}'

def parse_range(s):
    return tuple(map(int, s.split('-')))

def format_ranges(ranges, adjust = False):
    if not ranges:
        return 'missing'
    return ','.join(map(lambda range: format_range(range, adjust = adjust), ranges))

def parse_ranges(s):
    if s == 'missing':
        return []
    return list(map(parse_range, s.split(',')))

def generate_selectors(questions, num_pages, starts, omit):
    def next(q):
        i = q + 1
        while i not in starts and i in questions:
            i = i + 1
        return i

    return dict((q, [(starts[q], starts.get(next(q), num_pages))] if q in starts else []) for q in questions if not q in omit)

def read_selectors(file):
    lines = general.read_without_comments(file)
    return dict(
        (entry['ID'], (entry['type'], dict((int(k), parse_ranges(v)) for (k, v) in entry.items() if k.isdigit() if v != None)))
        for entry in csv.DictReader(lines, dialect = csv.excel_tab)
    )

def to_selectors(starts, num_pages):
    return generate_selectors(
        questions,
        num_pages,
        dict((k, general.from_singleton(v)) for (k, v) in starts.items() if v),
        omit
    )

def find_selectors(file, strict = True):
    pdf = PyPDF2.PdfFileReader(str(file), strict = False)
    num_pages = pdf.getNumPages()

    to_pages = dict((i, []) for i in questions)
    to_pages_strict = dict((i, []) for i in questions)
    
    for i in range(num_pages):
        text = subprocess.run(['pdftotext', '-f', str(i + 1), '-l', str(i + 1), str(file), '-'], stdout = subprocess.PIPE, encoding = 'utf-8', check = True).stdout.strip()
        for q in questions:
            qt = f'Question {q}'
            if text.startswith(qt):
                to_pages_strict[q].append(i)
            if qt in text:
                to_pages[q].append(i)

    return to_selectors(to_pages_strict if strict else to_pages, num_pages)

def calculate_selectors():
    specified = read_selectors(selectors_file)

    def process(dir):
        id = dir.name
        s = specified.get(id)
        if s and s[0] == 'manual':
            return s[1]

        file = dir / 'submission.pdf'
        pdf = PyPDF2.PdfFileReader(str(file), strict = False)
        num_pages = pdf.getNumPages()

        to_pages = dict((i, []) for i in questions)
        to_pages_strict = dict((i, []) for i in questions)

        for i in range(num_pages):
            text = subprocess.run(['pdftotext', '-f', str(i + 1), '-l', str(i + 1), str(file), '-'], stdout = subprocess.PIPE, encoding = 'utf-8', check = True).stdout.strip()
            for q in questions:
                qt = f'Question {q}'
                if text.startswith(qt):
                    to_pages_strict[q].append(i)
                if qt in text:
                    to_pages[q].append(i)

        yes_strict = all (len(pages) == 1 for pages in to_pages_strict.values())
        if yes_strict and to_pages_strict[1] == [0]:
            return to_selectors(to_pages_strict, num_pages)

        yes_substrict = all (len(pages) <= 1 for pages in to_pages_strict.values())
        if yes_substrict and s[0] == 'okay':
            return to_selectors(to_pages, num_pages)

        subprocess.run(['evince', str(file)], check = True)

    return dict((dir.name, process(dir)) for dir in exam_uploader.submissions_dir.iterdir())

def read_lookup():
    return exam_uploader.read_lookup(exam_uploader.lookup_file)

def print_handles():
    for (i, j, _, _) in read_lookup():
        print(f'V{i}N{j}')

def extract_from_pdf(source, target, ranges):
    if ranges:
        cmd = ['pdfjam', '--keepinfo', '--outfile', str(target), str(source), format_ranges(ranges, adjust = True)]
        print(shlex.join(cmd))
        subprocess.run(cmd, check = True)

def solution_file(i):
    return sol_dir / str(i) / 'test.pdf'

#selectors = calculate_selectors()
print(selectors['REDACTED_GU_EMAIL'])

for (i, j, integration_id, name) in read_lookup():
    if integration_id == 'REDACTED_GU_EMAIL':
        print(i, j)

def package_submissions():
    #solution_selectors = dict((i, find_selectors(solution_file(i))) for i in range(20))
    selectors = calculate_selectors()
    #general.mkdir_fresh(packaged_dir)

    for q in [7]:#questions_actual:
        question_dir = packaged_dir / f'Q{q}'
        #question_dir.mkdir()
        for i in range(20):
            version_dir = question_dir / f'V{i}'
            version_dir.mkdir()
            #extract_from_pdf(solution_file(i), version_dir / 'solution.pdf', solution_selectors[i][q])

    if False:
        question_dir = packaged_dir / 'original'
        for i in range(20):
            version_dir = question_dir / f'V{i}'
            version_dir.mkdir()

    for (i, j, integration_id, name) in read_lookup():
        #if integration_id == 'REDACTED_GU_EMAIL':
            for q in [7]:#questions_actual:
                file = packaged_dir / f'Q{q}' / f'V{i}' / f'N{j}.pdf'
                ranges = selectors[integration_id][q]
                extract_from_pdf(exam_uploader.submissions_dir / integration_id / 'submission.pdf', file, ranges)

            if False:
                file = packaged_dir / 'original' / f'V{i}' / f'N{j}.pdf'
                shutil.copy(exam_uploader.submissions_dir / integration_id / 'submission.pdf', file)
