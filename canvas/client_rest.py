import functools
import json
import logging
import os.path
import re
import shutil
import subprocess
import sys
import types
import urllib.parse
from datetime import timedelta
from pathlib import Path, PurePosixPath

import requests

import util.http_logging  # noqa F401
import util.simple_cache
from util.general import (
    BearerAuth,
    JSONObject,
    doublequote,
    eq,
    from_singleton,
    group_by,
    join_lines,
    json_encoder,
    on,
    print_error,
    without_adjacent_dups,
)
from util.path import OpenWithModificationTime, format_path, set_modification_time


logger = logging.getLogger(__name__)


# This class manages requests to Canvas and their caching.
# Caching is important to maintain quick execution time of higher level scripts on repeat invocation.
# Cache behaviour is controlled by the parameter 'use_cache' of the request methods.
# It can be:
# * a Boolean,
# * a timestamp: only entries at most this old are considered valid.
class Canvas:
    def __init__(
        self,
        domain,
        auth_token=Path(__file__).parent / "auth_token",
        *,
        timeout=30,
        cache_dir=Path("cache"),
    ):
        if isinstance(auth_token, PurePosixPath):
            try:
                self.auth_token = Path(auth_token).read_text(encoding="ascii").strip()
            except FileNotFoundError:
                print_error("No Canvas authorization token found.")
                print_error(
                    f"Expected Canvas authorization token in file {format_path(auth_token)}."
                )
                sys.exit(1)
        else:
            self.auth_token = auth_token

        self.domain = domain
        self.cache = util.simple_cache.SimpleCache(cache_dir)

        self.base_url = "https://" + self.domain
        self.base_url_api = self.base_url + "/api/v1"

        self.timeout = timeout
        self.session = requests.Session()
        self.session.auth = BearerAuth(self.auth_token)
        # self.session.headers.update({'Authorization': 'Bearer {}'.format(self.auth_token)})

        self.session_file = requests.Session()

    # internal
    @staticmethod
    def get_cache_path(endpoint, params):
        p = PurePosixPath(*(map(str, endpoint)))
        n = p.name
        if bool(params):
            n = n + "?" + urllib.parse.urlencode(params)
        return p.with_name(n)

    # internal
    def get_url(self, endpoint, absolute=True):
        prefix = self.base_url if absolute else ""
        return prefix + "/" + str(PurePosixPath(*(map(str, endpoint))))

    # internal
    @staticmethod
    def with_api(endpoint):
        return ["api", "v1"] + endpoint

    # internal
    @staticmethod
    def load_json_objectified(x):
        return json.loads(x, object_hook=lambda x: JSONObject(**x))

    # internal
    @staticmethod
    def objectify_json(x):
        return Canvas.load_json_objectified(json.dumps(x))

    # internal
    @staticmethod
    def get_response_json(response):
        response.raise_for_status()
        return response.json()

    # internal
    def get_json(self, endpoint, params=None):
        r = self.session.get(
            self.get_url(Canvas.with_api(endpoint)), params=params, timeout=self.timeout
        )
        result = Canvas.get_response_json(r)
        assert not isinstance(r, list)
        return result

    # internal
    def get_list_json(self, endpoint, params=None):
        if params is None:
            params = {}
        params = params | {"per_page": "100"}
        r = self.session.get(
            self.get_url(Canvas.with_api(endpoint)),
            params=params,
            timeout=self.timeout,
        )
        x = Canvas.get_response_json(r)
        assert isinstance(x, list)
        while "next" in r.links:
            r = self.session.get(
                r.links["next"]["url"],
                headers={"Authorization": f"Bearer {self.auth_token}"},
                timeout=self.timeout,
            )
            x.extend(Canvas.get_response_json(r))
        return x

    # internal
    def json_cacher(self, method):
        def f(endpoint, params=None, use_cache=True):
            logger.info(
                "accessing endpoint " + self.get_url(Canvas.with_api(endpoint)),
            )
            return Canvas.objectify_json(
                self.cache.with_cache_json(
                    Canvas.get_cache_path(Canvas.with_api(endpoint), params),
                    lambda: method(endpoint, params),
                    use_cache,
                )
            )

        return f

    # Return the URL to the web browser page on Canvas corresponding to an endpoint.
    # Does not always corresponds to an API endpoint.
    def interactive_url(self, endpoint):
        return self.get_url(endpoint)

    # Using GET to retrieve a JSON object.
    # 'endpoint' is a list of strings and integers constituting the path component of the url.
    # The starting elements 'api' and 'v1' are omitted.
    def get(self, endpoint, params=None, use_cache=True):
        return self.json_cacher(self.get_json)(endpoint, params, use_cache)

    # Using GET to retrieve a JSON list.
    # 'endpoint' is a list of strings and integers constituting the path component of the url.
    # The starting elements 'api' and 'v1' are omitted.
    def get_list(self, endpoint, params=None, use_cache=True):
        return self.json_cacher(self.get_list_json)(endpoint, params, use_cache)

    # internal
    def get_file_bare(self, id, verifier, use_cache=True):
        endpoint = ["files", id, "download"]
        params = {"verifier": verifier}
        logger.info("accessing endpoint " + self.get_url(endpoint))

        def constructor(file_path):
            r = self.session.get(
                self.get_url(endpoint), params=params, timeout=self.timeout
            )
            r.raise_for_status()
            with Path(file_path).open("wb") as file:
                file.write(r.content)

        return self.cache.with_cache_file(
            Canvas.get_cache_path(endpoint, params), constructor, use_cache
        )

    # internal
    @staticmethod
    def parse_verifier(url):
        r = urllib.parse.urlparse(url)
        return urllib.parse.parse_qs(r.query)["verifier"][0]

    # Retrieve a file from canvas.
    # 'file' is a file description object retrieved from Canvas.
    # Returns a path to the stored location of the file in the cache (not to be modified).
    def get_file(self, file_descr, use_cache=True):
        return self.get_file_bare(
            file_descr.id, Canvas.parse_verifier(file_descr.url), use_cache
        )

    # Store a file from canvas in a designated location.
    # 'file_descr' is a file description object retrieved from Canvas.
    # The file modification time is set to the modification time of the file on Canvas.
    def place_file(
        self,
        target,
        file_descr,
        temp_target=None,
        if_already_there=True,
        use_cache=True,
    ):
        if if_already_there or not target.is_file():
            t = temp_target if temp_target else target
            shutil.copyfile(self.get_file(file_descr, use_cache), t)
            set_modification_time(t, file_descr.modified_at_date)
            if temp_target:
                t.rename(target)

    # Perform a PUT request to the designated endpoint.
    # 'endpoint' is a list of strings and integers constituting the path component of the url.
    # The starting elements 'api' and 'v1' are omitted.
    # pylint: disable-next=redefined-outer-name
    def put(self, endpoint, params=None, data=None, json=None):
        logger.info("PUT with endpoint " + self.get_url(Canvas.with_api(endpoint)))
        return Canvas.objectify_json(
            Canvas.get_response_json(
                self.session.put(
                    self.get_url(Canvas.with_api(endpoint)),
                    data=data,
                    json=json,
                    params=params,
                )
            )
        )

    # Perform a POST request to the designated endpoint.
    # 'endpoint' is a list of strings and integers constituting the path component of the url.
    # The starting elements 'api' and 'v1' are omitted.
    # pylint: disable-next=redefined-outer-name
    def post(self, endpoint, data=None, json=None, params=None):
        logger.info("POST with endpoint " + self.get_url(Canvas.with_api(endpoint)))
        return Canvas.objectify_json(
            Canvas.get_response_json(
                self.session.post(
                    self.get_url(Canvas.with_api(endpoint)),
                    data=data,
                    json=json,
                    params=params,
                    timeout=self.timeout,
                )
            )
        )

    # Perform a DELETE request to the designated endpoint.
    # 'endpoint' is a list of strings and integers constituting the path component of the url.
    # The starting elements 'api' and 'v1' are omitted.
    def delete(self, endpoint, params=None):
        logger.info(
            "DELETE with endpoint " + self.get_url(Canvas.with_api(endpoint)),
        )
        return Canvas.objectify_json(
            Canvas.get_response_json(
                self.session.delete(
                    self.get_url(Canvas.with_api(endpoint)),
                    params=params,
                    timeout=self.timeout,
                )
            )
        )

    @staticmethod
    def param_boolean(v):
        return "true" if v else "false"

    # Returns the id of the posted file.
    def post_file(self, endpoint, file, folder_id_or_path, name, use_curl=False):
        """
        Warning:
        If folder_id_or_path is a path, then any ancestor folders may implicitly be created.
        They will be published by default.

        Possible Canvas bug (observed repeatedly since 2024-01-17):
        Sometimes, a file upload with specified folder id fails with error 404 (not found).

        Some further investigation on (2024-01-31):
        This seems to be related to upload of files with the same content as an old version.
        Probably some deduplication module in the Canvas server software is now broken.
        To reproduce:
        1. Upload file A under path P.
        2. Upload file B, different from A, under path P.
        3. Upload file A under path P.

        Reported here: https://github.com/instructure/canvas-lms/issues/2309

        As a workaround, consider appending random data without semantic meaning to every overwriting file upload.

        Warning (2024-01-31):
        The id of a folder can change.
        """
        file = file.resolve()
        size = file.stat().st_size

        def params():
            yield ("name", name)
            yield ("size", size)
            yield ("on_duplicate", "overwrite")  # Should actually be the default.
            if isinstance(folder_id_or_path, int):
                yield ("parent_folder_id", folder_id_or_path)
            else:
                yield ("parent_folder_path", str(folder_id_or_path))

        r = self.post(endpoint, dict(params()))
        upload_params = json.loads(json_encoder.encode(r.upload_params))

        if use_curl:
            cmd = ["curl", r.upload_url]
            for upload_param, value in upload_params.items():
                assert re.fullmatch("\\w+", upload_param)
                value = (
                    upload_param
                    + "="
                    + doublequote(
                        value if isinstance(value, str) else json.dumps(value)
                    )
                )
                cmd += ["-F", value]
            cmd += ["-F", "file=@" + doublequote(str(file))]
            process = subprocess.run(
                cmd, check=True, stdout=subprocess.PIPE, encoding="utf-8"
            )
            location = json.loads(process.stdout)["location"]
        else:
            location = self.session_file.post(
                r.upload_url, upload_params, files={"file": file.read_bytes()}
            ).headers["Location"]

        return Canvas.objectify_json(
            Canvas.get_response_json(self.session.get(location, timeout=self.timeout))
        ).id

    # Retrieve the list of courses that the current user is a member of.
    def courses(self):
        return self.get_list(["courses"])

    def file_set_locked(self, file_id, locked):
        self.put(["files", file_id], params={"locked": Canvas.param_boolean(locked)})

    # def get_inst_access_token(self):
    #    return self.post(['inst_access_tokens']).token


# On GU Canvas, the user id fields seem to mean the following:
# * sis_user_id: 12-digit personnummer (could be a temporary one, which includes letter 'T'; probably even 'P')
# if the user came from GU Canvas:
# * login_id: <GU-id>
# * integration_id: <GU-id>@gu.se
# if the user came from Chalmers Canvas:
# * login_id: <Chalmers-id>@chalmers.se
# * integration_id: unknown, 12-digits, starts 9228...
#
# On Chalmers Canvas, they seem to mean the following:
# * sis_user_id: 12-digit personnummer (could be a temporary one, which includes letter 'T'; probably even 'P')
# if the user came from GU Canvas:
# * login_id: not defined
# * integration_id: <GU-id>@gu.se
# if the user came from Chalmers Canvas:
# * login_id: not defined
# * integration_id: unknown, 12-digits, starts 9228...
#
# Whether or not the login_id is shown may depend on the permissions of the querying user.
#
# We cannot depend on the email field being the actual student email address.
# So that's not a good way to extract the id.
#
# Retrieving the user's profile (canvas.get(['users', id, 'profile']) always includes the login_id.
# The Chalmers login id might not be a valid email address (to confirm).
class Course:
    roles_student = ["StudentEnrollment", "admitted_student"]
    roles_teacher = ["Examiner", "TeacherEnrollment", "TaEnrollment"]

    @staticmethod
    def has_some_role(user, roles):
        return any(enrollment.role in roles for enrollment in user.enrollments)

    @staticmethod
    def is_student(user):
        return Course.has_some_role(user, Course.roles_student)

    @staticmethod
    def is_teacher(user):
        return Course.has_some_role(user, Course.roles_teacher)

    def get_all_users(self, use_cache=True):
        return self.canvas.get_list(
            ["courses", self.course_id, "users"],
            params={
                "include[]": ["enrollments"],
                # We used to also include 'invited' below,
                # but that causes problems.
                # An invited user lacks several fields a script may require (email, login_id).
                "enrollment_state[]": ["active", "completed", "inactive"],
            },
            use_cache=use_cache,
        )

    def __init__(self, canvas, course_id, use_cache=True):
        logger.info(f"loading course {course_id}.")
        self._use_cache = use_cache

        self.canvas = canvas
        self.course_id = course_id
        self.endpoint = ["courses", self.course_id]

        self.users = self.get_all_users(use_cache=use_cache)

        self.user_details = {}
        self.user_name_to_id = {}
        self.user_sortable_name_to_id = {}
        self.user_integration_id_to_id = {}
        self.user_sis_id_to_id = {}
        for user in self.users:
            if Course.has_some_role(user, Course.roles_student + Course.roles_teacher):
                self.user_details[user.id] = user
                self.user_name_to_id[user.name] = user.id
                self.user_sortable_name_to_id[user.sortable_name] = user.id
                self.user_integration_id_to_id[user.integration_id] = user.id
                self.user_sis_id_to_id[user.sis_user_id] = user.id

        self.students = tuple(filter(Course.is_student, self.users))
        self.student_details = dict((user.id, user) for user in self.students)

        self.teachers = tuple(filter(Course.is_teacher, self.users))
        self.teacher_details = dict((user.id, user) for user in self.teachers)

    def _init_assignments(self, use_cache=True):
        self.assignments_name_to_id = {}
        self.assignment_details = {}
        for assignment in self.get_assignments(use_cache=use_cache):
            self.assignment_details[assignment.id] = assignment
            self.assignments_name_to_id[assignment.name] = assignment.id

    @functools.cached_property
    def assignments_name_to_id(self):
        self._init_assignments(self._use_cache)
        return self.assignments_name_to_id

    @functools.cached_property
    def assignment_details(self):
        self._init_assignments()
        return self.assignment_details

    def _user_maybe(self, user_id):
        return None if user_id is None else self.user_details[user_id]

    def user_by_sis_id(self, sis_id):
        return self._user_maybe(self.user_sis_id_to_id.get(sis_id))

    def user_by_integration_id(self, integration_id):
        return self._user_maybe(self.user_integration_id_to_id.get(integration_id))

    def user_str(self, id):
        return f"{self.user_details[id].name} (id {id})"

    def users_str(self, ids):
        return ", ".join(self.user_str(id) for id in ids) if ids else "[no users]"

    def user_str_informal(self, id):
        return self.user_details[id].sortable_name.split(",")[-1].strip()

    def get_assignments(self, include=None, use_cache=True):
        params = {}
        if include:
            params = {"include": include}
        return self.canvas.get_list(
            self.endpoint + ["assignments"], params=params, use_cache=use_cache
        )

    def select_assignment(self, assignment_name):
        id = self.assignments_name_to_id.get(assignment_name)
        if id:
            return self.assignment_details[id]

        xs = list(
            filter(
                lambda assignment: assignment.name.lower().startswith(
                    assignment_name.lower()
                ),
                self.assignment_details.values(),
            )
        )
        if len(xs) == 1:
            return xs[0]

        if not xs:
            print_error(f"No assigments found fitting '{assignment_name}'.")
        else:
            print_error(f"Multiple assignments found fitting '{assignment_name}':")
            for assignment in xs:
                print_error("  " + assignment.name)
        assert False

    def assignment_str(self, id):
        return f"{self.assignment_details[id].name} (id {id})"

    def post_assignment(self, assignment):
        return self.canvas.post(
            self.endpoint + ["assignments"],
            json={
                "assignment": assignment,
            },
        )

    def edit_assignment(self, id, assignment):
        return self.canvas.put(
            self.endpoint + ["assignments", id],
            json={
                "assignment": assignment,
            },
        )

    def delete_assignment(self, id):
        self.canvas.delete(self.endpoint + ["assignments", id])

    def get_submissions(self, assignment_id, use_cache=True):
        return self.canvas.get_list(
            ["courses", self.course_id, "assignments", assignment_id, "submissions"],
            params={"include[]": ["submission_comments", "submission_history"]},
            use_cache=use_cache,
        )

    def get_section(self, name, use_cache=True):
        sections = self.canvas.get_list(
            self.endpoint + ["sections"], use_cache=use_cache
        )
        return from_singleton(s for s in sections if s.name == name)

    def get_students_in_section(self, id, use_cache=True):
        x = self.canvas.get(
            self.endpoint + ["sections", id],
            params={"include": ["students"]},
            use_cache=use_cache,
        ).students
        if x is None:
            x = []
        return [user for user in x if user.id in self.student_details]

    def get_folder_by_path(self, canvas_dir, use_cache=True):
        canvas_dir = PurePosixPath(canvas_dir)
        if canvas_dir.is_absolute():
            canvas_dir = canvas_dir.relative_to("/")
        try:
            return self.canvas.get_list(
                self.endpoint + ["folders", "by_path", canvas_dir], use_cache=use_cache
            )[-1]
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                return None
            raise e

    def get_file_descr(self, id):
        return self.canvas.get(self.endpoint + ["files", id])

    def get_file_link(self, id, absolute=False, download=True):
        endpoint = list(self.endpoint)
        endpoint.extend(["files", id])
        if download:
            endpoint.append("download")
        return self.canvas.get_url(endpoint, absolute=absolute)

    # Returns the id of the posted file.
    def post_file(self, file, folder_id_or_path, name, locked=False, use_curl=False):
        file_id = self.canvas.post_file(
            self.endpoint + ["files"], file, folder_id_or_path, name, use_curl=use_curl
        )
        if locked:
            self.canvas.file_set_locked(file_id, True)
        return file_id

    def get_files(self, folder_id, use_cache=False):
        if not isinstance(folder_id, int):
            folder_id = self.get_folder_by_path(folder_id, use_cache=use_cache).id
        files = self.canvas.get_list(
            ["folders", folder_id, "files"], use_cache=use_cache
        )
        return dict((file.filename, file) for file in files)

    def get_folder(self, id, use_cache=True):
        return self.canvas.get(["folders", id], use_cache=use_cache)

    def create_folder(
        self, canvas_dir, unlock_at=None, lock_at=None, locked=None, hidden=None
    ):
        canvas_dir = PurePosixPath(canvas_dir)
        params = {
            "name": canvas_dir.name,
            "parent_folder_path": str(canvas_dir.parent),
        }
        if unlock_at is not None:
            params["unlock_at"] = unlock_at.isoformat()
        if lock_at is not None:
            params["lock_at"] = lock_at.isoformat()
        if locked is not None:
            params["locked"] = Canvas.param_boolean(locked)
        if hidden is not None:
            params["hidden"] = Canvas.param_boolean(hidden)

        folder = self.canvas.post(self.endpoint + ["folders"], params)
        if not folder.full_name == "course files" + str(canvas_dir):
            self.delete_folder(folder.id)
            assert False, f"Could not create Canvas folder {format_path(canvas_dir)}."

        return folder

    def edit_folder(
        self,
        id,
        name=None,
        unlock_at=None,
        lock_at=None,
        locked=None,
        hidden=None,
        use_cache=False,
    ):
        if not isinstance(id, int):
            id = self.get_folder_by_path(id, use_cache=use_cache).id

        params = {}
        if name is not None:
            params["name"] = name
        params["unlock_at"] = unlock_at.isoformat() if unlock_at is not None else "null"
        params["lock_at"] = lock_at.isoformat() if lock_at is not None else "null"
        if locked is not None:
            params["locked"] = "true" if locked else "false"
        if hidden is not None:
            params["hidden"] = hidden

        return self.canvas.put(["folders", id], data=params)

    # id can also be path.
    def delete_folder(self, id, use_cache=False):
        if not isinstance(id, int):
            id = self.get_folder_by_path(id, use_cache=use_cache).id

        self.canvas.delete(
            ["folders", id], params={"force": Canvas.param_boolean(True)}
        )

    def list_folders(self, use_cache=False):
        return self.canvas.get_list(self.endpoint + ["folders"], use_cache=use_cache)


class GroupSet:
    def __init__(self, course, group_set, use_cache=True):
        logger.info(f"loading group set {group_set}.")

        self.canvas = course.canvas
        self.course = course

        group_sets = self.canvas.get_list(
            ["courses", self.course.course_id, "group_categories"]
        )
        self.group_set = from_singleton(
            filter(
                lambda x: (
                    (isinstance(group_set, str) and x.name == group_set)
                    or x.id == group_set
                ),
                group_sets,
            )
        )

        self.details = {}
        self.name_to_id = {}

        self.group_users = {}
        self.user_to_group = {}

        for group in self.canvas.get_list(
            ["group_categories", self.group_set.id, "groups"],
            use_cache=use_cache,
        ):
            self.details[group.id] = group
            self.name_to_id[group.name] = group.id
            users = set()
            for user in self.canvas.get_list(
                ["groups", group.id, "users"],
                use_cache=use_cache,
            ):
                users.add(user.id)
                self.user_to_group[user.id] = group.id
            self.group_users[group.id] = users

        self.prefix = os.path.commonprefix(
            [group.name for (_, group) in self.details.items()]
        )

    def str(self, id):
        return f"{self.details[id].name} (id {id})"

    def members_str(self, id):
        return self.course.users_str(self.group_users[id])

    def create_group(self, name):
        logger.info(
            f"Creating group with name {name} in group set {self.group_set.name}"
        )
        self.canvas.post(
            ["group_categories", self.group_set.id, "groups"],
            json={
                "name": name,
                #'description': None,
                "join_level": "parent_context_auto_join",
            },
        )


class Assignment:
    def __init__(self, course, assignment_id, use_cache=True):
        self.canvas = course.canvas
        self.course = course

        if isinstance(assignment_id, str):
            self.assignment_id = course.select_assignment(assignment_id).id
        else:
            self.assignment_id = assignment_id

        self.assignment = self.canvas.get(
            ["courses", course.course_id, "assignments", self.assignment_id]
        )
        self.group_set = GroupSet(
            course, self.assignment.group_category_id, use_cache=use_cache
        )

    @staticmethod
    def could_be_same_date(a, b):
        return abs(a - b) < timedelta(minutes=1)

    @staticmethod
    def submission_file_signature(s):
        return tuple(
            sorted(
                file.id
                for file in (s.attachments if "attachments" in s.__dict__ else [])
            )
        )

    # Canvas bug: some submissions have null posted_at
    # Work around that by looking at date of submission files.
    # What does posted_at mean? Using submitted_at.
    @staticmethod
    def submission_date(s):
        return (
            s.submitted_at_date
        )  # if s.submitted_at else max(a.updated_at_date for a in s.attachments) # noqa E261

    @staticmethod
    def is_duplicate_comment(a, b):
        checks = [
            on(eq, lambda c: c.author_id),
            on(eq, lambda c: c.comment),
            on(Assignment.could_be_same_date, lambda c: c.created_at_date),
        ]
        return all(map(lambda check: check(a, b), checks))

    @staticmethod
    def is_duplicate_submission(a, b):
        checks = [
            on(eq, Assignment.submission_file_signature),
            on(eq, lambda s: s.submission_type),
            on(eq, lambda s: s.workflow_state),
            on(eq, lambda s: s.body),
            on(Assignment.could_be_same_date, Assignment.submission_date),
        ]
        return all(map(lambda check: check(a, b), checks))

    @staticmethod
    def merge_comments(comments):
        return without_adjacent_dups(
            Assignment.is_duplicate_comment,
            sorted(comments, key=lambda c: c.created_at_date),
        )

    @staticmethod
    def merge_submissions(submissions):
        return without_adjacent_dups(
            Assignment.is_duplicate_submission,
            sorted(submissions, key=Assignment.submission_date),
        )

    # Get the web browser URL for a submission.
    def submission_interactive_url(self, submission):
        return self.canvas.interactive_url(
            [
                "courses",
                self.course.course_id,
                "assignments",
                self.assignment_id,
                "submissions",
                submission.user_id,
            ]
        )

    def submission_speedgrader_url(self, submission):
        return (
            self.canvas.interactive_url(
                ["courses", self.course.course_id, "gradebook", "speed_grader"]
            )
            + "?"
            + urllib.parse.urlencode(
                {"assignment_id": self.assignment_id, "student_id": submission.user_id}
            )
        )

    # Keep only the real submissions.
    @staticmethod
    def filter_submissions(raw_submissions):
        return filter(
            lambda raw_submission: (
                not raw_submission.missing
                and raw_submission.workflow_state != "unsubmitted"
            ),
            raw_submissions,
        )

    # Returns list of named tuples with attributes:
    # - members: list of users with this submission
    # - submissions: merged submission history
    # - comments: merged comments
    # TODO: Revisit implementation of this method when there is a conflict of the produced grouping with groupset.
    @staticmethod
    def group_identical_submissions(raw_submissions):
        grouping = group_by(
            lambda raw_submission: tuple(
                sorted(file.id for file in raw_submission.attachments)
            ),
            raw_submissions,
        )
        return [
            types.SimpleNamespace(
                members=[submission.user_id for submission in grouped_submissions],
                submissions=list(
                    Assignment.merge_submissions(
                        submission
                        for s in grouped_submissions
                        for submission in s.submission_history
                    )
                ),
                comments=list(
                    Assignment.merge_comments(
                        [
                            comment
                            for s in grouped_submissions
                            for comment in s.submission_comments
                        ]
                    )
                ),
            )
            for _, grouped_submissions in grouping.items()
        ]

    def align_with_groups(self, user_grouped_submissions):
        user_to_user_grouping = dict(
            (user, submission_data.members)
            for submission_data in user_grouped_submissions
            for user in submission_data.members
        )
        lookup = dict(
            (tuple(user_grouped_submission.members), user_grouped_submission)
            for user_grouped_submission in user_grouped_submissions
        )

        result = {}
        for group in self.group_set.details:
            group_users = self.group_set.group_users[group]
            if not group_users:
                continue

            user_groupings = set()
            for user in group_users:
                user_grouping = user_to_user_grouping.get(user)
                if user_grouping:
                    user_groupings.add(tuple(user_grouping))

            if not user_groupings:
                logger.info(f"Info: {self.group_set.str(group)} did not submit:")
                logger.info("- " + self.course.users_str(group_users))
                continue

            # TODO: handle this somehow if it ever happens (assuming students can change groups).
            if len(user_groupings) > 1:
                print_error(
                    f"Incongruous submissions for members of {self.group_set.str(group)}."
                )
                print_error(
                    f"The group consists of: {self.group_set.members_str(group)}."
                )
                print_error(
                    "But only the following groups of users have submitted identically:"
                )
                for user_grouping in user_groupings:
                    print_error("- " + self.course.users_str(user_grouping))
                assert False

            user_grouping = next(iter(user_groupings))

            did_not_submit = set(group_users).difference(set(user_grouping))
            if did_not_submit:
                logger.info(
                    f"The following members have not submitted with {self.group_set.str(group)}:"
                )
                for user_id in did_not_submit:
                    logger.info("- " + self.course.user_str(user_id))

            not_part_of_group = set(user_grouping).difference(set(group_users))
            if not_part_of_group:
                logger.info(
                    f"The following non-members have submitted with {self.group_set.str(group)}:"
                )
                for user_id in not_part_of_group:
                    logger.info("- " + self.course.user_str(user_id))

            result[group] = lookup[tuple(user_grouping)]
        return result

    def collect_submissions(self, use_cache=True):
        raw_submissions = self.course.get_submissions(
            self.assignment_id,
            use_cache=use_cache,
        )
        grouped_submission = Assignment.group_identical_submissions(
            Assignment.filter_submissions(raw_submissions)
        )
        # pylint: disable-next=attribute-defined-outside-init
        self.submissions = self.align_with_groups(grouped_submission)

    @staticmethod
    def current_submission(s):
        return s.submissions[-1]

    @staticmethod
    def first_ungraded(s):
        submissions = s.submissions
        for i in reversed(range(len(submissions))):
            if submissions[i].workflow_state == "graded":
                return i + 1

        return 0

    @staticmethod
    def last_graded_submission(s):
        i = Assignment.first_ungraded(s)
        if i == 0:
            return None

        return s.submissions[i - 1]

    @staticmethod
    def get_submissions(s, previous=False):
        submissions = s.submissions
        if previous:
            submissions = submissions[: Assignment.first_ungraded(s)]
        return submissions

    @staticmethod
    def graded_comments(s):
        last_graded = Assignment.last_graded_submission(s)

        def is_new(date):
            return (
                last_graded is None
                or date - last_graded.graded_at_date >= timedelta(minutes=5)
            )

        return list(
            filter(lambda comment: not is_new(comment.created_at_date), s.comments)
        )

    @staticmethod
    def ungraded_comments(s):
        last_graded = Assignment.last_graded_submission(s)

        def is_new(date):
            return (
                last_graded is None
                or date - last_graded.graded_at_date >= timedelta(minutes=5)
            )

        return list(filter(lambda comment: is_new(comment.created_at_date), s.comments))

    @staticmethod
    def get_file_name(file):
        return urllib.parse.unquote_plus(file.filename)

    # Use with 'get_files' and assorted functions
    @staticmethod
    def name_handler(whitelist, handlers, unhandled=None):
        def f(id, name):
            handler = handlers(id) if handlers else None
            if handler:
                return handler(name)
            if name in whitelist:
                return name
            if unhandled:
                return unhandled(id, name)
            return None

        return f

    # We treat submissions as cumulative: later files replace earlier files.
    # We do this because students sometimes only resubmit the updated files.
    @staticmethod
    def get_files(submissions, name_handler=None):
        files = {}
        for submission in submissions:
            submission_files = {}
            for attachment in submission.attachments:
                name = Assignment.get_file_name(attachment)
                if name_handler:
                    name = name_handler(attachment.id, name)
                if name:
                    prev_attachment = submission_files.get(name)
                    if prev_attachment:
                        print_error(
                            f"Duplicate filename {name} in submission {submission.id}:"
                            f"files ids {prev_attachment.id} and {attachment.id}."
                        )
                        raise RuntimeError()
                    submission_files[name] = attachment
            files.update(submission_files)
        return files

    @staticmethod
    def get_graded_files(s, name_handler=None):
        return Assignment.get_files(
            s.submissions[: Assignment.first_ungraded(s)], name_handler=name_handler
        )

    @staticmethod
    def get_current_files(s, name_handler=None):
        return Assignment.get_files(s.submissions, name_handler=name_handler)

    @staticmethod
    def write_comments(path, comments):
        if comments:
            with OpenWithModificationTime(path, comments[-1].created_at_date) as file:
                for comment in comments:
                    file.write_text(
                        join_lines(
                            [
                                "=" * 80,
                                "",
                                comment.author.display_name,
                                comment.created_at,
                                "",
                                comment.comment,
                                "",
                            ]
                        )
                    )

    @staticmethod
    def format_comments(comments):
        lines = []
        for comment in comments:
            lines.append(comment.author.display_name)
            lines.append(comment.created_at)
            lines.append("")
            lines.append(comment.comment)
            lines.append("")
        return lines

    # Returns a mapping from file ids to paths.
    # Better use create_submission_dir_linked.
    # def create_submission_dir(self, dir, submission, files, write_ids = False, content_handlers = None):
    #     dir.mkdir(exist_ok = True) # useful if unpacking on top of template files
    #     file_mapping = {}
    #     for filename, attachment in files.items():
    #         path = dir / filename
    #         self.canvas.place_file(path, attachment)
    #         util.path.fix_encoding(path)
    #
    #         file_mapping[attachment.id] = path
    #         if write_ids:
    #             with (dir / ('.' + filename)).open('w') as file:
    #                 file.write(str(attachment.id))
    #
    #         content_handler = content_handlers(attachment.id) if content_handlers else None
    #         if content_handler:
    #             try:
    #                 util.path.modify_no_modification_time(path, content_handler)
    #             except HandlerException as e:
    #                 print_error('Content handler failed on file id {}: {}'.format(attachment.id, format_path(path)))
    #                 raise e
    #     set_modification_time(dir, submission.submitted_at_date)
    #     return file_mapping

    # Returns a mapping from file ids to paths.
    # Needs: from _2020_lp2.submission_fix_lib import HandlerException
    # def create_submission_dir_linked(
    #     self,
    #     dir_files,
    #     dir,
    #     rel_dir_files,
    #     submission,
    #     files,
    #     content_handlers=None,
    # ):
    #     dir_files.mkdir(exist_ok=True)
    #     dir.mkdir(exist_ok=True)
    #
    #     file_mapping = {}
    #     for filename, attachment in files.items():
    #         source = dir_files / str(attachment.id)
    #         self.canvas.place_file(
    #             source, attachment, temp_target=util.path.add_suffix(source, ".temp")
    #         )
    #         util.path.fix_encoding(source)
    #
    #         content_handler = (
    #             content_handlers(attachment.id) if content_handlers else None
    #         )
    #         if content_handler:
    #             try:
    #                 util.path.modify_no_modification_time(source, content_handler)
    #             except HandlerException as e:
    #                 print_error(f"Content handler failed on {format_path(source)}")
    #                 raise e
    #
    #         target = dir / filename
    #         target.symlink_to(rel_dir_files / str(attachment.id))
    #         file_mapping[attachment.id] = target

    #     set_modification_time(dir, submission.submitted_at_date)
    #     return file_mapping

    # def prepare_submission(self, deadline, group, dir, s):
    #     dir.mkdir()

    #     current_dir = dir / 'current'
    #     current = Assignment.current_submission(s)
    #     self.create_submission_dir(current_dir, current, Assignment.get_current_files(s))
    #     Assignment.write_comments(dir / 'new-comments.txt', Assignment.ungraded_comments(s))

    #     previous = Assignment.last_graded_submission(s)
    #     if previous != None:
    #         previous_dir = dir / 'previous'
    #         self.create_submission_dir(previous_dir, previous, Assignment.get_graded_files(s))
    #         Assignment.write_comments(dir / 'previous-comments.txt', Assignment.graded_comments(s))

    #     if deadline != None:
    #         time_diff = current.submitted_at_date - deadline
    #         if time_diff >= timedelta(minutes = 5):
    #             with OpenWithModificationTime(dir / 'late.txt', current.submitted_at_date) as file:
    #                 file.write_text(util.general.join_lines(['{:.2f} hours'.format(time_diff / timedelta(hours = 1))]))

    #     with (dir / 'members.txt').open('w') as file:
    #         for user in self.group_set.group_users[group]:
    #             file.write_text(util.general.join_lines([self.group_set.user_details[user].name]))

    # def prepare_submissions(self, dir, deadline = None):
    #     #self.build_submissions()
    #     dir = Path(dir)
    #     dir.mkdir()
    #     for group in self.submissions:
    #         s = self.submissions[group]
    #         current = Assignment.current_submission(s)
    #         if not (current.workflow_state == 'graded' and current.grade == 'complete')
    #            and (current.workflow_state == 'submitted' or Assignment.ungraded_comments(s)):
    #             self.prepare_submission(deadline, group, dir / self.group_set.details[group].name, s)

    def grade(self, user, comment=None, grade=None):
        assert grade in [None, "complete", "incomplete", "fail"]

        endpoint = [
            "courses",
            self.course.course_id,
            "assignments",
            self.assignment_id,
            "submissions",
            user,
        ]
        params = {"comment[group_comment]": "false"}
        if comment:
            params["comment[text_comment]"] = comment
        if grade:
            params["submission[posted_grade]"] = grade
        self.canvas.put(endpoint, params=params)


def user_first_and_last_name(user):
    (last, first) = user.sortable_name.split(",", maxsplit=1)
    return (first.strip(), last.strip())
