#!/usr/bin/env python
# PYTHON_ARGCOMPLETE_OK

# We defer expensive initialization to after argument parsing is done.
# This makes bash completion more responsive.
import argparse
from pathlib import Path
import shlex

import lab_assignment_constants

dir_script = Path(__file__).parent
cache_dir_default = dir_script / 'cache'
file_auth_token_default = dir_script / 'auth_token'

p = argparse.ArgumentParser(add_help = False, description = '\n'.join([
    f'Display assignment comments ordered by recency.',
]), epilog = '\n'.join([
    f'This Python script supports bash completion.',
    f'For this, python-argparse needs to be installed and configured.',
    f'See https://github.com/kislyuk/argcomplete for more information.',
]))

p.add_argument('lab', type = int, choices = [1, 2, 3, 4], help = 'The lab to process.')
p.add_argument('out', type = Path, help = '\n'.join([
    f'The path of the HTML file to produce.',
]))

p.add_argument('-h', '--help', action = 'help', help = '\n'.join([
    f'Show this help message and exit.',
]))
p.add_argument('-v', '--verbose', action = 'store_true', help = '\n'.join([
    f'Print INFO level logging.',
    f'This includes accesses to Canvas API endpoints.',
]))
p.add_argument('--auth-token-file', type = str, default = file_auth_token_default, help = '\n'.join([
    f'Path to a file storing the Canvas authentication token.',
    f'Defaults to {shlex.quote(str(file_auth_token_default))}.',
]))
p.add_argument('--cache-dir', type = str, default = cache_dir_default, help = '\n'.join([
    f'The cache directory to use.',
    f'If it does not exist, it will be created.',
    f'Defaults to {shlex.quote(str(cache_dir_default))}.',
]))
p.add_argument('--groups', nargs = '+', type = str, help = '\n'.join([
    f'Restrict processing to these groups.',
]))
p.add_argument('--no-preview', action = 'store_true', help = '\n'.join([
    f'After finishing processing, do not open the overview index file in a webbrowser tab.'
]))

#Support for argcomplete.
try:
    import argcomplete
    argcomplete.autocomplete(p)
except ModuleNotFoundError:
    pass

args = p.parse_args()
# Argument parsing is done: expensive initialization can start now.

import datetime
import logging
import os
import shutil
import webbrowser

from dominate import document
from dominate.tags import *
from dominate.util import raw, text

from general import print_error, print_json
from canvas import Canvas, GroupSet, Course, Assignment
from lab_assignment import LabAssignment
import config

logging.basicConfig()
if args.verbose:
    logging.getLogger().setLevel(logging.INFO)
else:
    logging.getLogger().setLevel(25)

canvas = Canvas(config.canvas_url, cache_dir = Path(args.cache_dir))
group_set = GroupSet(canvas, config.course_id, config.group_set, use_cache = True)
lab_assignment = LabAssignment(canvas, config.course_id, args.lab, use_name_handlers = None, use_content_handlers = None)
lab_assignment.collect_submissions(use_cache = True)

groups = lab_assignment.parse_groups(args.groups) if args.groups else list(lab_assignment.submissions.keys())

def comment_date(comment):
    return comment.edited_at_date if comment.edited_at else comment.created_at_date

def sort_key(group):
    s = lab_assignment.submissions[group]
    if not s.comments:
        return datetime.min

    return comment_date(s.comments[-1])

def get_item_end(lines, start):
    if not (len(lines[start]) >= 2 and lines[start][0] in {'*', '+', '-'} and lines[start][1] == ' '):
        return start

    i = start + 1
    while i != len(lines) and lines[i].startswith('  '):
        i = i + 1
    return i

def get_quote_end(lines, start):
    i = start
    while i != len(lines) and lines[i].startswith('> '):
        i = i + 1
    return i

def group_items_into_lists(objects):
    r = list()
    list_start = 0

    def finish_list(list_end, new_start):
        nonlocal list_start
        if list_start != list_end:
            r.append(ul(objects[list_start : list_end]))
        list_start = new_start

    for i in range(len(objects)):
        if not isinstance(objects[i], li):
            finish_list(i, i + 1)
            r.append(objects[i])
    finish_list(len(objects), len(objects))
    return r

def break_on(sep, xs):
    r = [[]]
    for x in xs:
        if x == sep:
            if len(r[-1]) != 0:
                r.append(list())
        else:
            r[-1].append(x)
    if len(r[-1]) == 0:
        r.pop()
    return r

def format_comment(lines):
    print('NEW CALL')
    for line in lines:
        print(line)
    print('==============')

    objects = list()
    i = 0
    start_new_paragraph = True
    while i != len(lines):
        j = get_quote_end(lines, i)
        if j != i:
            new_lines = [line[2:] for line in lines[i : j]]
            objects.append(pre('\n'.join(new_lines), style = 'white-space: pre-wrap'))
            i = j
            continue

        j = get_item_end(lines, i)
        if j != i:
            new_lines = [line[2:] for line in lines[i : j]]
            x = li(format_comment(new_lines))
            while len(objects) != 0 and objects[-1] == None:
                objects.pop()
            if len(objects) != 0 and isinstance(objects[-1], ul):
                objects[-1].add(x)
            else:
                objects.append(ul(x))
            i = j
            continue

        if not lines[i].strip():
            start_new_paragraph = True
            i = i + 1
            continue

        if True:
            if start_new_paragraph or not (len(objects) != 0 and isinstance(objects[-1], p)):
                objects.append(p())
                start_new_paragraph = False
            objects[-1].add(lines[i] + ' ')
            i = i + 1
            continue

    return objects

groups_sorted = sorted(groups, key = sort_key)

doc = document(title = 'Comments for {}.'.format(lab_assignment.name))

for group in groups_sorted:
    s = lab_assignment.submissions[group]
    div_group = doc.body.add(div(Class = 'group'))
    div_group.add(div(Class = 'group_name'))
    for comment in s.comments:
        div_comment = div_group.add(div())
        div_comment.add(div(comment_date(comment).isoformat(sep = ' ', timespec = 'minutes'), Class = 'date'))
        div_comment.add(div(format_comment(comment.comment.splitlines()), Class = 'message'))
        div_comment.add(div(comment.author.display_name, Class = 'user'))

out = Path(args.out)
out.write_text(doc.render())
if not args.no_preview:
    webbrowser.open(out.resolve().as_uri())






