import contextlib
import dataclasses
import functools
import hashlib
import logging
import operator
import time
import urllib.parse
from pathlib import Path, PurePosixPath
from typing import Any, Tuple

import dateutil.parser
import gitlab

import util.general
import util.path
import util.print_parse


logger = logging.getLogger(__name__)


def read_private_token(x):
    if isinstance(x, Path):
        x = x.read_text()
    return x


# The default value of per_page seems to be 15.
# This is incredibly slow.
# We wish to retrieve as many items at once, so supply a large per_page parameter.
# The maximum seems to be 100.
list_all_args = {
    "all": True,
    "per_page": 1000,
}


def list_all(manager, **kwargs):
    return manager.list(**kwargs, **list_all_args)


@contextlib.contextmanager
def exist_ok():
    try:
        yield
    except gitlab.exceptions.GitlabCreateError as e:
        if not (
            e.response_code in [304, 409]
            or (e.response_code == 400 and e.error_message == "Branch already exists")
        ):
            raise
    except gitlab.exceptions.GitlabDeleteError as e:
        if not e.response_code in [304, 404]:
            raise


def exist_ok_check(enabled=False):
    return exist_ok() if enabled else contextlib.nullcontext()


def wait_for_fork(gl, project, fork_poll_interval=0.5, check_immediately=True):
    # The GitLab API does not have a synchronous fork command.
    # This is the currently recommended workaround.
    logger.debug(f"Waiting for fork of {project.path_with_namespace}...")
    while not project.import_status in ["none", "finished"]:
        if check_immediately:
            check_immediately = False
        else:
            time.sleep(fork_poll_interval)
        project = gl.projects.get(project.id)
        logger.debug(f"Import status: {project.import_status}")
    logger.debug("Finished waiting for fork.")
    return project


def protect_tags(
    gl,
    project_id,
    patterns: list[str] | None = None,
    delete_existing=False,
    # pylint: disable-next=redefined-outer-name
    exist_ok=True,
):
    if patterns is None:
        patterns = []

    project = gl.projects.get(project_id, lazy=True)
    if delete_existing or exist_ok:
        protected_prev = list_all(project.protectedtags)
    if delete_existing:
        # Needs gitlab.v4.objects.projects.Project, not just gitlab.v4.objects.projects.ProjectFork.
        # Otherwise, the attribute protectedtags does not exist.
        for x in protected_prev:
            x.delete()
        protected_prev = []
    if exist_ok:
        patterns_prev = set(
            protect.name
            for protect in protected_prev
            if [level["access_level"] for level in protect.create_access_levels] == [30]
        )
        patterns = set(patterns) - patterns_prev
    for pattern in patterns:
        with exist_ok_check(exist_ok):
            project.protectedtags.create(
                {"name": pattern, "create_access_level": gitlab.const.DEVELOPER_ACCESS}
            )


def delete_protected_branches(project):
    for branch in list_all(project.protectedbranches):
        branch.delete()


def protect_branch(project, branch, delete_prev=False):
    if delete_prev:
        project.protectedbranches.delete(branch)
    data = {
        "name": branch,
        "merge_access_level": gitlab.const.MAINTAINER_ACCESS,
        "push_access_level": gitlab.const.MAINTAINER_ACCESS,
        "allow_force_push": True,
    }
    project.protectedbranches.create(data)


def members_from_access(entity, levels):
    return dict(
        (user.id, user)
        for user in list_all(entity.members)
        if user.access_level in levels
    )


class CachedGroup:
    # pylint: disable-next=redefined-outer-name
    def __init__(self, gl, path, name, logger=None):
        self.gl = gl
        self.path = path
        self.name = name
        self.logger = logger

    @functools.cached_property
    def get(self):
        if self.logger:
            self.logger.debug(f"Getting group {self.path}")
        return self.gl.groups.get(str(self.path), lazy=False)

    @functools.cached_property
    def lazy(self):
        g = self.gl.groups.get(str(self.path), lazy=True)
        g.namespace_path = str(self.path)
        g.web_url = urllib.parse.urljoin(self.gl.url, str(self.path))
        return g

    # pylint: disable-next=method-hidden
    def create(self, group=None, **kwargs):
        if self.logger:
            self.logger.info(f"Creating group {self.path}")
        if group is None:
            group = self.gl.groups.get(str(self.path.parent))
        group_data = {
            # The GitLab API should permit to give path instead of id.
            # 'parent_path': str(self.path.parent),
            "parent_id": group.id,
            "path": self.path.name,
            "name": self.name,
        } | kwargs
        self.get = self.gl.groups.create(group_data)
        # Creating a group seems to make you a member.
        # This does not seem to be documented in the GitLab API.
        # Working around this issue.
        self.get.members.get(self.gl.user.id).delete()
        return self.get

    def delete(self):
        if self.logger:
            self.logger.info(f"Deleting group {self.path}")
        # Triggers a bug in python-gitlab:
        # https://github.com/python-gitlab/python-gitlab/issues/1494
        # self.get().delete()
        # Workaround:
        self.gl.groups.delete(str(self.path))
        with contextlib.suppress(AttributeError):
            del self.get

    def replace_create(self, f):
        create_old = self.create
        self.create = f(self, create_old)
        return self


class CachedProject:
    # pylint: disable-next=redefined-outer-name
    def __init__(self, gl, path, name, logger=None):
        self.gl = gl
        self.path = path
        self.name = name
        self.logger = logger

    @functools.cached_property
    def get(self):
        if self.logger:
            self.logger.debug(f"Getting project {self.path}")
        return self.gl.projects.get(str(self.path), lazy=False)

    @functools.cached_property
    def lazy(self):
        p = self.gl.projects.get(str(self.path), lazy=True)
        p.path_with_namespace = str(self.path)
        p.web_url = urllib.parse.urljoin(self.gl.url, str(self.path))
        return p

    def exists(self):
        try:
            return self.get
        except gitlab.exceptions.GitlabGetError as e:
            if e.error_message == "404 Project Not Found":
                return None
            raise

    def create_ensured(self):
        try:
            return self.get
        except gitlab.exceptions.GitlabGetError as e:
            if e.error_message == "404 Project Not Found":
                return self.create()
            raise

    def delete_ensured(self):
        try:
            self.delete()
        except gitlab.exceptions.GitlabDeleteError as e:
            if e.error_message == "404 Project Not Found":
                return
            raise

    def create(self, group=None, **kwargs):
        if self.logger:
            self.logger.info(f"Creating project {self.path}")
        if group is None:
            group = self.gl.groups.get(str(self.path.parent))
        project_data = {
            # The GitLab API should permit to give path instead of id.
            # 'namespace_path': str(self.path.parent),
            "namespace_id": group.id,
            "path": self.path.name,
            "name": self.name,
        } | kwargs
        self.get = self.gl.projects.create(project_data)
        return self.get

    def delete(self):
        if self.logger:
            self.logger.info(f"Deleting project {self.path}")
        # Triggers a bug in python-gitlab:
        # https://github.com/python-gitlab/python-gitlab/issues/1494
        # self.get().delete()
        # Workaround:
        self.gl.projects.delete(str(self.path))
        with contextlib.suppress(AttributeError):
            del self.get


def users_dict(manager):
    return dict((user.username, user) for user in list_all(manager))


def members_dict(entity):
    return users_dict(entity.members)


# pylint: disable-next=redefined-outer-name
def member_create(entity, user_id, access_level, exist_ok=False, **kwargs):
    with exist_ok_check(exist_ok):
        entity.members.create(
            {
                "user_id": user_id,
                "access_level": access_level,
                **kwargs,
            }
        )


# pylint: disable-next=redefined-outer-name
def member_delete(entity, user_id, exist_ok=False):
    with exist_ok_check(exist_ok):
        entity.members.delete(user_id)


def entity_path_segment(entity):
    type_segment = {
        gitlab.v4.objects.groups.Group: "groups",
        gitlab.v4.objects.projects.Project: "projects",
    }[entity.__class__]
    return PurePosixPath(type_segment) / str(entity.id)


def invitation_list(gitlab_client, entity):
    return gitlab_client.http_list(
        str(PurePosixPath("/") / entity_path_segment(entity) / "invitations"),
        **list_all_args,
    )


def invitation_dict(gl, entity):
    """
    The argument entity is a GitLab group or project object.
    Returns a dictionary mapping email addresses to an invitation in entity.
    """
    return util.general.sdict(
        (invitation["invite_email"], invitation)
        for invitation in invitation_list(gl, entity)
    )


@gitlab.exceptions.on_http_error(gitlab.exceptions.GitlabCreateError)
def invitation_create(gitlab_client, entity, email, access_level, **kwargs):
    r = gitlab_client.http_post(
        str(PurePosixPath("/") / entity_path_segment(entity) / "invitations"),
        post_data={"email": email, "access_level": access_level, **kwargs},
    )

    if r["status"] == "error":
        message = util.general.from_singleton(r["message"].values())
        response_code = None
        if any(
            message.startswith(prefix)
            for prefix in [
                "Member already invited",
                "Already a member",
                "Invite email has already been taken",
                "The member's email address has already been taken",
                "User already exists in source",
            ]
        ):
            response_code = 409
        raise gitlab.exceptions.GitlabCreateError(message, response_code=response_code)


@gitlab.exceptions.on_http_error(gitlab.exceptions.GitlabDeleteError)
def invitation_delete(gitlab_client, entity, email):
    gitlab_client.http_delete(
        str(PurePosixPath("/") / entity_path_segment(entity) / "invitations" / email),
    )


parse_date = dateutil.parser.parse


def get_tags_sorted_by_date(project):
    tags = list_all(project.tags)
    for tag in tags:
        tag.date = parse_date(tag.commit["committed_date"])
    tags.sort(key=operator.attrgetter("date"))
    return tags


def format_given_username(username):
    """
    Format a username.
    This prepends the character '@'.
    """
    return "@" + username


def format_username(user):
    """
    Format username of a GitLab user.
    This prepends the character '@'.
    """
    return format_given_username(user.username)


def mentions(users):
    """
    Get mentions string for an iterable of users.
    Including this in an issue or comment will typically
    trigger notification to the mentioned users.

    The trailing whitespace seems necessary.
    Otherwise, edit fields flip out with autocompletion of users.
    """
    return " ".join(map(format_username, users)) + " "


def append_paragraph(text, paragraph):
    """Append a paragraph to a given Markdown text."""
    lines = text.splitlines()

    def f():
        if len(lines) != 0:
            yield from lines
            yield ""

    return util.general.join_lines(f()) + paragraph


def append_mentions(text, users):
    """Append a mentions paragraph to a given Markdown text."""
    return append_paragraph(text, mentions(users))


def project_url(project, path_segments=None, query_params=None):
    """
    Format a URL for a project request.

    Arguments:
    * project: Project in which to make the request in.
    * path_segments:
        Optional Iterable of path segments to append to the projects path to give the desired endpoint.
    * query_params: Optional query parameters represented as a dictionary mapping strings to strings.
    """
    if path_segments is None:
        path_segments = []
    if query_params is None:
        query_params = {}

    url = urllib.parse.urlparse(project.web_url)
    url = url._replace(
        path=str(PurePosixPath(url.path) / PurePosixPath(*path_segments))
    )
    url = url._replace(query=urllib.parse.urlencode(query_params))
    return urllib.parse.urlunparse(url)


# TODO:
# Add web_url attribute to lazy project instances when we can cheaply compute them.
# Then these two methods become callable on them.


def url_params_ref_type(is_tag: bool | None):
    if is_tag is None:
        return {}

    return {"ref_type": "tags" if is_tag else "heads"}


def url_tree(project, ref, is_tag: bool | None = None, path=PurePosixPath()):
    return project_url(
        project,
        ["-", "tree", str(ref), *PurePosixPath(path).parts],
        query_params=url_params_ref_type(is_tag),
    )


def url_history(project, ref, is_tag: bool | None = None):
    return project_url(
        project,
        ["-", "commits", str(ref)],
        query_params=url_params_ref_type(is_tag),
    )


# BUG:
# GitLab gets confused when references contain slashes ('/').
# Although the diff shows correctly, links back to the project are broken.
def url_compare(project, source, target):
    return project_url(
        project,
        ["-", "compare", str(source) + "..." + str(target)],
        {"straight": "true", "w": "1"},
    )


def url_tag_name(project, tag_name=None):
    def f():
        yield "-"
        yield "tags"
        if tag_name is not None:
            yield tag_name

    return project_url(project, f())


def url_tag(project, tag):
    return url_tag_name(project, tag.name)


def url_merge_request_note(merge_request, note=None):
    anchor = "notes" if note is None else f"note_{note.id}"
    return merge_request.web_url + "#" + anchor


def url_username(gl, username):
    return f"{gl.url}/{username}"


def url_user(gl, user):
    return url_username(gl, user.username)


def url_issues_new(project, **kwargs):
    """
    Format a URL for opening a new issue in a project.

    Arguments:
    * project: Relevant project.
    * kwargs:
        Parameters to initialize the issue with.
        Values should be strings.
        Commonly used keys are 'title' and 'description'.
    """
    return project_url(
        project,
        ["-", "issues", "new"],
        dict((f"issue[{key}]", value) for (key, value) in kwargs.items()),
    )


def format_tag_metadata(project, tag_name, description=None):
    def lines():
        if description:
            yield description
        yield f"* name: {tag_name}"
        url = url_tag_name(project, tag_name)
        yield f"* URL: {url}"

    return util.general.join_lines(lines())


def format_issue_metadata(issue, description=None):
    def lines():
        if description:
            yield description
        yield f"* title: {issue.title}"
        author = issue.author["name"]
        yield f"* author: {author}"
        yield f"* URL: {issue.web_url}"

    return util.general.join_lines(lines())


def move_subgroups_and_subprojects(gl, group_source, group_target):
    for group in list_all(group_source.subgroups):
        if not group.id == group_target.id:
            group = gl.groups.get(group.id)
            group.transfer(group_target.id)

    for project in list_all(group_source.projects):
        project = gl.projects.get(project.id)
        project.transfer(group_target.id)


@dataclasses.dataclass
class LabelSpec:
    name: str
    color: str


username_regex = r"[a-zA-Z0-9\.\-_]+"

pp_username = util.print_parse.regex("{}", username_regex)


class _T:
    @functools.cached_property
    def pp_add(self):
        return util.print_parse.regex("requested review from @{}", username_regex)

    @functools.cached_property
    def pp_remove(self):
        return util.print_parse.regex("removed review request for @{}", username_regex)

    @functools.cached_property
    def pp_change(self):
        return util.print_parse.regex_many(
            "requested review from @{} and removed review request for @{}",
            [username_regex, username_regex],
        )

    def __call__(self, note):
        if note.system:
            body = note.body
            with contextlib.suppress(ValueError):
                added = self.pp_add.parse(body)
                return (added, None)

            with contextlib.suppress(ValueError):
                removed = self.pp_remove.parse(body)
                return (None, removed)

            with contextlib.suppress(ValueError):
                return self.pp_change.parse(body)

        return None


parse_reviewer_change = _T()


def parse_reviewer_intervals(notes):
    reviewer = None
    start = None

    for note in notes:
        r = parse_reviewer_change(note)
        if r:
            change = (note.id, parse_date(note.created_at))
            (added, removed) = r

            if not removed == reviewer:
                raise ValueError(
                    f"Previous reviewer {added} does not match"
                    f" removed reviewer {removed}"
                )

            # Can this happen?
            if added == removed:
                continue

            if reviewer is not None:
                yield (reviewer, (start, change))

            reviewer = added
            start = change

    if reviewer is not None:
        yield (reviewer, (start, None))


def parse_label_event_action(action):
    return {
        "add": True,
        "remove": False,
    }[action]


@dataclasses.dataclass
class HookSpec:
    project: Any
    netloc: util.print_parse.NetLoc
    events: Tuple[str]
    secret_token: str


def hooks_get(project):
    """
    Get the currently installed webhooks in this projects.
    Returns a dictionary from net locations to lists of hooks.
    """

    def f():
        for hook in list_all(project.hooks):
            url = util.print_parse.url.parse(hook.url)
            yield (url.netloc, hook)

    return util.general.multidict(f())


def hook_create(spec: HookSpec):
    """
    Create webhook in the given project with the specified net location, events, and secret token.
    Hook callbacks are made via SSL, with certificate verification disabled.
    The argument netloc is an instance of util.print_parse.NetLoc.

    Arguments:
    * project: Project in which to create the webhook.
    * netloc: Net location to use.
    * events: Iterable of events (str) to watch for, e.g. 'tag_push', 'issues', 'merge_requests'.
    * secret_token: Secret token to send with each webhook callback.

    Note: Due to a GitLab bug, the webhook is not called when an issue is deleted.
    """
    url = util.print_parse.url.print(util.print_parse.URL_HTTPS(spec.netloc))
    logger.debug(f"Creating project webhook with url {url} in {spec.project.web_url}.")

    try:

        def f():
            yield ("url", url)
            yield ("enable_ssl_verification", False)
            yield ("token", spec.secret_token)
            if "push" not in spec.events:
                yield ("push_events", False)
            for event in spec.events:
                yield (f"{event}_events", True)

        return spec.project.hooks.create(dict(f()))
    except gitlab.exceptions.GitlabCreateError as e:
        if e.response_code == 422 and e.error_message == "Invalid url given":
            raise ValueError(
                f"Invalid net location {util.print_parse.netloc.print(spec.netloc)} "
                f"for a webhook in {spec.project.web_url}."
            ) from e
        raise


def hook_delete(project, hook):
    """Delete a webhook in the given project."""
    logger.debug(
        f"Deleting project webhook {hook.id} with url {hook.url} in {project.web_url}."
    )
    hook.delete()


def hooks_delete_all(project, hooks=None, except_for=None):
    """
    Delete webhooks in the given project.
    The argument netloc is an instance of util.print_parse.NetLoc.
    You should use this:
    * when manually creating and deleting hooks in separate program invocations,
    * when using hook_manager:
        if previous program runs where killed or stopped in a non-standard fashion
        that prevented cleanup and have left lingering webhooks.

    Arguments:
    * hooks: Optional hook dictionary to use (as returned by hooks_get)
    * except_for: When set to a netloc, skip deleting hooks that match.
    """
    if except_for is None:
        logger.debug("Deleting all project hooks")
    else:
        netloc_keep = util.print_parse.netloc_normalize(except_for)
        logger.debug(
            "Deleting all project hooks but those with"
            f" net location {util.print_parse.netloc.print(netloc_keep)}"
        )

    if hooks is None:
        hooks = hooks_get(project)

    for netloc, hook_list in hooks.items():
        for hook in hook_list:
            if not (except_for is not None and netloc_keep == netloc):
                hook_delete(project, hook)


def hook_check(spec: HookSpec, hooks):
    """
    Check that the given hooks dictionary (as returned by hooks_get) corresponds to a correct configuration.
    Here, correct means: as created by a single call to hook_create.
    Returns that hook on success.
    Otherwise raises ValueError.
    """
    for netloc_key, hook_list in hooks.items():
        if not netloc_key == spec.netloc:
            raise ValueError(
                f"hook for incorrect netloc {util.print_parse.netloc.print(netloc_key)}"
            )

    hook_list = hooks.get(spec.netloc)
    if not hook_list:
        raise ValueError(
            f"hook missing for given netloc {util.print_parse.netloc.print(spec.netloc)}"
        )

    try:
        [hook] = hook_list
    except ValueError:
        raise ValueError(
            f"more than one hook given netloc {util.print_parse.netloc.print(spec.netloc)}"
        ) from None

    for event in spec.events:
        if not hasattr(hook, f"{event}_events"):
            raise ValueError(f"{event} events not configured")
    if hook.enable_ssl_verification:
        raise ValueError("hook does not have SSL certificate verification disabled")

    return hook


def hook_ensure(spec: HookSpec, hooks=None):
    """
    Ensure that the webhook in this project is correctly configured.
    Also makes sure there are no other hooks.
    (This is to deal with cases of changing IP addresses.)
    Cannot check whether the secret token matches.
    Returns the ensured hook.

    If 'hooks' is None, get the hooks from the project.
    """
    logger.debug(f"Ensuring webhook configuration in {spec.project.web_url}.")
    if hooks is None:
        hooks = hooks_get(spec.project)
    try:
        return hook_check(spec, hooks)
    except ValueError:
        hooks_delete_all(spec.project, hooks)
        return hook_create(spec)


@contextlib.contextmanager
def hook_manager(spec: HookSpec):
    """
    A context manager for a webhook.
    Encapsulates hook_create and hool_delete.
    """
    hook = hook_create(spec)
    try:
        yield hook
    finally:
        hook_delete(spec.project, hook)


def event_type(event):
    """
    For some reason, GitLab is inconsistent in the field
    name of the event type attribute of a webhook event.
    This function attempts to guess it, returning its value.
    """
    for key in ["event_type", "event_name"]:
        r = event.get(key)
        if r is not None:
            return r
    raise ValueError(f"no event type found in event {event}")


class UsernameCache:
    """
    DEPRECATED

    A simple directory-based cache for data stored as a single file.
    Suitable for interprocess communication.

    For sharing between processes of different users, we recommend the following workflow.
    * Designate a supplemental group for access to the cache.
    * Add users that should have access to the cache to this group.
    * Some user in the supplemental group creates the cache directory.
      They then create every file in the directory needed by the cache as an empty placeholder, group-writable and owned by the supplemental group.

      This may be accomplished using 'create_placeholders'.
      Do not give the cache directory to the supplemental group.
      This compromises security between its users.
    * The cache can now be used by all users in the supplemental group.

    Subclasses may add more files to the cache directory as needed.
    Take care to extend 'paths' as appropriate.
    """

    def __init__(self, gl, path):
        self.gl = gl

        self.path = Path(path)
        self.path.mkdir(exist_ok=True)

        self._path_lock = self.path / "lock"
        self._path_lock_update = self.path / "lock_update"

        # Class DateFile has since been removed.
        # pylint: disable=undefined-variable
        self.last_updated = DateFile(self.path / "last_update")
        self.last_changed = DateFile(self.path / "last_changed")

        self.path_data = self.path / "data"
        self._path_hash = self.path / "hash"

        self.usernames = None

    def paths(self):
        """
        An iterable of paths used by this cache.

        Overwrite this for caches using more files.
        """
        yield self._path_lock
        yield self._path_lock_update
        yield self.last_updated.path
        yield self.last_changed.path
        yield self._path_hash
        yield self.path_data

    def create_placeholders(self, group_id):
        """
        Create placeholder files as needed for a shared cache with other users.
        Every file needed is created empty, group-writable, owned by the given group.
        """
        with util.path.working_dir(self.path):
            for path_file in list(self.paths()):
                # Function create_placeholder_file_for_group has since been removed.
                # pylint: disable=undefined-variable
                create_placeholder_file_for_group(path_file, group_id)

    @property
    @contextlib.contextmanager
    def reading(self):
        """
        A context manager for reading from the cache.
        Gives reading permissions.

        Incompatible with 'writing'.
        """
        with util.path.lock_file(self._path_lock, shared=True):
            yield

    @property
    @contextlib.contextmanager
    def writing(self):
        """
        A context manager for reading from and writing to the cache.
        Gives reading and writing permissions.

        Incompatible with 'reading'.
        """
        with util.path.lock_file(self._path_lock, shared=False):
            yield

    @property
    def inhabited(self):
        """
        Requires reading permissions.

        Checks if the cache is inhabited.
        """
        try:
            return bool(self._path_hash.read_bytes())
        except FileNotFoundError:
            return False

    def hash_differs(self, hash_: bytes):
        """
        Requires reading permissions.

        Checks if the cache hash differs with respect to the given hash.
        """
        return hash_ != self._path_hash.read_bytes()

    def hash_update(self):
        """
        Requires writing permissions.

        Updates the hash after data has been written.
        Return a boolean indicating if it changed.
        """
        with self.path_data.open("b") as file:
            hash_ = hashlib.file_digest(file, hashlib.sha1).digest()
            changed = self.hash_differs(hash_)
            if changed:
                self._path_hash.write_bytes(hash_)
            return changed

    @property
    @contextlib.contextmanager
    def updating(self):
        """
        A context manager for updating the cache.

        Updating usually involves gathering new data before writing it to the cache.
        Gathering the new data can take long (e.g., network access).
        Therefore, we may want to separaste it from writing to the cache.

        The usual flow is as follows:
          with cache.reading:


          with cache.updating:
            [check if update to desired recency already happened; if so, return]
            date = datetime.now(timezone.utc)
            [obtain the new data]
            with cache.writing:
              [write the new data to the cache]
              cache.last_updated.write(date)
        """
        with util.path.lock_file(self._path_lock_update, shared=False):
            yield
