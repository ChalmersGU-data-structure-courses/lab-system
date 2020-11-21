import json
from types import SimpleNamespace
import requests
import urllib.parse
from pathlib import PurePath, Path
from datetime import datetime, timedelta, timezone
from collections import defaultdict
import os.path
import logging

from general import unique_by, JSONObject, print_json, print_error, write_lines, set_modification_time, OpenWithModificationTime
import simple_cache

logger = logging.getLogger("canvas")

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

    def put(self, endpoint, params):
        logger.log(logging.INFO, 'accessing endpoint ' + self.get_url(Canvas.with_api(endpoint)))
        response = self.session.put(self.get_url(Canvas.with_api(endpoint)), params = params)
        response.raise_for_status()

    def courses(self):
        return self.get_list(['courses'])

class Course:
    def __init__(self, canvas, course_id):
        self.canvas = canvas
        self.course_id = course_id

        self.assignments_name_to_id = dict()
        self.assignment_details = dict()
        for assignment in self.get_assignments():
            self.assignment_details[assignment.id] = assignment
            self.assignments_name_to_id[assignment.name] = assignment.id

    def get_assignments(self):
        return self.canvas.get_list(['courses', self.course_id, 'assignments'])

    def select_assignment(self, assignment_name):
        xs = list(filter(lambda assignment: assignment.name.lower().startswith(assignment_name.lower()), self.assignment_details.values()))
        if len(xs) == 1:
            return xs[0]

        if not xs:
            print_error('No assigments found fitting \'{}\'.'.format(assignment_name))
        else:
            print_error('Multiple assignments found fitting \'{}\':'.format(assignment_name))
            for assignment in xs:
                print_error('  ' + assignment.name)
        exit(1)

    def assignment_str(self, id):
        return '{} (id {})'.format(self.assignment_details[id].name, id)

class Groups:
    def __init__(self, canvas, course_id, groupset):
        self.canvas = canvas
        self.groupset = groupset

        self.user_details = dict()
        self.user_name_to_id = dict()
        for user in canvas.get_list(['courses', course_id, 'users']):
            self.user_details[user.id] = user
            self.user_name_to_id[user.name] = user.id

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

        self.group_prefix = os.path.commonprefix([group.name for (_, group) in self.group_details.items()])

    def user_str(self, id):
        return '{} (id {})'.format(self.user_details[id].name, id)

    def group_str(self, id):
        return '{} (id {})'.format(self.group_details[id].name, id)

class Assignment:
    def __init__(self, canvas, course_id, assignment_id):
        self.canvas = canvas
        self.course_id = course_id

        if isinstance(assignment_id, str):
            self.assignment_id = Course(canvas, course_id).select_assignment(assignment_id).id
        else:
            self.assignment_id = assignment_id

        self.assignment = canvas.get(['courses', course_id, 'assignments', self.assignment_id])
        self.groups = Groups(canvas, course_id, self.assignment.group_category_id)

    @staticmethod
    def is_duplicate_comment(a, b):
        return a.author_id == b.author_id and a.comment == b.comment and abs(a.created_at_date - b.created_at_date) < timedelta(minutes = 1)

    @staticmethod
    def merge_comments(comments):
        return unique_by(Assignment.is_duplicate_comment, comments)

    def build_submissions(self, use_cache = True):
        submissions_by_group = defaultdict(lambda: dict())
        for submission in self.canvas.get_list(['courses', self.course_id, 'assignments', self.assignment_id, 'submissions'], params = {'include[]': ['submission_comments', 'submission_history']}, use_cache = use_cache):
            if not submission.missing and submission.workflow_state != 'unsubmitted':
                if not submission.user_id in self.groups.user_to_group:
                    print_error('User {} submitted despite not being in a group; ignoring.'.format(self.groups.user_str(submission.user_id)))
                else:
                    submissions_by_group[self.groups.user_to_group[submission.user_id]][submission.user_id] = submission

        self.submissions = dict()
        for group in submissions_by_group:
            submissions_this_group = submissions_by_group[group]
            first_user = next(iter(submissions_this_group)) #self.groups.group_details[group].leader.id

            us = self.groups.group_users[group]
            vs = set(submissions_this_group)
            if not us.issubset(vs):
                ws = us.difference(vs)
                print_error('The following members have not submitted with {}:'.format(self.groups.group_str(group)))
                for user_id in ws:
                    print_error('  {}'.format(self.groups.user_str(user_id)))

            all_comments = list()
            for user in submissions_this_group:
                all_comments.extend(submissions_this_group[user].submission_comments)
    
            # sanity check
            attempts_set = set()
            for user in submissions_this_group:
                attempts_set.add(tuple(map(lambda old_submission: old_submission.attempt, submissions_this_group[user].submission_history)))
                if len(attempts_set) != 1:
                    print_error('Incongruous submissions for members of group {}.'.format(self.groups.group_str(group)))
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
            with OpenWithModificationTime(path, comments[-1].created_at_date) as file:
                for comment in comments:
                    write_lines(file, [
                        '=' * 80,
                        '',
                        comment.author.display_name,
                        comment.created_at,
                        '',
                        comment.comment,
                        '',
                    ])

    def create_submission_dir(self, dir, submission, files):
        dir.mkdir()
        for file in files:
            self.canvas.place_file(dir / urllib.parse.unquote_plus(file.filename), file)
        set_modification_time(dir, submission.submitted_at_date)

    def prepare_submission(self, deadline, group, dir, s):
        dir.mkdir()

        current_dir = dir / 'current'
        current = Assignment.current_submission(s)
        self.create_submission_dir(current_dir, current, Assignment.get_current_files(s))
        Assignment.write_comments(dir / 'new-comments.txt', Assignment.ungraded_comments(s))

        previous = Assignment.last_graded_submission(s)
        if previous != None:
            previous_dir = dir / 'previous'
            self.create_submission_dir(previous_dir, previous, Assignment.get_graded_files(s))
            Assignment.write_comments(dir / 'previous-comments.txt', Assignment.graded_comments(s))

        if deadline != None:
            time_diff = current.submitted_at_date - deadline
            if time_diff >= timedelta(minutes = 5):
                with OpenWithModificationTime(dir / 'late.txt', current.submitted_at_date) as file:
                    write_lines(file, ['{:.2f} hours'.format(time_diff / timedelta(hours=1))])

        with (dir / 'members.txt').open('w') as file:
            for user in self.groups.group_users[group]:
                write_lines(file, [self.groups.user_details[user].name])

    def prepare_submissions(self, dir, deadline = None):
        #self.build_submissions()
        dir = Path(dir)
        dir.mkdir()
        for group in self.submissions:
            s = self.submissions[group]
            current = Assignment.current_submission(s)
            if not (current.workflow_state == 'graded' and current.grade == 'complete') and (current.workflow_state == 'submitted' or Assignment.ungraded_comments(s)):
                self.prepare_submission(deadline, group, dir / self.groups.group_details[group].name, s)

    def grade(self, user, comment = None, grade = None):
        assert(grade in [None, 'complete', 'incomplete', 'fail'])

        #user = self.groups.group_details[group].leader.id
        endpoint = ['courses', self.course_id, 'assignments', self.assignment_id, 'submissions', user]
        params = {'comment[group_comment]' : 'false'}
        if comment:
            params['comment[text_comment]'] = comment
        if grade:
            params['submission[posted_grade]'] = grade
        self.canvas.put(endpoint, params = params)
