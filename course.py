import atomicwrites
import contextlib
import dateutil.parser
import enum
import functools
import general
import gitlab
import json
import logging
import operator
from pathlib import Path, PurePosixPath
import re
import shlex
import types
import urllib.parse

import canvas
import gitlab_tools
from instance_cache import instance_cache
import print_parse

#===============================================================================
# Tools

def dict_sorted(xs):
    return dict(sorted(xs, key = operator.itemgetter(0)))

#===============================================================================
# Course labs management

def parse_issue(config, issue):
    request_types = config.request.__dict__
    for (request_type, spec) in request_types.items():
        for (response_type, pp) in spec.issue.__dict__.items():
            try:
                return (request_type, response_type, pp.parse(issue.title))
            except:
                continue

class InvitationStatus(str, enum.Enum):
    '''
    An invitation status.
    This is:
    * LIVE: for a live invitation (not yet accepted),
    * POSSIBLY_ACCEPTED: for an invitation that has disappeared on GitLab.
    The script has no way of knowing whether the invitation email was accepted,
    rejected, or deleted by another group/project owner.
    GitLab sends status updates to the email address of the user creating the invitation.
    It is not possible to query this via the API.
    '''
    LIVE = 'live'
    POSSIBLY_ACCEPTED = 'possibly accepted'

class Course:
    def __init__(self, config, dir = None, *, logger = logging.getLogger('course')):
        '''
        Arguments:
        * config: Course configuration, as documented in gitlab_config.py.template.
        * dir: Local directory used by the Course and Lab objects for storing information.
               Each local lab repository will be created as a subdirectory with full id as name (e.g. lab-3).
               Only needed by certain methods that depend on state not recorded on Canvas or GitLab.
               If given, should exist on filesystem.
        '''
        self.logger = logger
        self.config = config
        self.dir = Path(dir) if dir != None else None

        # Qualify a request by the full group id.
        # Used as tag names in the grading repository of each lab.
        self.qualify_request = print_parse.compose(
            print_parse.on(general.component_tuple(0), self.config.group.full_id),
            print_parse.qualify_with_slash
        )

        import lab
        self.labs = dict(
            (lab_id, lab.Lab(self, lab_id, dir = self.dir / self.config.lab.full_id.print(lab_id) if self.dir != None else None))
            for lab_id in self.config.labs
        )

    @functools.cached_property
    def canvas(self):
        return canvas.Canvas(self.config.canvas.url, auth_token = self.config.canvas_auth_token)

    def canvas_course_get(self, use_cache):
        return canvas.Course(self.canvas, self.config.canvas.course_id, use_cache = use_cache)

    @functools.cached_property
    def canvas_course(self):
        return self.canvas_course_get(True)

    def canvas_course_refresh(self):
        self.canvas_course = self.canvas_course_get(False)

    def canvas_group_set_get(self, use_cache):
        return canvas.GroupSet(self.canvas_course, self.config.canvas.group_set, use_cache = use_cache)

    @functools.cached_property
    def canvas_group_set(self):
        return self.canvas_group_set_get(True)

    def canvas_group_set_refresh(self):
        self.canvas_group_set = self.canvas_group_set_get(False)

    def canvas_user_login_id(self, user):
        return user._dict.get('login_id')

    def canvas_profile_login_id(self, user):
        return self.canvas.get(['users', user.id, 'profile'], use_cache = True).login_id

    def canvas_login_id(self, canvas_user_id):
        '''
        Retrieve the login id for a user id on Canvas.
        If this is a Chalmers user, this is CID@chalmers.
        If this is a GU user, this is GU-ID@gu.se.

        On Chalmers Canvas, you need the Examiner role for the login_id field to appear in user queries.
        If this is not the case, we perform a workaround: querying the user profile.
        This is more expensive (one call per user profile), but we use the local Canvas cache to record the result.
        '''
        user = self.canvas_course.user_details[canvas_user_id]
        login_id = self.canvas_user_login_id(user)
        if login_id != None:
            return login_id

        login_id = self.canvas_profile_login_id(user)
        # Canvas BUG (report):
        # The login_id for Abhiroop Sarkar is sarkara@chalmers.se,
        # but shown as abhiroop when queried via profile or on GU Chalmers.
        if login_id == 'abhiroop':
            login_id = 'sarkara@chalmers.se'
        return login_id

    def canvas_login_id_check_consistency(self):
        '''
        Check whether the login_id field of the  user coincides with the login_id field of the profile of the user.
        Reports mismatches as errors via the logger.
        '''
        for x in [self.canvas_course.teacher_details, self.canvas_course.user_details]:
            for user in x.values():
                user_login_id = self.canvas_user_login_id(user)
                profile_login_id = self.canvas_profile_login_id(user)
                if not user_login_id == profile_login_id:
                    self.logger.error(general.join_lines([
                        f'mismatch between login ids for user {user.name}:',
                        f'* in user object: {user_login_id}',
                        f'* in profile object: {profile_login_id}',
                    ]))
                    general.print_json(user._dict)
                    general.print_json(self.canvas.get(['users', user.id, 'profile'], use_cache = True)._dict)

    @functools.cached_property
    def gl(self):
        r = gitlab.Gitlab(
            self.config.base_url,
            private_token = gitlab_tools.read_private_token(self.config.gitlab_private_token)
        )
        r.auth()
        return r

    def gitlab_url(self, path):
        return urllib.parse.urljoin(self.config.base_url, str(path))

    @functools.cached_property
    def entity_cached_params(self):
        return types.SimpleNamespace(
            gl = self.gl,
            logger = self.logger,
        ).__dict__

    @functools.cached_property
    def labs_group(self):
        return gitlab_tools.CachedGroup(**self.entity_cached_params,
            path = self.config.path.labs,
            name = 'Labs',
        )

    @functools.cached_property
    def groups_group(self):
        return gitlab_tools.CachedGroup(**self.entity_cached_params,
            path = self.config.path.groups,
            name = 'Student groups',
        )

    @functools.cached_property
    def graders_group(self):
        return gitlab_tools.CachedGroup(**self.entity_cached_params,
            path = self.config.path.graders,
            name = 'Graders',
        )

    @functools.cached_property
    def labs(self):
        return frozenset(
            self.config.lab.id.parse(lab.path)
            for lab in gitlab_tools.list_all(self.labs_group.lazy.subgroups)
        )

    @functools.cached_property
    def groups(self):
        return frozenset(
            self.config.group.id_gitlab.parse(group.path)
            for group in gitlab_tools.list_all(self.groups_group.lazy.subgroups)
        )

    @instance_cache
    def group(self, group_id):
        r = gitlab_tools.CachedGroup(**self.entity_cached_params,
            path = self.groups_group.path / self.config.lab.id.print(group_id),
            name = self.config.group.name.print(group_id),
        )

        def create():
            gitlab_tools.CachedGroup.create(r, self.groups_group.get)
            with contextlib.suppress(AttributeError):
                del self.groups
        r.create = create

        def delete():
            gitlab_tools.CachedGroup.delete(r)
            with contextlib.suppress(AttributeError):
                del self.groups
        r.delete = delete

        return r

    def group_delete_all(self):
        for group_id in self.groups:
            self.group(group_id).delete()

    def create_groups_on_canvas(self, group_ids):
        '''
        Create (additional) additional groups with the given ids (e.g. range(50)) on Canvas.
        This uses the configured Canvas group set where students sign up for lab groups.
        Refreshes the Canvas cache and local cache of the group set (this part of the call may not be interrupted).
        '''
        group_names = general.sdict((group_id, self.config.group.name.print(group_id)) for group_id in group_ids)
        for group_name in group_names.values():
            if group_name in self.canvas_group_set.name_to_id:
                raise ValueError(f'Group {group_name} already exists in Canvas group set {self.canvas_group_set.group_set.name}')

        for group_name in group_names.values():
            self.canvas_group_set.create_group(group_name)
        self.canvas_group_set_refresh()
        with contextlib.suppress(AttributeError):
            del self.groups_on_canvas

    @functools.cached_property
    def groups_on_canvas(self):
        return dict(
            (self.config.group.name.parse(canvas_group.name), tuple(
                self.canvas_course.user_details[canvas_user_id]
                for canvas_user_id in self.canvas_group_set.group_users[canvas_group.id]
            ))
            for canvas_group in self.canvas_group_set.details.values()
        )

    def create_groups_from_canvas(self, delete_existing = False):
        if delete_existing:
            self.group_delete_all()
        groups_old = () if delete_existing else self.groups
        for (group_id, canvas_users) in self.groups_on_canvas.items():
            if not group_id in groups_old:
                self.group(group_id).create()

    @functools.cached_property
    def _gitlab_users(self):
        self.logger.info('Retrieving all users on Chalmers GitLab')
        return gitlab_tools.users_dict(self.gl.users)

    def gitlab_user(self, gitlab_username):
        '''
        Return the Chalmers GitLab user for a username, or None if none is found.

        Currently, this method uses a cached call retrieving all users on Chalmers GitLab.
        This takes about 1.5s.
        If the number of users on Chalmers GitLab grows significantly,
        it will be faster to switch to lookup calls for individual users.
        '''
        return self._gitlab_users.get(gitlab_username)

    @contextlib.contextmanager
    def invitation_history(self, path):
        try:
            with path.open() as file:
                history = json.load(file)
        except FileNotFoundError:
            self.logger.warning(
                f'Invitation history file {shlex.quote(str(path))} not found; '
                'a new one while be created.'
            )
            history = dict()
        try:
            yield history
        finally:
            with atomicwrites.atomic_write(path, overwrite = True) as file:
                json.dump(history, file, ensure_ascii = False, indent = 4)

    def get_invitations(self, entity):
        '''
        The argument entity is a GitLab group or project object.
        Returns a dictionary mapping email addresses to an invitation in entity.
        '''
        return general.sdict(
            (invitation['invite_email'], invitation)
            for invitation in gitlab_tools.invitation_list(self.gl, entity)
        )

    def add_teachers_to_gitlab(self):
        '''
        Add or invite examiners, teachers, and TAs from Chalmers/GU Canvas to the graders group on Chalmers GitLab.
        This only sends invitiations or adds users for new graders.
        Existing members of the grader group not on Canvas are not removed.
        Outdated or unrecognized invitations are removed.

        Improved version of invite_teachers_to_gitlab that uses gitlab username resolution from a Canvas user.
        Does not need a ledger of past invitations.
        '''
        self.logger.info('adding teachers from Canvas to the grader group')

        members = gitlab_tools.members_dict(self.graders_group.lazy)
        invitations = self.get_invitations(self.graders_group.lazy)

        # Returns the set of prior invitation emails still valid.
        def invite():
            for user in self.canvas_course.teachers:
                gitlab_username = self.config.gitlab_username_from_canvas_user_id(self, user.id)
                gitlab_user = self.gitlab_user(gitlab_username)
                if not gitlab_username in members:
                    if gitlab_user:
                        self.logger.debug(f'adding {user.name}')
                        with gitlab_tools.exist_ok():
                            self.graders_group.lazy.members.create({
                                'user_id': gitlab_user.id,
                                'access_level': gitlab.OWNER_ACCESS,
                            })
                    else:
                        invitation = invitations.get(user.email)
                        if invitation:
                            yield user.email
                        else:
                            self.logger.debug(f'inviting {user.name} via {user.email}')
                            with gitlab_tools.exist_ok():
                                gitlab_tools.invitation_create(
                                    self.gl,
                                    self.graders_group.lazy,
                                    user.email,
                                    gitlab.OWNER_ACCESS,
                                )

        for email in invitations.keys() - invite():
            self.logger.debug(f'deleting obsolete invitation of {email}')
            with gitlab_tools.exist_ok():
                gitlab_tools.delete(self.gl, self.graders_group.lazy, email)

    def invite_teachers_to_gitlab(self, path_invitation_history = None):
        '''
        Update invitations of examiners, teachers, TAs from Chalmers/GU Canvas to the graders group on Chalmers GitLab.
        The argument 'path_invitation_history' is to a pretty-printed JSON file that is used
        (read and written) by this method as a ledger of performed invitations.
        This is necessary because Chalmers provides no way of connecting
        a teacher on Chalmers/GU Canvas with a user on GitLab Chalmers.

        If path_invitation_history is None, it defaults to self.dir / teacher_invitation_history
        where self.dir is the directory for the course on the local filesystem (specified in the constructor).

        The ledger path_invitation_history is different from the one used by the method invite_students_to_gitlab.
        It also uses a different format.
        TODO: possibly change to using a single ledger for GitLab invitations for this the whole Canvas course.

        The file path_invitation_history is a JSON-encoded dictionary mapping Canvas user id to user entries.
        A user entry is a dictionary with keys:
        * 'name': the teacher name (only for informational purposes),
        * 'invitations': a dictionary mapping email addresses of the teacher
                         to values of the enumeration InvitationStatus.

        You can manually inspect the invitation_history to see invitation statuses.
        When this method is not running, you can also manually edit the file according to the above format.

        Deprecated.
        Use add add_teachers_to_gitlab instead.
        '''
        self.logger.info('inviting teachers from Canvas to the grader group')

        if path_invitation_history == None:
            path_invitation_history = self.dir / 'teacher_invitation_history'

        invitations_prev = self.get_invitations(self.graders_group.lazy)
        with self.invitation_history(path_invitation_history) as history:
            for user in self.canvas_course.teacher_details.values():
                history_user = history.setdefault(str(user.id), dict())
                history_user['name'] = user.name
                invitations_by_email = history_user.setdefault('invitations_by_email', dict())

                # Check status of live invitations and revoke those for old email addresses.
                for (email, status) in list(invitations_by_email.items()):
                    if status == InvitationStatus.LIVE.value:
                        invitation = invitations_prev.get(email)
                        if not invitation:
                            self.logger.debug(f'marking invitation of {email} as possibly accepted')
                            invitations_by_email[email] = InvitationStatus.POSSIBLY_ACCEPTED
                        elif not email == user.email:
                            self.logger.debug(f'deleting obsolete invitation of {email}')
                            try:
                                gitlab_tools.invitation_delete(self.gl, self.graders_group.lazy, email)
                                del invitations_by_email[email]
                            except gitlab.exceptions.GitlabCreateError as e:
                                if e.response_code == 404:
                                    invitations_by_email[email] = InvitationStatus.POSSIBLE_ACCEPTED
                                else:
                                    raise

                # Invite teacher to current group, if not already done.
                if not user.email in invitations_by_email:
                    self.logger.debug(f'creating invitation of {user.email}')
                    gitlab_tools.invitation_create(
                        self.gl,
                        self.graders_group.lazy,
                        user.email,
                        gitlab.OWNER_ACCESS,
                    )
                    invitations_by_email[user.email] = InvitationStatus.LIVE

                if not invitations_by_email:
                    history.pop(str(user.id))

    def sync_students_to_gitlab(self, *, add = True, remove = True, restrict_to_known = True):
        '''
        Synchronize Chalmers GitLab student group membership according to the group membership on Canvas.

        If add is True, this adds missing members of groups on GitLab.
        An invitation is sent if a GitLab account is not found.
        If remove is True, this removes invitations and members not belonging to groups on GitLab.
        If any of these are False, a warning is logged instead of performing the action.

        If restrict_to_known is True, removals are restricted to invitations
        and members recognized as belonging to students in the Canvas course.
        This is recommended in case there are students participating
        in the labs that are not registered in the Canvas course.
        However, a registered student can then contrive to obtain duplicate group memberships
        by changing their primary email address on Canvas prior to changing groups and accepting invitations.

        This method is simpler than invite_students_to_gitlab.
        It does not use a ledger of past invitations.
        However, it only works properly if we can resolve Canvas students to Chalmers GitLab accounts.

        Call sync_students_to_gitlab(all = False, remove = False, restrict_to_known = False)
        to obtain (via logged warnings) a report of group membership deviations.
        '''
        self.logger.info('synchronizing students from Canvas groups to GitLab group')

        # Resolve Canvas user ids to GitLab usernames and email addresses.
        # If skip_email, is true, don't collect the email address if a GitLab username is found.
        # Returns dictionaries mapping a key to a tuple whose first element is the Canvas user
        # and whose remaining elements specify details of the key.
        def resolve(user_ids, skip_email):
            gitlab_usernames = dict()
            emails = dict()
            for user_id in user_ids:
                user = self.canvas_course.user_details[user_id]
                gitlab_username = self.config.gitlab_username_from_canvas_user_id(self, user_id)

                # Only allow running with remove option if we can resolve GitLab student usernames.
                if remove and gitlab_username == None:
                    raise ValueError('called with remove option, but cannot resolve GitLab username of {user.name}')

                gitlab_user = self.gitlab_user(gitlab_username)
                if gitlab_user:
                    gitlab_usernames[gitlab_user.username] = (user, gitlab_user, )
                if not (gitlab_user and skip_email):
                    emails[user.email] = (user, )
            return (gitlab_usernames, emails)

        (
            student_gitlab_usernames,
            student_emails,
        ) = resolve(self.canvas_course.student_details, False)

        def str_with_user_details(s, user_tuple):
            details = user_tuple[0].name if user_tuple else 'unknown Canvas student'
            return f'{s} ({details})'

        def user_str_from_email(email):
            return str_with_user_details(email, student_emails.get(email))

        def user_str_from_gitlab_username(gitlab_username):
            return str_with_user_details(
                gitlab_tools.format_username(gitlab_username),
                student_gitlab_usernames.get(gitlab_username)
            )

        for canvas_group in self.canvas_group_set.details.values():
            group_id = self.config.group.name.parse(canvas_group.name)
            users = self.canvas_group_set.group_users[canvas_group.id]

            entity = self.group(group_id).lazy
            entity_name = f'{self.config.group.name.print(group_id)} on GitLab'

            # Current members and invitations.
            # If restrict_to_known holds, restricts to gitlab users and email addresses
            # recognized as belonging to Canvas students.
            self.logger.debug(f'checking {entity_name}')
            members = dict((gitlab_user.username, gitlab_user)
                for gitlab_user in gitlab_tools.members_dict(entity).values()
                if general.when(restrict_to_known, gitlab_user.username in student_gitlab_usernames)
            )
            invitations = set(email
                for email in self.get_invitations(entity)
                if general.when(restrict_to_known, email in student_emails)
            )

            # Desired members and invitations.
            (
                members_desired,
                invitations_desired,
            ) = resolve(users, True)

            for email in invitations - invitations_desired.keys():
                if remove:
                    self.logger.warning(f'deleting invitation of {user_str_from_email(email)} to {entity_name}')
                    with gitlab_tools.exist_ok():
                        gitlab_tools.invitation_delete(self.gl, entity, email)
                else:
                    self.logger.warning(f'extra invitation of {user_str_from_email(email)} to {entity_name}')

            for gitlab_username in members.keys() - members_desired.keys():
                if remove:
                    gitlab_user = members[gitlab_username]
                    self.logger.warning(
                        f'removing {user_str_from_gitlab_username(gitlab_username)} from {entity_name}'
                    )
                    with gitlab_tools.exist_ok():
                        entity.members.delete(gitlab_user.id)
                else:
                    self.logger.warning(
                        f'extra member {user_str_from_gitlab_username(gitlab_username)} of {entity_name}'
                    )

            for email in invitations_desired.keys() - invitations:
                if add:
                    self.logger.info(f'inviting {user_str_from_email(email)} to {entity_name}')
                    try:
                        with gitlab_tools.exist_ok():
                            gitlab_tools.invitation_create(self.gl, entity, email, gitlab.DEVELOPER_ACCESS)
                    except gitlab.exceptions.GitlabCreateError e:
                        self.logger.error(str(e))
                else:
                    self.logger.warning(f'missing invitation of {user_str_from_email(email)} to {entity_name}')

            for gitlab_username in members_desired.keys() - members.keys():
                if add:
                    (_, gitlab_user, ) = members_desired[gitlab_username]
                    self.logger.info(f'adding {user_str_from_gitlab_username(gitlab_username)} to {entity_name}')
                    with gitlab_tools.exist_ok():
                        entity.members.create({
                            'user_id': gitlab_user.id,
                            'access_level': gitlab.DEVELOPER_ACCESS,
                        })
                else:
                    self.logger.warning(
                        f'missing member {user_str_from_gitlab_username(gitlab_username)} of {entity_name}'
                    )

    def invite_students_to_gitlab(self, path_invitation_history):
        '''
        Update invitations of students from Chalmers/GU Canvas signed up
        for lab groups to the corresponding groups on Chalmers GitLab.
        The argument 'path_invitation_history' is to a pretty-printed JSON file that is used
        (read and written) by this method as a ledger of performed invitations.
        This is necessary because Chalmers provides no way of connecting
        a student on Chalmers/GU Canvas with a user on GitLab Chalmers.

        If path_invitation_history is None, it defaults to self.dir / student_invitation_history
        where self.dir is the directory for the course on the local filesystem (specified in the constructor).

        For each student, we consider:
        * the current group membership on Canvas,
        * the past membership invitations according to invitation_history,
        * which of the groups in invitation_history they are still a member of on GitLab.

        The file path_invitation_history is a JSON-encoded dictionary mapping Canvas user id to user entries.
        A user entry is a dictionary with keys:
        * 'name': the student name (only for informational purposes),
        * 'invitations': a dictionary mapping group names to past invitation dictionaries.
        A past invitation dictionary maps email addresses of
        the student to values of the enumeration InvitationStatus.

        You can manually inspect the invitation_history to see invitation statuses.
        When this method is not running, you can also manually edit the file according to the above format.

        In the future, this method may be extended to allow for project-based membership
        for students that change groups midway through the course.

        The method sync_students_to_gitlab provides a simpler alternative approach
        that works under different assumptions.
        '''
        self.logger.info('inviting students from Canvas groups to GitLab groups')

        if path_invitation_history == None:
            path_invitation_history = self.dir / 'student_invitation_history'

        with self.invitation_history(path_invitation_history) as history:
            for user in self.canvas_course.user_details.values():
                history_user = history.setdefault(str(user.id), dict())
                history_user['name'] = user.name

                def group_id_from_canvas():
                    canvas_group_id = self.canvas_group_set.user_to_group.get(user.id)
                    if canvas_group_id == None:
                        return None
                    return self.config.group.name.parse(self.canvas_group_set.details[canvas_group_id].name)
                group_id_current = group_id_from_canvas()

                # Include current group in the following iteration.
                stored_invitations = history_user.setdefault('invitations', dict())
                if group_id_current != None:
                    stored_invitations.setdefault(self.config.group.name.print(group_id_current), dict())

                for (group_name, invitations_by_email) in stored_invitations.items():
                    group_id = self.config.group.name.parse(group_name)
                    invitations_prev = self.get_invitations(self.group(group_id).lazy)

                    # Check status of live invitations and revoke those for email addresses or groups.
                    for (email, status) in list(invitations_by_email.items()):
                        if status == InvitationStatus.LIVE.value:
                            invitation = invitations_prev.get(email)
                            if not invitation:
                                self.logger.debug(f'marking invitation of {email} to {group_name} as possibly accepted')
                                invitations_by_email[email] = InvitationStatus.POSSIBLY_ACCEPTED
                            elif not (email == user.email and group_id == group_id_current):
                                self.logger.debug(f'deleting outdated invitation of {email} to {group_name}')
                                try:
                                    gitlab_tools.invitation_delete(self.gl, self.group(group_id).lazy, email)
                                    del invitations_by_email[email]
                                except gitlab.exceptions.GitlabDeleteError as e:
                                    if e.response_code == 404:
                                        invitations_by_email[email] = InvitationStatus.POSSIBLE_ACCEPTED
                                    else:
                                        raise

                    # Invite student to current group, if not already done.
                    if group_id == group_id_current:
                        if not user.email in invitations_by_email:
                            self.logger.debug(f'creating invitation of {user.email} to {group_name}')
                            with gitlab_tools.exist_ok():
                                gitlab_tools.invitation_create(
                                    self.gl,
                                    self.group(group_id).lazy,
                                    user.email,
                                    gitlab.DEVELOPER_ACCESS,
                                )
                            invitations_by_email[user.email] = InvitationStatus.LIVE

                    if not invitations_by_email:
                        del stored_invitations[group_name]

                if not stored_invitations:
                    history.pop(str(user.id))

    @functools.cached_property
    def graders(self):
        return gitlab_tools.members_from_access(
            self.graders_group.lazy,
            [gitlab.OWNER_ACCESS]
        )

    def student_members(self, cached_entity):
        '''
        Get the student members of a group or project.
        We approximate this as meaning members that have developer or maintainer rights.
        '''
        return gitlab_tools.members_from_access(
            cached_entity.lazy,
            [gitlab.DEVELOPER_ACCESS, gitlab.MAINTAINER_ACCESS, gitlab.OWNER_ACCESS] # TODO: delete owner case
        )

    def configure_student_project(self, project):
        self.logger.debug('Configuring student project {project.path_with_namespace}')

        def patterns():
            for spec in self.config.request.__dict__.values():
                for pattern in spec.tag_protection:
                    yield pattern

        self.logger.debug('Protecting tags')
        gitlab_tools.protect_tags(self.gl, project.id, patterns())
        self.logger.debug('Waiting for potential fork to finish')
        project = gitlab_tools.wait_for_fork(self.gl, project)
        self.logger.debug(f'Protecting branch {self.config.branch.master}')
        gitlab_tools.protect_branch(self.gl, project.id, self.config.branch.master)
        return project

    def request_namespace(self, f):
        return types.SimpleNamespace(**dict(
            (request_type, f(request_type, spec))
            for (request_type, spec) in self.config.request.__dict__.items()
        ))

    def format_tag_metadata(self, project, tag, description = None):
        def lines():
            if description:
                yield description
            yield f'* name: {tag.name}'
            path = PurePosixPath(project.path_with_namespace)
            url = self.gitlab_url(path / '-' / 'tags' / tag.name)
            yield f'* URL: {url}'
        return general.join_lines(lines())

    #def parse_request_tags(self, tags, tag_name = lambda tag: tag.name)

    def parse_request_tags(self, project):
        '''
        Parse the request tags of a project.
        A request tag is one matching the the pattern in self.config.tag.
        These are used for grading and testing requests.
        Returns an object with attributes for each request type (as specified in config.request).
        Each attribute is a list of tags sorted by committed date.

        Warning: The committed date can be controlled by students by pushing a tag
                 (instead of creating it in the web user interface) with an incorrect date.
        '''
        self.logger.debug('Parsing request tags in project {project.path_with_namespace}')

        request_types = self.config.request.__dict__
        r = self.request_namespace(lambda x, y: list())
        for tag in gitlab_tools.list_all(project.tags):
            tag.date = dateutil.parser.parse(tag.commit['committed_date'])
            for (request_type, spec) in request_types.items():
                if re.fullmatch(spec.tag_regex, tag.name):
                    r.__dict__[request_type].append(tag)
                    break
            else:
                self.logger.info(self.format_tag_metadata(project, tag,
                    f'Unrecognized tag in project {project.path_with_namespace}:'
                ))

        for xs in r.__dict__.values():
            xs.sort(key = operator.attrgetter('date'))
        return r

    def format_issue_metadata(self, project, issue, description = None):
        def lines():
            if description:
                yield description
            yield f'* title: {issue.title}'
            author = issue.author['name']
            yield f'* author: {author}'
            yield f'* URL: {issue.web_url}'
        return general.join_lines(lines())

    def response_issues(self, project):
        '''
        Retrieve the response issues in a project.
        A response issue is one created by a grader and matching an issue title in self.config.issue_title.
        These are used for grading and testing responses.
        '''
        for issue in gitlab_tools.list_all(project.issues):
            if issue.author['id'] in self.graders:
                yield issue

    def parse_response_issues(self, project):
        '''
        Parse the response issues of a project (see 'official_issues').
        Returns an object with attributes for each request type (as specified in config.request).
        Each attribute is a dictionary mapping pairs of tag names and issue types
        to pairs of an issue and the issue title parsing.
        '''
        self.logger.debug('Parsing response issues in project {project.path_with_namespace}')

        r = self.request_namespace(lambda x, y: dict())
        for issue in self.response_issues(project):
            x = parse_issue(self.config, issue)
            if x:
                (request_type, response_type, u) = x
                request_issues = r.__dict__[request_type]
                key = (u['tag'], response_type)
                prev = request_issues.get(key)
                if prev:
                    (issue_prev, _) = prev
                    self.logger.warning(
                          general.join_lines([f'Duplicate response issue in project {project.path_with_namespace}.',])
                        + self.format_issue_metadata(project, issue_prev, 'First issue:')
                        + self.format_issue_metadata(project, issue, 'Second issue:')
                        + general.join_lines(['Ignoring second issue.'])
                    )
                else:
                    request_issues[key] = (issue, u)
            else:
                self.logger.warning(self.format_issue_metadata(project, issue,
                    f'Response issue in project {project.path_with_namespace} with no matching request tag:'
                ))
        return r

    def merge_requests_and_responses(self, project, request_tags = None, response_issues = None):
        '''
        Merges the tag requests and response issues of a project.
        Returns an object with attributes for each request type (as specified in config.request).
        Each attribute is a map from request names to objects with the following attributes:
        * 'tag': the request tag,
        * response_type (for each applicable issue type):
          None (if missing) or a pair of issue and issue title parsing.
        '''
        if request_tags == None:
            request_tags = self.parse_request_tags(project)
        if response_issues == None:
            response_issues = self.parse_response_issues(project)

        def merge(request_type, spec, tags, response_map):
            def response(tag):
                r = types.SimpleNamespace(**dict(
                    (response_type, response_map.pop((tag.name, response_type), None))
                    for response_type in spec.issue.__dict__.keys()
                ))
                r.tag = tag
                return r

            r = dict((tag.name, response(tag)) for tag in tags)
            for ((tag_name, response_type), (issue, _)) in response_map.items():
                self.logger.warning(general.join_lines([
                    f'Unrequested {response_type} issue in project {project.path_with_namespace}:'
                ]) + self.format_issue_metadata(project, issue))
            return r

        return self.request_namespace(lambda request_type, spec:
            merge(request_type, spec, request_tags.__dict__[request_type], response_issues.__dict__[request_type])
        )
