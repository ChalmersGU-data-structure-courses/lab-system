import json
import requests
import types
import urllib.parse
from pathlib import PurePath, Path
from datetime import datetime, timedelta, timezone
from collections import defaultdict, namedtuple
import os.path
import http_logging
import logging

from general import unique_by, group_by, JSONObject, print_json, print_error, write_lines, set_modification_time, OpenWithModificationTime, modify_no_modification_time
import simple_cache

logger = logging.getLogger("canvas")

# This class manages requests to Canvas and their caching.
# Caching is important to maintain quick execution time of higher level scripts on repeat invocation.
# Cache behaviour is controlled by the parameter 'use_cache' of the request methods.
# It can be:
# * a Boolean,
# * a timestamp: only entries at most this old are considered valid.
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
        result = Canvas.get_response_json(r)
        assert(not isinstance(r, list))
        return result

    # internal
    def get_list_json(self, endpoint, params = dict()):
        p = params.copy()
        p['per_page'] = '100'
        r = self.session.get(self.get_url(Canvas.with_api(endpoint)), params = p)
        x = Canvas.get_response_json(r)
        assert(isinstance(x, list))
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

    # Return the URL to the web browser page on Canvas corresponding to an endpoint.
    # Does not always corresponds to an API endpoint.
    def interactive_url(self, endpoint):
        return self.get_url(endpoint)

    # Using GET to retrieve a JSON object.
    # 'endpoint' is a list of strings and integers constituting the path component of the url.
    # The starting elements 'api' and 'v1' are omitted.
    def get(self, endpoint, params = dict(), use_cache = True):
        return self.json_cacher(self.get_json)(endpoint, params, use_cache)

    # Using GET to retrieve a JSON list.
    # 'endpoint' is a list of strings and integers constituting the path component of the url.
    # The starting elements 'api' and 'v1' are omitted.
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

    # Retrieve a file from canvas.
    # 'file' is a file description object retrieved from Canvas.
    # Returns a path to the stored location of the file in the cache (not to be modified).
    def get_file(self, file_descr, use_cache = True):
        return self.get_file_bare(file_descr.id, Canvas.parse_verifier(file_descr.url), use_cache)

    # Store a file from canvas in a designated location.
    # 'file' is a file description object retrieved from Canvas.
    # The file modification time is set to the modification time of the file on Canvas.
    def place_file(self, target, file_descr, use_cache = True):
        source = self.get_file(file_descr, use_cache)
        target.write_bytes(source.read_bytes())
        set_modification_time(target, file_descr.modified_at_date)

    # Perform a PUT request to the designated endpoint.
    # 'endpoint' is a list of strings and integers constituting the path component of the url.
    # The starting elements 'api' and 'v1' are omitted.
    def put(self, endpoint, params):
        logger.log(logging.INFO, 'accessing endpoint ' + self.get_url(Canvas.with_api(endpoint)))
        response = self.session.put(self.get_url(Canvas.with_api(endpoint)), params = params)
        response.raise_for_status()

    # Retrieve the list of courses that the current user is a member of.
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

    def users_str(self, ids):
        return ', '.join(self.user_str(id) for id in ids) if ids else '[no users]'

    def group_str(self, id):
        return '{} (id {})'.format(self.group_details[id].name, id)

    def group_members_str(self, id):
        return self.users_str(self.group_users[id])

class Assignment:
    def __init__(self, canvas, course_id, assignment_id):
        self.canvas = canvas
        self.course_id = course_id

        if isinstance(assignment_id, str):
            self.assignment_id = Course(canvas, course_id).select_assignment(assignment_id).id
        else:
            self.assignment_id = assignment_id

        self.assignment = self.canvas.get(['courses', course_id, 'assignments', self.assignment_id])
        self.groups = Groups(canvas, course_id, self.assignment.group_category_id)

    @staticmethod
    def is_duplicate_comment(a, b):
        return a.author_id == b.author_id and a.comment == b.comment and abs(a.created_at_date - b.created_at_date) < timedelta(minutes = 1)

    @staticmethod
    def merge_comments(comments):
        return unique_by(Assignment.is_duplicate_comment, comments)

    # Get the web browser URL for a submission.
    def submission_interactive_url(self, submission):
        return self.canvas.interactive_url(['courses', self.course_id, 'assignments', self.assignment_id, 'submissions', submission.user_id])

    def submission_speedgrader_url(self, submission):
        return self.canvas.interactive_url(['courses', self.course_id, 'gradebook', 'speed_grader']) + '?' + urllib.parse.urlencode({'assignment_id' : self.assignment_id, 'student_id' : submission.user_id})

    # Keep only the real submissions.
    @staticmethod
    def filter_submissions(raw_submissions):
        return filter(lambda raw_submission: not raw_submission.missing and raw_submission.workflow_state != 'unsubmitted', raw_submissions)

    # Returns list of named tuples with attributes:
    # - members: list of users with this submission
    # - submissions: merged submission history
    # - comments: merged comments
    # TODO: Revisit implementation of this method when there is a conflict of the produced grouping with groupset.
    @staticmethod
    def group_identical_submissions(raw_submissions):
        grouping = group_by(lambda raw_submission: tuple(sorted([(s.attempt, tuple(sorted(file.id for file in s.attachments))) for s in raw_submission.submission_history])), raw_submissions)
        submission_data_type = namedtuple('submission_data', ['members', 'submissions', 'comments']) # TODO: make static
        return [submission_data_type(
            members = [submission.user_id for submission in grouped_submissions],
            submissions = grouped_submissions[0].submission_history,
            comments = Assignment.merge_comments([c for s in grouped_submissions for c in s.submission_comments]),
        ) for _, grouped_submissions in grouping.items()]

    def align_with_groups(self, user_grouped_submissions):
        user_to_user_grouping = dict((user, submission_data.members) for submission_data in user_grouped_submissions for user in submission_data.members)
        lookup = dict((tuple(user_grouped_submission.members), user_grouped_submission) for user_grouped_submission in user_grouped_submissions)

        result = dict()
        for group in self.groups.group_details:
            group_users = self.groups.group_users[group]

            user_groupings = set()
            for user in group_users:
                user_grouping = user_to_user_grouping.get(user)
                if user_grouping:
                    user_groupings.add(tuple(user_grouping))

            if not user_groupings:
                print_error('{} did not submit.'.format(self.groups.group_str(group)))
                continue

            # TODO: handle this somehow if it ever happens (assuming students can change groups).
            if len(user_groupings) > 1:
                print_error('Incongruous submissions for members of {}.'.format(self.groups.group_str(group)))
                print_error('The group consists of: {}.'.format(self.groups.group_members_str(group)))
                print_error('But only the groups of users have submitted identically:')
                for user_grouping in user_groupings:
                    print_error('- {}'.format(self.groups.users_str(user_grouping)))
                exit(1)

            user_grouping = next(iter(user_groupings))
            #print_error('The group consists of: {}.'.format(self.groups.group_members_str(group)))
            #print_error('The user grouping is: {}.'.format(self.groups.users_str(user_grouping)))

            did_not_submit = set(group_users).difference(set(user_grouping))
            if did_not_submit:
                print_error('The following members have not submitted with {}:'.format(self.groups.group_str(group)))
                for user_id in did_not_submit:
                    print_error('- {}'.format(self.groups.user_str(user_id)))

            not_part_of_group = set(user_grouping).difference(set(group_users))
            if not_part_of_group:
                print_error('The following non-members have submitted with {}:'.format(self.groups.group_str(group)))
                for user_id in not_part_of_group:
                    print_error('- {}'.format(self.groups.user_str(user_id)))

            result[group] = lookup[tuple(user_grouping)]
        return result

    def build_submissions(self, use_cache = True):
        raw_submissions = self.canvas.get_list(['courses', self.course_id, 'assignments', self.assignment_id, 'submissions'], params = {'include[]': ['submission_comments', 'submission_history']}, use_cache = use_cache)
        grouped_submission = Assignment.group_identical_submissions(Assignment.filter_submissions(raw_submissions))
        self.submissions = self.align_with_groups(grouped_submission)

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
    def get_file_name(file):
        return urllib.parse.unquote_plus(file.filename)

    # Use with 'get_files' and assorted functions
    @staticmethod
    def name_handler(whitelist, handlers, unhandled = None):
        def f(id, name):
            if name in whitelist:
                return name;
            handler = handlers.get(id)
            if handler:
                if isinstance(handler, types.FunctionType):
                    handler = [handler]
                for h in handler:
                    name = h(name)
                return name
            if unhandled:
                return unhandled(id, name)
            return None
        return f

    @staticmethod
    def get_files(submissions, name_handler = None):
        files = dict()
        for submission in submissions:
            for attachment in submission.attachments:
                name = Assignment.get_file_name(attachment)
                if name_handler:
                    name = name_handler(attachment.id, name)
                if name:
                    files[name] = attachment

        return files

    @staticmethod
    def get_graded_files(s, name_handler = None):
        return Assignment.get_files(s.submissions[:Assignment.first_ungraded(s)], name_handler = name_handler)

    @staticmethod
    def get_current_files(s, name_handler = None):
        return Assignment.get_files(s.submissions, name_handler = name_handler)

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

    @staticmethod
    def format_comments(comments):
        lines = list()
        for comment in comments:
            lines.append(comment.author.display_name)
            lines.append(comment.created_at)
            lines.append('')
            lines.append(comment.comment)
            lines.append('')
        return lines

    # Returns a mapping from file ids to paths.
    def create_submission_dir(self, dir, submission, files, write_ids = False, content_handlers = None):
        dir.mkdir(exist_ok = True) # useful if unpacking on top of template files
        file_mapping = dict()
        for filename, attachment in files.items():
            path = dir / filename
            self.canvas.place_file(path, attachment)
            file_mapping[attachment.id] = path
            if write_ids:
                with (dir / ('.' + filename)).open('w') as file:
                    file.write(str(attachment.id))
            if content_handlers:
                content_handler = content_handlers.get(attachment.id)
                if content_handler:
                    if isinstance(content_handler, types.FunctionType):
                        content_handler = [content_handler]
                    for handler in content_handler:
                        modify_no_modification_time(path, handler)
        set_modification_time(dir, submission.submitted_at_date)
        return file_mapping

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
