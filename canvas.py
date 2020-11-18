import json
from types import SimpleNamespace
import requests
import urllib.parse
from pathlib import PurePath, Path
import re
from datetime import datetime, timedelta, timezone
from collections import defaultdict
import sys
import logging
import os

import simple_cache

logger = logging.getLogger("canvas")

################################################################################
# General purpose functions (could be in a tools module)

def unique_by(f, xs):
    rs = list()
    for x in xs:
        if not any(f(x, r) for r in rs):
            rs.append(x)

    return rs

class JSONObject(SimpleNamespace):
    DATE_PATTERN = re.compile("[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._dict = kwargs

        for key in kwargs:
            value = str(kwargs[key])
            # idea from canvasapi/canvas_object.py
            if JSONObject.DATE_PATTERN.match(value):
                t = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo = timezone.utc)
                new_key = key + "_date"
                self.__setattr__(new_key, t)

class JSONEncoderForJSONObject(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, JSONObject):
            return obj._dict

def print_json(x):
    print(json_encoder.encode(x))

json_encoder = JSONEncoderForJSONObject(indent = 4, sort_keys = True)

def write_lines(file, lines):
    for line in lines:
        file.write(line)
        file.write('\n')

def print_error(*objects, sep = ' ', end = '\n'):
    print(*objects, sep = sep, end = end, file = sys.stderr)

def set_modification_time(path, date):
    t = date.timestamp()
    os.utime(path, (t, t))

################################################################################
# Canvas stuff stars here

class Canvas:
    def __init__(self, domain, auth_token = Path("AUTH_TOKEN"), cache_dir = Path("cache")):
        if isinstance(auth_token, Path):
            try:
                self.auth_token = auth_token.open().read().strip()
            except FileNotFoundError:
                print_error('No Canvas authorization token found.')
                print_error('Expected Canvas authorization token in file {}.'.format(auth_token))
                exit(1)
        else:
            self.auth_token = auth_token

        self.domain = domain
        self.cache = simple_cache.SimpleCache(cache_dir)

        self.base_url = 'https://' + self.domain
        self.base_url_api = self.base_url + '/api/v1'
        self.session = requests.Session()
        self.session.headers.update({ 'Authorization': 'Bearer {}'.format(self.auth_token) })

    # internal
    @staticmethod
    def get_cache_path(endpoint, params):
        p = PurePath(*(map(str, endpoint)))
        n = p.name
        if bool(params):
            n = n + "?" + urllib.parse.urlencode(params)
        return p.with_name(n)

    # internal
    def get_url(self, endpoint):
        return self.base_url + "/" + str(PurePath(*(map(str, endpoint))))

    # internal
    @staticmethod
    def with_api(endpoint):
        return ['api', 'v1'] + endpoint

    # internal
    @staticmethod
    def objectify_json(x):
        return json.loads(json.dumps(x), object_hook = lambda x: JSONObject(**x))

    # internal
    @staticmethod
    def get_response_json(response):
        response.raise_for_status()
        return response.json()

    # internal
    def get_json(self, endpoint, params = dict()):
        r = self.session.get(self.get_url(Canvas.with_api(endpoint)), params = params)
        return Canvas.get_response_json(r)

    # internal
    def get_list_json(self, endpoint, params = dict()):
        p = params.copy()
        p['per_page'] = '100'
        r = self.session.get(self.get_url(Canvas.with_api(endpoint)), params = p)
        x = Canvas.get_response_json(r)
        while 'next' in r.links:
            r = self.session.get(r.links['next']['url'], headers = {'Authorization': 'Bearer {}'.format(self.auth_token)})
            x.extend(Canvas.get_response_json(r))
        return x;

    # internal
    def json_cacher(self, method):
        def f(endpoint, params = dict(), use_cache = True):
            logger.log(logging.INFO, 'accessing endpoint ' + self.get_url(Canvas.with_api(endpoint)))
            return Canvas.objectify_json(self.cache.with_cache_json(Canvas.get_cache_path(Canvas.with_api(endpoint), params), lambda: method(endpoint, params), use_cache))
        return f

    def get(self, endpoint, params = dict(), use_cache = True):
        return self.json_cacher(self.get_json)(endpoint, params, use_cache)

    def get_list(self, endpoint, params = dict(), use_cache = True):
        return self.json_cacher(self.get_list_json)(endpoint, params, use_cache)

    # internal
    def get_file_bare(self, id, verifier, use_cache = True):
        endpoint = ['files', id, 'download']
        params = {'verifier': verifier}
        logger.log(logging.INFO, 'accessing endpoint ' + self.get_url(endpoint))

        def constructor(file_path):
            r = self.session.get(self.get_url(endpoint), params = params)
            r.raise_for_status()
            with open(file_path, 'wb') as file:
                file.write(r.content)

        return self.cache.with_cache_file(Canvas.get_cache_path(endpoint, params), constructor, use_cache)

    # internal
    @staticmethod
    def parse_verifier(url):
        r = urllib.parse.urlparse(url)
        return urllib.parse.parse_qs(r.query)['verifier'][0]

    def get_file(self, file_descr, use_cache = True):
        return self.get_file_bare(file_descr.id, Canvas.parse_verifier(file_descr.url), use_cache)

    def place_file(self, target, file_descr, use_cache = True):
        source = self.get_file(file_descr, use_cache)
        target.write_bytes(source.read_bytes())
        set_modification_time(target, file_descr.modified_at_date)

    def courses(self):
        return self.get_list(['courses'])

class Course:
    def __init__(self, canvas, course_id):
        self.canvas = canvas
        self.course_id = course_id

    def assignments(self):
        return self.canvas.get_list(['courses', self.course_id, 'assignments'])

    def select_assignment(self, assignment_name):
        xs = list(filter(lambda assignment: assignment.name.lower().startswith(assignment_name.lower()), self.assignments()))
        if len(xs) == 1:
            return xs[0]

        if not xs:
            print_error('No assigments found fitting \'{}\'.'.format(assignment_name))
        else:
            print_error('Multiple assignments found fitting \'{}\':'.format(assignment_name))
            for assignment in xs:
                print_error('  ' + assignment.name)
        exit(1)

class Groups:
    def __init__(self, canvas, groupset):
        self.canvas = canvas
        self.groupset = groupset

        self.group_details = dict()
        self.group_name_to_id = dict()
        self.group_users = dict()
        self.user_to_group = dict()

        for group in canvas.get_list(['group_categories', groupset, 'groups']):
            self.group_details[group.id] = group;
            self.group_name_to_id[group.name] = group.id
            users = set()
            for user in canvas.get_list(['groups', group.id, 'users']):
                users.add(user.id)
                self.user_to_group[user.id] = group.id
                self.group_users[group.id] = users

class Assignment:
    def __init__(self, canvas, course_id, assignment_id):
        self.canvas = canvas
        self.course_id = course_id

        if isinstance(assignment_id, str):
            self.assignment_id = Course(canvas, course_id).select_assignment(assignment_id).id
        else:
            self.assignment_id = assignment_id

        self.assignment = canvas.get(['courses', course_id, 'assignments', self.assignment_id])
        self.groups = Groups(canvas, self.assignment.group_category_id)

    @staticmethod
    def is_duplicate_comment(a, b):
        return a.author_id == b.author_id and a.comment == b.comment and abs(a.created_at_date - b.created_at_date) < timedelta(minutes = 1)

    @staticmethod
    def merge_comments(comments):
        return unique_by(Assignment.is_duplicate_comment, comments)

    def build_submissions(self):
        submissions_by_group = defaultdict(lambda: dict())
        for submission in self.canvas.get_list(['courses', self.course_id, 'assignments', self.assignment_id, 'submissions'], params = {'include[]': ['submission_comments', 'submission_history']}):
            if submission.workflow_state != 'unsubmitted':
                if (not submission.user_id in self.groups.user_to_group):
                    print_error(f'user_id {submission.user_id} submitted despite not being in a group; ignoring')
                else:
                    submissions_by_group[self.groups.user_to_group[submission.user_id]][submission.user_id] = submission

        self.submissions = dict()
        for group in submissions_by_group:
            first_user = self.groups.group_details[group].leader.id
            submissions_this_group = submissions_by_group[group]

            all_comments = list()
            for user in submissions_this_group:
                all_comments.extend(submissions_this_group[user].submission_comments)
    
            # sanity check
            attempts_set = set()
            for user in submissions_this_group:
                attempts_set.add(tuple(map(lambda old_submission: old_submission.attempt, submissions_this_group[user].submission_history)))
                if len(attempts_set) != 1:
                    print_error(f'incongruous submissions for members of group {group} [{group_details[group].name}]')
                    exit(1)

            r = SimpleNamespace();
            r.submissions = submissions_this_group[user].submission_history
            r.comments = Assignment.merge_comments(all_comments)
            self.submissions[group] = r

    @staticmethod
    def current_submission(s):
        return s.submissions[-1]

    @staticmethod
    def first_ungraded(s):
        for i in reversed(range(len(s.submissions))):
            if s.submissions[i].workflow_state == 'graded':
                return i + 1

        return 0

    @staticmethod
    def last_graded_submission(s):
        i = Assignment.first_ungraded(s)
        if i == 0:
            return None

        return s.submissions[i - 1]

    @staticmethod
    def graded_comments(s):
        last_graded = Assignment.last_graded_submission(s)
        def is_new(date):
            return last_graded == None or date - last_graded.graded_at_date >= timedelta(minutes = 5)

        return list(filter(lambda comment: not is_new(comment.created_at_date), s.comments))

    @staticmethod
    def ungraded_comments(s):
        last_graded = Assignment.last_graded_submission(s)
        def is_new(date):
            return last_graded == None or date - last_graded.graded_at_date >= timedelta(minutes = 5)

        return list(filter(lambda comment: is_new(comment.created_at_date), s.comments))

    @staticmethod
    def get_files(submissions):
        files = dict()
        for submission in submissions:
            for attachment in submission.attachments:
                files[attachment.filename] = attachment

        return files.values()

    @staticmethod
    def get_graded_files(s):
        return Assignment.get_files(s.submissions[:Assignment.first_ungraded(s)])

    @staticmethod
    def get_current_files(s):
        return Assignment.get_files(s.submissions)

    @staticmethod
    def write_comments(path, comments):
        if comments:
            with open(path, 'w') as file:
                for comment in comments:
                    write_lines(file, [
                        '=' * 80,
                        '',
                        comment.author.display_name,
                        comment.created_at,
                        '',
                        comment.comment,
                    ])
            set_modification_time(path, comments[-1].created_at_date)

    def create_submission_dir(self, dir, submission, files):
        dir.mkdir()
        #set_modification_time(dir, submission.submitted_at_date)
        for file in files:
            self.canvas.place_file(dir / file.filename, file)

    def prepare_submission(self, deadline, dir, s):
        current = Assignment.current_submission(s)
        self.create_submission_dir(dir, current, Assignment.get_current_files(s))
        Assignment.write_comments(dir / 'new-comments.txt', Assignment.ungraded_comments(s))

        last_graded = Assignment.last_graded_submission(s)
        if last_graded != None:
            prev_dir = dir / 'previous'
            self.create_submission_dir(prev_dir, last_graded, Assignment.get_graded_files(s))
            Assignment.write_comments(prev_dir / 'comments.txt', Assignment.graded_comments(s))

        if deadline != None:
            time_diff = current.submitted_at_date - deadline
            if time_diff >= timedelta(minutes = 5):
                late_path = dir / 'LATE'
                with open(late_path, 'w') as file:
                    write_lines(file, ['{:.2f} hours'.format(time_diff / timedelta(hours=1))])
                set_modification_time(late_path, current.submitted_at_date)

    def prepare_submissions(self, dir, deadline = None):
        #self.build_submissions()
        dir = Path(dir)
        dir.mkdir()
        for group in self.submissions:
            s = self.submissions[group]
            if Assignment.current_submission(s).workflow_state != 'graded':
                self.prepare_submission(deadline, dir / self.groups.group_details[group].name, s)
