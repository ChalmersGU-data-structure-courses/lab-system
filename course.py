import atomicwrites
import contextlib
import datetime
import dateutil.parser
import enum
import functools
import general
import gitlab
import json
import logging
import operator
from pathlib import Path, PurePosixPath
import random
import shlex
import threading
import types
import urllib.parse

import more_itertools

import canvas
import events
import gitlab_tools
import grading_sheet
from instance_cache import instance_cache
import ip_tools
import print_parse
import subsuming_queue
import threading_tools
import webhook_listener

#===============================================================================
# Tools

def dict_sorted(xs):
    return dict(sorted(xs, key = operator.itemgetter(0)))

#===============================================================================
# Course labs management

class HookCallbackError(Exception):
    pass

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
    '''
    This class provides the lab management for a single course
    via Chalmers GitLab and optionally Canvas for group sign-up.

    This class manages instances of lab.Lab (see the attribute labs).

    This class is configured by the config argument to its constructor.
    The format of this argument is a module as documented in gitlab.config.py.template.
    '''
    def __init__(self, config, dir = None, *, logger = logging.getLogger(__name__)):
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
        self.dir = None if dir is None else Path(dir)

        # Qualify a request by the full group id.
        # Used as tag names in the grading repository of each lab.
        self.qualify_request = print_parse.compose(
            print_parse.on(general.component_tuple(0), self.config.group.full_id),
            print_parse.qualify_with_slash
        )

        import lab
        self.labs = dict(
            (lab_id, lab.Lab(
                self,
                lab_id,
                dir = None if self.dir is None else self.dir / self.config.lab.full_id.print(lab_id)
            ))
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
        if login_id is not None:
            return login_id

        login_id = self.canvas_profile_login_id(user)
        # Canvas BUG (report):
        # The login_id for REDACTED_NAME is REDACTED_CHALMERS_EMAIL,
        # but shown as abhiroop when queried via profile or on GU Chalmers.
        if login_id == 'REDACTED_CID':
            login_id = 'REDACTED_CHALMERS_EMAIL'
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
        return gitlab_tools.CachedGroup(
            **self.entity_cached_params,
            path = self.config.path.labs,
            name = 'Labs',
        )

    @functools.cached_property
    def groups_group(self):
        return gitlab_tools.CachedGroup(
            **self.entity_cached_params,
            path = self.config.path.groups,
            name = 'Student groups',
        )

    @functools.cached_property
    def graders_group(self):
        return gitlab_tools.CachedGroup(
            **self.entity_cached_params,
            path = self.config.path.graders,
            name = 'Graders',
        )

    @functools.cached_property
    def graders(self):
        return gitlab_tools.members_from_access(
            self.graders_group.lazy,
            [gitlab.OWNER_ACCESS]
        )

    @functools.cached_property
    def grader_ids(self):
        '''
        A dictionary from grader ids to users on Chalmers GitLab.
        Derived from self.graders.
        '''
        return dict({user.id: user for user in self.graders.values()})

    @functools.cached_property
    def labs(self):
        return frozenset(
            self.config.lab.id_gitlab.parse(lab.path)
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
        r = gitlab_tools.CachedGroup(
            **self.entity_cached_params,
            path = self.groups_group.path / self.config.group.id_gitlab.print(group_id),
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
                raise ValueError(
                    f'Group {group_name} already exists in '
                    f'Canvas group set {self.canvas_group_set.group_set.name}'
                )

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

    @functools.cached_property
    def canvas_user_by_gitlab_username(self):
        '''
        A dictionary mapping usernames on Chalmers GitLab to Canvas users.
        '''
        self.logger.debug('Creating dictionary mapping GitLab usernames to Canvas users')

        def f():
            user_sources = [self.canvas_course.student_details, self.canvas_course.teacher_details]
            for user in self.canvas_course.user_details.values():
                if any(user.id in user_source for user_source in user_sources):
                    yield (self.config.gitlab_username_from_canvas_user_id(self, user.id), user)
        return general.sdict(f())

    def gitlab_user_by_canvas_id(self, canvas_id):
        '''Returns the Chalmers GitLab user for a given Canvas user id .'''
        return self.gitlab_user(self.config.gitlab_username_from_canvas_user_id(self, canvas_id))

    def gitlab_user_by_canvas_name(self, canvas_name):
        '''returns the Chalmers GitLab user for a given full name on Canvas.'''
        canvas_id = self.canvas_course.user_name_to_id[canvas_name]
        return self.gitlab_user_by_canvas_id(canvas_id)

    def canvas_user_informal_name(self, user):
        '''
        Find the informal name of a user on Chalmers.
        Uses self.config.names_informal.
        Defaults to the first name as given on Canvas.
        '''
        try:
            return self.config.names_informal.print(user.name)
        except KeyError:
            return self.canvas_course.user_str_informal(user.id)

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

        if path_invitation_history is None:
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

    def recreate_student_invitations(self, keep_after = None):
        '''
        Recreate student invitations to groups on Chalmers GitLab.
        Since GitLab does not expose an API for resending invitations,
        we delete and recreate invitations instead.

        If the date keep_after is given (instance of datetime.datetime),
        only those invitations are recreated that have been created before the given date.
        '''
        earlier_than = '' if keep_after is None else f' earlier than {keep_after}'
        self.logger.info(f'recreating student invitations{earlier_than}.')

        for group_id in self.groups:
            entity = self.group(group_id).lazy
            entity_name = f'{self.config.group.name.print(group_id)} on GitLab'
            for invitation in self.get_invitations(entity).values():
                created_at = dateutil.parser.parse(invitation['created_at'])
                if keep_after is None or created_at < keep_after:
                    email = invitation['invite_email']
                    self.logger.info(f'Recreating invitation from {created_at} of {email} to {entity_name}.')
                    with gitlab_tools.exist_ok():
                        gitlab_tools.invitation_delete(self.gl, entity, email)
                    try:
                        with gitlab_tools.exist_ok():
                            gitlab_tools.invitation_create(self.gl, entity, email, gitlab.DEVELOPER_ACCESS)
                    except gitlab.exceptions.GitlabCreateError as e:
                        self.logger.error(str(e))

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
        #
        # This skips user ids that cannot be resolved to Canvas users.
        # Such a case can happen if a student joins a group and then later leaves the course
        # or has enrollment status reset to "pending" (that happened one, not sure how?).
        def resolve(user_ids, skip_email):
            gitlab_usernames = dict()
            emails = dict()
            for user_id in user_ids:
                try:
                    user = self.canvas_course.user_details[user_id]
                except KeyError:
                    continue
                gitlab_username = self.config.gitlab_username_from_canvas_user_id(self, user_id)

                # Only allow running with remove option if we can resolve GitLab student usernames.
                if remove and gitlab_username is None:
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
            members = dict(
                (gitlab_user.username, gitlab_user)
                for gitlab_user in gitlab_tools.members_dict(entity).values()
                if general.when(restrict_to_known, gitlab_user.username in student_gitlab_usernames)
            )
            invitations = set(
                email
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
                    except gitlab.exceptions.GitlabCreateError as e:
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

        if path_invitation_history is None:
            path_invitation_history = self.dir / 'student_invitation_history'

        with self.invitation_history(path_invitation_history) as history:
            for user in self.canvas_course.user_details.values():
                history_user = history.setdefault(str(user.id), dict())
                history_user['name'] = user.name

                def group_id_from_canvas():
                    canvas_group_id = self.canvas_group_set.user_to_group.get(user.id)
                    if canvas_group_id is None:
                        return None
                    return self.config.group.name.parse(self.canvas_group_set.details[canvas_group_id].name)
                group_id_current = group_id_from_canvas()

                # Include current group in the following iteration.
                stored_invitations = history_user.setdefault('invitations', dict())
                if group_id_current is not None:
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

    def student_members(self, cached_entity):
        '''
        Get the student members of a group or project.
        We approximate this as meaning members that have developer or maintainer rights.
        '''
        return gitlab_tools.members_from_access(
            cached_entity.lazy,
            [gitlab.DEVELOPER_ACCESS, gitlab.MAINTAINER_ACCESS]
        )

    def student_projects(self):
        '''A generator for all contained student group projects.'''
        for lab in self.labs.values():
            yield from lab.student_groups

    @functools.cached_property
    def hook_netloc_default(self):
        return print_parse.NetLoc(
            host = ip_tools.get_local_ip_routing_to(print_parse.NetLoc(
                host = print_parse.url.parse(self.config.base_url).netloc.host,
                # TODO: determine port from self.config.base_url.
                port = 443,
            )),
            port = self.config.webhook.local_port,
        )

    def hook_normalize_netloc(self, netloc = None):
        '''
        Normalize the given net location.

        If netloc is not given, it is set as follows:
        * ip address: address of the local interface routing to git.chalmers.se,
        * port: as configured in course configuration.
        '''
        if netloc is None:
            netloc = self.hook_netloc_default
        return print_parse.netloc_normalize(netloc)

    def hooks_create(self, netloc = None):
        '''
        Create webhooks in all group project in this course on GitLab with the given net location.
        See group_project.GroupProject.hook_create.
        Returns a dictionary mapping each lab to a dictionary mapping each group id to a hook.

        Use this method only if you intend to create and
        delete webhooks over separate program invocations.
        Otherwise, the context manager hooks_manager is more appropriate.

        If 'netloc' is None, uses the configured default (see Course.hook_normalize_netloc).
        '''
        self.logger.info('Creating project hooks in all labs')
        hooks = dict()
        try:
            for lab in self.labs.values():
                hooks[lab.id] = lab.hooks_create(netloc = netloc)
            return hooks
        except:  # noqa: E722
            for (lab_id, hook) in hooks.items():
                self.labs[lab_id].hooks_delete(hook, netloc = netloc)
            raise

    def hooks_delete(self, hooks, netloc = None):
        '''
        Delete webhooks in student projects in labs in this course on GitLab.
        Takes a dictionary mapping each lab id to a dictionary mapping each group id to its hook.
        See group_project.GroupProject.hook_delete.
        '''
        self.logger.info('Deleting project hooks in all labs')
        for lab in self.labs.values():
            lab.hooks_delete(hooks[lab.id], netloc = netloc)

    def hooks_delete_all(self, except_for = ()):
        '''
        Delete all webhooks in all group project in all labs set up with the given netloc on GitLab.
        See group_project.GroupProject.hook_delete_all.
        '''
        self.logger.info('Deleting all project hooks in all labs')
        for lab in self.labs.values():
            lab.hooks_delete_all(except_for = except_for)

    def hooks_ensure(self, netloc = None, sample_size = 10):
        '''
        Ensure that all hooks for student projects in this course are correctly configured.
        By default, only a random sample is checked.

        If 'netloc' is None, uses the configured default (see Course.hook_normalize_netloc).

        If sample_size is None, checks all student projects.
        '''
        self.logger.info('Ensuring webhook configuration.')
        if sample_size is None:
            for group in self.student_projects():
                group.hook_ensure(netloc = netloc)
        else:
            netloc = self.hook_normalize_netloc(netloc = netloc)
            all_groups = list(self.student_projects())
            random_sample = random.sample(all_groups, min(len(all_groups), sample_size))
            try:
                for group in random_sample:
                    group.check_hooks(netloc = netloc)
            except ValueError as e:
                self.logger.info(
                    f'Hook configuration for {group.name} in {group.lab.name} incorrect: {str(e)}'
                )
                self.hooks_delete_all()
                self.hooks_create(netloc = netloc)

    @contextlib.contextmanager
    def hooks_manager(self, netloc = None):
        '''
        A context manager for installing GitLab web hooks for all student projects in all lab.
        This is an expensive operation, setting up and cleaning up costs one HTTP call per project.
        Yields a dictionary mapping each lab id to a dictionary mapping each group id
        to the hook installed in the project of that group.

        If 'netloc' is None, uses the configured default (see Course.hook_normalize_netloc).
        '''
        self.logger.info('Creating project hooks in all labs')
        try:
            with contextlib.ExitStack() as stack:
                def f():
                    for lab in self.labs.values():
                        yield (lab.id, stack.enter_context(lab.hook_manager(netloc = netloc)))
                yield dict(f())
        finally:
            self.logger.info('Deleted project hooks in all labs')

    def parse_hook_event(self, event, strict = False):
        '''
        Takes an event received from a webhook and returns
        a corresponding instance of events.GroupProjectEvent.

        if 'strict' is set, raises an exception if
        the event is not one of the types we can handle.

        Returns None if the event should be ignored.

        Uses self.graders, which takes an HTTP call
        to compute the first time it is accessed.
        Make sure to precompute this attribute before you
        call this method in a time-sensitive environment.

        For a tag push event, we always generate a queue event.
        TODO: check that the tag name matches a request matcher.

        For an issue event, we only generate a queue event if both:
        - the (current or previous) author is a grader,
        - the title has changed.
        '''
        # Find the relevant lab and group project.
        project_path = PurePosixPath(event['project']['path_with_namespace'])
        project_path = project_path.relative_to(self.config.path.groups)
        (group_id_gitlab, lab_full_id) = project_path.parts

        # Find the lab and group ids.
        lab_id = self.config.lab.full_id.parse(lab_full_id)
        lab = self.labs[lab_id]

        group_id = self.config.group.id_gitlab.parse(group_id_gitlab)
        group = lab.student_group(group_id)

        kwargs = {
            'lab_id': lab_id,
            'group_id': group_id,
            'event': event,
        }

        event_type = webhook_listener.event_type(event)
        if event_type == 'tag_push':
            self.logger.debug(f'Received a tag push event for {group.name} in {lab.name}.')
            return events.GroupProjectEventTag(**kwargs)
        elif event_type == 'issue':
            self.logger.debug(f'Received an issue event for {group.name} in {lab.name}.')
            changes = event.get('changes')

            def author_id():
                object_attributes = event.get('object_attributes')
                if object_attributes is not None:
                    return object_attributes['author_id']

                author_id_changes = changes['author_id']
                for version in ['current', 'previous']:
                    author_id = author_id_changes[version]
                    if author_id is not None:
                        return author_id

                raise ValueError('Could not determine author id in the following issue event: {event}')
            author_id = author_id()
            author_is_grader = author_id in self.grader_ids
            self.logger.debug(
                f'Detected issue author id {author_id}, member of graders: {author_is_grader}'
            )

            def title_change():
                if changes is None:
                    return False

                title_changes = changes.get('title')
                if title_changes is None:
                    return False

                return title_changes['current'] != title_changes['previous']
            title_change = title_change()
            self.logger.debug(f'Detected title change: {title_change}')

            if author_is_grader and title_change:
                return events.GroupProjectEventTag(**kwargs)
        else:
            if strict:
                raise(f'Unknown event {event_type}')
            self.logger.debug(f'Received unexpected event with type {event_type}.')

        return None

    def hook_callback(self, event):
        '''Only supports hooks in student group projects.'''
        try:
            # Only handle certain kinds of callbacks.
            event_type = event['event_type']
            if not event_type in ['tag_push', 'issue']:
                raise(f'Unknown event type {event_type}')

            # Find the relevant lab and group project.
            project_path = PurePosixPath(event['project']['path_with_namespace'])
            project_path = project_path.relative_to(self.config.path.groups)
            (group_id_gitlab, lab_full_id) = project_path.parts

            # Find the lab.
            lab_id = self.config.lab.full_id.parse(lab_full_id)
            lab = self.labs[lab_id]

            # Find the group project.
            group_id = self.config.group.id_gitlab.parse(group_id_gitlab)
            group = lab.student_group(group_id)

            # Delegate to the lab.
            lab.hook_callback(self, event, group)

            # Find the group project.
            group_id = self.config.group.id_gitlab.parse(group_id_gitlab)
            group = lab.student_group(group_id)
        except Exception as e:
            raise HookCallbackError(e) from e

    @functools.cached_property
    def grading_spreadsheet(self):
        return grading_sheet.GradingSpreadsheet(self.config)

    def grading_template_issue_parser(self, parsed_issues):
        '''Specialization of parse_issues for the grading template issue.'''
        def parser(issue):
            self.config.grading_response_template.parse(issue.title)
            return ((), issue)

        return functools.partial(self.parse_issues, 'grading template', parser, parsed_issues)

    def setup(self, use_live_submissions_table = True):
        '''Sets up all labs.'''
        for lab in self.labs.values():
            lab.setup(use_live_submissions_table = use_live_submissions_table)

    def initial_run(self):
        '''Does initial runs of all labs.'''
        for lab in self.labs.values():
            lab.initial_run()

    def run_event_loop(self, netloc = None):
        '''
        Run the event loop.

        This method only returns after an event of
        kind ProgramTermination has been processed.

        The event loop starts with processing of all labs.
        So it is unnecessary to prefix it with a call to initial_run.

        Arguments:
        * netloc:
            The local net location to listen to for webhook notifications.
            If 'netloc' is None, uses the configured default (see Course.hook_normalize_netloc).
        '''
        # List of context managers for managing threads we create.
        thread_managers = []

        # The event queue.
        self.event_queue = subsuming_queue.SubsumingQueue()

        # Set up the server for listening for group project events.
        def add_webhook_event(hook_event):
            print(hook_event)
            event = self.parse_hook_event(hook_event)
            self.event_queue.add(event)
        netloc = self.hook_normalize_netloc(netloc)
        webhook_listener_manager = webhook_listener.server_manager(
            netloc,
            self.config.webhook.secret_token,
            add_webhook_event,
        )
        with webhook_listener_manager as self.webhook_server:
            def webhook_server_run():
                try:
                    self.webhook_server.serve_forever()
                finally:
                    self.event_queue.add(events.ProgramTermination())
            self.webhook_server_thread = threading.Thread(
                target = webhook_server_run,
                name = 'webhook-server-listener',
            )
            thread_managers.append(general.add_cleanup(
                threading_tools.thread_manager(self.webhook_server_thread),
                self.webhook_server.shutdown,
            ))

            # Set up program termination timer.
            def shutdown():
                self.event_queue.add(events.ProgramTermination())
            if self.config.webhook.event_loop_runtime is not None:
                self.shutdown_timer = threading_tools.Timer(
                    self.config.webhook.event_loop_runtime,
                    shutdown,
                    name = 'shutdown-timer',
                )
                thread_managers.append(threading_tools.timer_manager(self.shutdown_timer))

            # Set up lab refresh event timers and add initial lab refreshes.
            def refresh_lab(lab_id):
                self.event_queue.add(events.LabRefresh(lab_id))
            delays = more_itertools.iterate(
                lambda x: x + self.config.webhook.first_lab_refresh_delay,
                datetime.timedelta()
            )
            for lab in self.labs.values():
                if lab.config.refresh_period is not None:
                    self.event_queue.add(events.LabRefresh(lab.id))
                    lab.refresh_timer = threading_tools.Timer(
                        lab.config.refresh_period + next(delays),
                        refresh_lab,
                        args = [lab.id],
                        name = f'lab-refresh-timer<{lab.name}>',
                        repeat = True,
                    )
                    thread_managers.append(threading_tools.timer_manager(lab.refresh_timer))

            # Start the threads.
            with contextlib.ExitStack() as stack:
                for manager in thread_managers:
                    stack.enter_context(manager)

                # The event loop.
                while True:
                    self.logger.info('Waiting for event.')
                    event = self.event_queue.remove()
                    if isinstance(event, events.ProgramTermination):
                        self.logger.info('Program termination event received, shutting down.')
                        return
                    elif isinstance(event, events.LabEvent):
                        self.logger.debug(
                            f'Lab event received for {self.config.lab.name.print(event.lab_id)}, '
                            'forwarding to lab event handler.'
                        )
                        self.labs[event.lab_id].handle_event(event)
                    else:
                        raise ValueError(f'cannot handle event of type {type(event)}:\n{event}')

    @contextlib.contextmanager
    def error_reporter(self):
        '''
        A context manager for reporting program errors via the temp directory on Canvas.
        Hack, uses hard-coded configuration for now.
        '''
        import traceback
        import google_tools.sheets

        # Shortcut
        spreadsheets = grading_sheet.GradingSpreadsheet(self.config).google

        spreadsheet_id = '1qnG1Lfp8Y-_0MpsncASBljDb_NTn1pFk6b0pgjQwka4'
        sheet_id = '0'

        try:
            yield
        except Exception:
            report = traceback.format_exc()
            google_tools.sheets.batch_update(
                spreadsheets,
                spreadsheet_id,
                [google_tools.sheets.request_update_cell_user_entered_value(
                    google_tools.sheets.cell_value(report), sheet_id, 0, 0
                )]
            )
            raise
