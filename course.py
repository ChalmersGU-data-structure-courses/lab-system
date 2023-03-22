import atomicwrites
import collections
import contextlib
import datetime
import dateutil.parser
import enum
import functools
import general
import gitlab
import json
import ldap
import logging
import operator
from pathlib import Path
import random
import shlex
import threading
import types
from typing import Iterable

import more_itertools

import canvas
import events
import gdpr_coding
import gitlab_tools
import grading_sheet
import group_set
from instance_cache import instance_cache
import ip_tools
import ldap_tools
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

    Settable attributes:
    * ssh_multiplexer:
        An optional instance of ssh_tools.Multiplexer.
        Used for executing git commands for Chalmers GitLab over SSH.
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
        self.path = self.config.path_course

        self.ssh_multiplexer = None

        # Map from group set names on Canvas to instances of group_set.GroupSet.
        self.group_sets = dict()

        import lab
        self.labs = dict(
            (lab_id, lab.Lab(
                self,
                lab_id,
                dir = None if self.dir is None else self.dir / self.config.lab.full_id.print(lab_id)
            ))
            for lab_id in self.config.labs
        )

    def format_datetime(self, x):
        return x.astimezone(self.config.time.zone).strftime(self.config.time.format)

    def get_group_set(self, config):
        gs = self.group_sets.get(config.name)
        if gs:
            return gs

        gs = group_set.GroupSet(self, config)
        self.group_sets[config.name] = gs
        return gs

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
        if hasattr(self, 'student_name_coding'):
            self.student_name_coding_update()

    @functools.cached_property
    def student_name_coding(self):
        def first_and_last_name(cid):
            canvas_user = self.canvas_user_by_gitlab_username[cid]
            return canvas.user_first_and_last_name(canvas_user)

        self.student_name_coding = gdpr_coding.NameCoding(self.dir / 'gdpr_coding.json', first_and_last_name)
        self.student_name_coding_update()
        return self.student_name_coding

    def student_name_coding_update(self):
        self.student_name_coding.add_ids(self.gitlab_username_by_canvas_user_id.values())

    def canvas_user_login_id(self, user):
        return user._dict.get('login_id')

    def canvas_profile_login_id(self, user):
        return self.canvas.get(['users', user.id, 'profile'], use_cache = True).login_id

    def canvas_login_id(self, canvas_user_id):
        '''
        Retrieve the login id for a user id on Canvas.
        * If this is a Chalmers user, this is CID@chalmers.
        * If this is a GU user, this is GU-ID@gu.se.
        Sometimes, the login id is just the user part of the email.
        TODO: find out when exactly this happens.

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
    def ldap_client(self):
        return ldap.initialize('ldap://ldap.chalmers.se')

    @instance_cache
    def cid_from_ldap_name(self, name):
        '''Raises a LookupError if the given name cannot be uniquely resolved to a CID.'''
        results = ldap_tools.search_people_by_name(self.ldap_client, name)
        try:
            (result,) = results
            return result[1]['uid'][0].decode()
        except Exception:
            raise LookupError(f'Could not resolve {name} via LDAP')

    def resolve_gu_students(self):
        for (canvas_id, student_details) in self.canvas_course.student_details.items():
            login_id = student_details.login_id
            parts = login_id.split('@', 1)
            if len(parts) == 1:
                if not parts[0].startswith('gus'):
                    raise ValueError(f'Not GU: {parts[0]}')
                gitlab_username = self.cid_from_ldap_name(student_details.name)
                if not gitlab_username is None:
                    print(f'{canvas_id}: {gitlab_username}')
                else:
                    print(f'Ambiguous results for {student_details.name}')

    def cid_from_canvas_id_via_login_id(self, user_id):
        '''
        For login IDs that look like Chalmers login IDs, return the CID directly.
        Otherwise, return None.
        '''
        user_details = self.canvas_course.user_details[user_id]
        parts = user_details.login_id.split('@', 1)
        looks_like_gu_id = parts[0].startswith('gus')

        def is_cid():
            if len(parts) == 1:
                return not looks_like_gu_id

            domain = parts[1]
            if domain == 'chalmers.se':
                return True

            if domain == 'gu.se':
                return False

            raise ValueError(f'Unknown domain part in login_id {user_details.login_id}')

        if is_cid():
            return parts[0]

    @instance_cache
    def cid_from_canvas_id_via_login_id_or_ldap_name(self, user_id):
        '''
        For login IDs that look like Chalmers login IDs, return the CID directly.
        Otherwise, attempt an LDAP lookup.
        Raises a LookupError if the student name (as on Canvas) cannot be uniquely resolved to a CID.
        '''
        cid = self.cid_from_canvas_id_via_login_id(user_id)
        if not cid is None:
            return cid

        user_details = self.canvas_course.user_details[user_id]
        return self.cid_from_ldap_name(user_details.name)

    @instance_cache
    def cid_from_canvas_id_via_login_id_or_pdb(self, user_id):
        '''
        For login IDs that look like Chalmers login IDs, return the CID directly.
        Otherwise, attempt a PDB lookup using the personnummer
        Raises a LookupError if the personnummer cannot be uniquely resolved to a CID.
        '''
        cid = self.cid_from_canvas_id_via_login_id(user_id)
        if not cid is None:
            return cid

        from chalmers_pdb.tools import personnummer_to_cid

        user_details = self.canvas_course.user_details[user_id]
        return personnummer_to_cid(user_details.sis_user_id)

    @property
    def gitlab_netloc(self):
        return print_parse.NetLoc(
            host = print_parse.url.parse(self.config.gitlab_url).netloc.host,
            # TODO: determine port from self.config.gitlab_url.
            port = 443,
        )

    @functools.cached_property
    def gl(self):
        r = gitlab.Gitlab(
            self.config.gitlab_url,
            private_token = gitlab_tools.read_private_token(self.config.gitlab_private_token)
        )
        r.auth()
        return r

    @functools.cached_property
    def lab_system_users(self):
        return {
            user.id: user
            for name in self.config.gitlab_lab_system_users
            for user in [self.gitlab_user(name)]
        }

    @functools.cached_property
    def entity_cached_params(self):
        return types.SimpleNamespace(
            gl = self.gl,
            logger = self.logger,
        ).__dict__

    @functools.cached_property
    def course_group(self):
        return gitlab_tools.CachedGroup(
            **self.entity_cached_params,
            path = self.path,
            name = 'Course Name (TODO)',
        )

    @functools.cached_property
    def graders_group(self):
        return gitlab_tools.CachedGroup(
            **self.entity_cached_params,
            path = self.config.path_graders,
            name = 'Graders',
        )

    @functools.cached_property
    def graders(self):
        return gitlab_tools.members_from_access(
            self.graders_group.lazy,
            [gitlab.const.OWNER_ACCESS]
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
        return None if gitlab_username is None else self._gitlab_users.get(gitlab_username)

    @functools.cached_property
    def gitlab_username_by_canvas_user_id(self):
        '''
        A dictionary mapping Canvas user ids to Chalmers GitLab usernames.

        Currently, the only place where self.config.gitlab_username_from_canvas_user_id is called.
        So that function does not have to be cached.
        '''
        def f():
            def canvas_users():
                yield from self.canvas_course.student_details.values()
                yield from self.canvas_course.teacher_details.values()
            for canvas_user in canvas_users():
                gitlab_username = self.config.gitlab_username_from_canvas_user_id(self, canvas_user.id)
                if not gitlab_username is None:
                    yield (canvas_user.id, gitlab_username)
        return general.sdict(f())

    def gitlab_username_from_canvas_user_id(self, canvas_user_id, strict = True):
        '''
        Prints a warning and returns None if the GitLab username could not be constructed and strict is not set.
        '''
        gitlab_username = self.gitlab_username_by_canvas_user_id.get(canvas_user_id)
        if not gitlab_username is None:
            return gitlab_username

        msg = f'No GitLab username contructable for Canvas user {canvas_user_id}: {canvas_user.name}, {canvas_user.login_id}, {canvas_user.sis_user_id}'
        if strict:
            raise LookupError(msg)

        self.logger.warning(msg)
        return None

    @functools.cached_property
    def canvas_user_by_gitlab_username(self):
        '''
        A dictionary mapping usernames on Chalmers GitLab to Canvas users.
        '''
        self.logger.debug('Creating dictionary mapping GitLab usernames to Canvas users')

        def f():
            for (canvas_user_id, gitlab_username) in self.gitlab_username_by_canvas_user_id.items():
                yield (gitlab_username, self.canvas_course.user_details[canvas_user_id])
        return general.sdict(f())

    def gitlab_user_by_canvas_id(self, canvas_id):
        '''Returns the Chalmers GitLab user for a given Canvas user id, or None if none is found.'''
        gitlab_username = self.gitlab_username_by_canvas_user_id.get(canvas_id)
        if gitlab_username is None:
            return None

        return self.gitlab_user(gitlab_username)

    def gitlab_user_by_canvas_name(self, canvas_name):
        '''Returns the Chalmers GitLab user for a given full name on Canvas.'''
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
                gitlab_username = self.config.gitlab_username_by_canvas_user_id.get(user.id)
                gitlab_user = self.gitlab_user(gitlab_username)
                if not gitlab_username in members:
                    if gitlab_user:
                        self.logger.debug(f'adding {user.name}')
                        with gitlab_tools.exist_ok():
                            self.graders_group.lazy.members.create({
                                'user_id': gitlab_user.id,
                                'access_level': gitlab.const.OWNER_ACCESS,
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
                                    gitlab.const.OWNER_ACCESS,
                                )

        for email in invitations.keys() - invite():
            self.logger.debug(f'deleting obsolete invitation of {email}')
            with gitlab_tools.exist_ok():
                gitlab_tools.delete(self.gl, self.graders_group.lazy, email)

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
                            gitlab_tools.invitation_create(self.gl, entity, email, gitlab.const.DEVELOPER_ACCESS)
                    except gitlab.exceptions.GitlabCreateError as e:
                        self.logger.error(str(e))

    def student_members(self, cached_entity):
        '''
        Get the student members of a group or project.
        We approximate this as meaning members that have developer or maintainer rights.
        '''
        return gitlab_tools.members_from_access(
            cached_entity.lazy,
            [gitlab.const.DEVELOPER_ACCESS, gitlab.const.MAINTAINER_ACCESS]
        )

    # def empty_groups(self):
    #     for canvas_group in self.canvas_group_set.details.values():
    #         group_id = self.config.group.name.parse(canvas_group.name)
    #         cached_entity = self.group(group_id)
    #         for gitlab_user in self.student_members(cached_entity).values():
    #             cached_entity.lazy.members.delete(gitlab_user.id)

    def student_projects(self):
        '''A generator for all contained student group projects.'''
        for lab in self.labs.values():
            yield from lab.student_groups.values()

    @functools.cached_property
    def hook_netloc_default(self):
        return print_parse.NetLoc(
            host = ip_tools.get_local_ip_routing_to(self.gitlab_netloc),
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

    def hook_specs(self, netloc = None) -> Iterable[gitlab_tools.HookSpec]:
        for lab in self.labs.values():
            yield from lab.hook_specs(netloc)

    def hooks_create(self, netloc = None):
        def f():
            for spec in self.hook_specs(netloc):
                yield gitlab_tools.hook_create(spec)
        return list(f())

    def hooks_delete_all(self, netloc = None, except_for = None):
        '''
        Delete all webhooks in all group project in all labs set up with the given netloc on GitLab.
        See gitlab_tools.hooks_delete_all.
        '''
        self.logger.info('Deleting all project hooks in all labs')
        netloc = self.hook_normalize_netloc(netloc)
        for spec in self.hook_specs(netloc):
            gitlab_tools.hooks_delete_all(spec.project, except_for = except_for)

    def hooks_ensure(self, netloc = None, sample_size = 10):
        '''
        Ensure that all hooks for student projects in this course are correctly configured.
        By default, only a random sample is checked.

        If 'netloc' is None, uses the configured default (see Course.hook_normalize_netloc).

        If sample_size is None, checks all student projects.
        '''
        self.logger.info('Ensuring webhook configuration.')
        netloc = self.hook_normalize_netloc(netloc)
        if sample_size is None:
            for spec in self.hook_specs(netloc):
                gitlab_tools.hook_ensure(spec)
        else:
            specs = list(self.hook_specs(netloc))
            specs_selection = random.sample(specs, min(len(specs), sample_size))
            try:
                for spec in specs_selection:
                    gitlab_tools.hook_ensure(spec)
            except ValueError as e:
                self.logger.info(
                    f'Live webhook(s) do(es) not match hook configuration {spec}: {str(e)}'
                )
                self.hooks_delete_all()
                self.hooks_create(netloc = netloc)

    @contextlib.contextmanager
    def hooks_manager(self, netloc = None):
        '''
        A context manager for installing GitLab web hooks for all student projects in all lab.
        This is an expensive operation, setting up and cleaning up costs one HTTP call per project.
        Yields an iterable of hooks created.
        If 'netloc' is None, uses the configured default (see Course.hook_normalize_netloc).
        '''
        self.logger.info('Creating project hooks in all labs')
        try:
            with general.traverse_managers_iterable(gitlab_tools.hook_manager(spec) for spec in self.hook_specs) as it:
                yield list(it)
        finally:
            self.logger.info('Deleted project hooks in all labs')

    def parse_hook_event(self, hook_event, lab_full_id, group_id_gitlab, strict = False):
        '''
        Arguments:
        * hook_event:
            Dictionary (decoded JSON).
            Event received from a webhook in this course.
        * lab_full_id:
            Lab id as appearing in the project path of the event.
        * group_id_gitlab:
            Group id as appearing in the project path of the event.
        * strict:
            Whether to fail on unknown events.

        Returns an iterator of pairs of:
        - an instance of events.CourseEvent,
        - a callback function to handle the event.
        These are the course events triggered by the webhook event.

        Uses self.graders, which takes an HTTP call
        to compute the first time it is accessed.
        Make sure to precompute this attribute before you
        call this method in a time-sensitive environment.
        '''
        # Parse the lab and group id.
        # This logic shows that it would be simpler to organize student projects by labs first.
        # But that would be less usable for the students.
        try:
            lab_id = self.config.lab.full_id.parse(lab_full_id)
        except ValueError:
            lab_id = self.config.lab.full_id_grading.parse(lab_full_id)

        # Delegate event to lab.
        lab = self.labs.get(lab_id)
        if lab is not None:
            yield from webhook_listener.map_with_callback(
                lab.course_event,
                lab.parse_hook_event(hook_event, group_id_gitlab, strict = strict),
            )
        else:
            if strict:
                raise ValueError(f'Unknown lab id {lab_id}')

            self.logger.warning(f'Received webhook event for unknown lab id {lab_id}.')
            self.logger.debug(f'Webhook event:\n{hook_event}')

    @property
    def program_event(self):
        return lambda course_event: events.ProgramEventInCourse(
            course_dir = self.dir,
            course_event = course_event,
        )

    @functools.cached_property
    def grading_spreadsheet(self):
        return grading_sheet.GradingSpreadsheet(self.config, self.labs)

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
        kind TerminateProgram has been processed.

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

        def shutdown():
            self.event_queue.add((events.TerminateProgram(), None))

        # Set up the server for listening for group project events.
        def add_webhook_event(hook_event):
            for result in webhook_listener.parse_hook_event(
                courses_by_groups_path = {self.config.path_groups: self},
                hook_event = hook_event,
                strict = False
            ):
                self.event_queue.add(result)
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
                    shutdown()
            self.webhook_server_thread = threading.Thread(
                target = webhook_server_run,
                name = 'webhook-server-listener',
            )
            thread_managers.append(general.add_cleanup(
                threading_tools.thread_manager(self.webhook_server_thread),
                self.webhook_server.shutdown,
            ))

            # Set up program termination timer.
            if self.config.webhook.event_loop_runtime is not None:
                self.shutdown_timer = threading_tools.Timer(
                    self.config.webhook.event_loop_runtime,
                    shutdown,
                    name = 'shutdown-timer',
                )
                thread_managers.append(threading_tools.timer_manager(self.shutdown_timer))

            # Set up lab refresh event timers and add initial lab refreshes.
            def refresh_lab(lab):
                self.event_queue.add((
                    self.program_event(lab.course_event(events.RefreshLab())),
                    lab.refresh_lab,
                ))
            delays = more_itertools.iterate(
                lambda x: x + self.config.webhook.first_lab_refresh_delay,
                datetime.timedelta()
            )
            for lab in self.labs.values():
                if lab.config.refresh_period is not None:
                    refresh_lab(lab)
                    lab.refresh_timer = threading_tools.Timer(
                        lab.config.refresh_period + next(delays),
                        refresh_lab,
                        args = [lab],
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
                    (event, callback) = self.event_queue.remove()
                    if isinstance(event, events.TerminateProgram):
                        self.logger.info('Program termination event received, shutting down.')
                        return

                    self.logger.info(f'Handling event {event}')
                    callback()

    def grading_report(self, scoring = None):
        '''
        Prepare a grading report for this course.
        This returns a map sending a username on Chalmers GitLab to a map sending lab ids to scores.
        The inner map is defined on lab ids for which the given username is (indirect) member of a group project.
        Scores are user-defined.

        Arguments:
        * scoring:
            A function taking a list of submission outcomes and returning a score.
            Defaults to None for no submissions and the maximum function otherwise.
        '''
        r = collections.defaultdict(dict)
        for lab in self.labs.values():
            for (gitlab_username, score) in lab.grading_report(scoring = scoring).items():
                r[gitlab_username][lab.id] = score
        return r

    def grading_report_with_summary(self, scoring = None, summary = None):
        '''
        Prepare a grading report for this course.
        This returns a map sending a username on Chalmers GitLab to a pair of:
        * a map sending each lab ids to a score (can be None),
        * a summary score (can be None).
        Scores are user-defined.

        Arguments:
        * scoring:
            A function taking a list of submission outcomes and returning a score.
            Defaults to None for no submissions and the maximum function otherwise.
        * summary:
            A function taking a map from lab ids to scores and returning a summary score.
            Defaults to None for maps with only values None and the minimum otherwise, with None counting as 0.
        '''
        u = self.grading_report(scoring = scoring)

        def summary_default(xs):
            xs = xs.values()
            if all(x is None for x in xs):
                return None
            return min(0 if x is None else x for x in xs)
        if summary is None:
            summary = summary_default

        def f(scores):
            scores_with_none = {lab.id: scores.get(lab.id) for lab in self.labs.values()}
            return (scores_with_none, summary(scores_with_none))
        return general.map_values(f, u)

    def grading_report_format_value(self, value, format_score = None):
        '''
        Format a value in the grading report with summary as a dictionary of strings.
        We make the simplifying assumption that all individual lab scores
        and the summary score are of the same kind.

        Arguments:
        * value:
            The value to format.
            As in the map returned by grading_report_with_summary.
        * format_score:
            A function formatting a score.
            By default, formats:
            - None as the empty string,
            - 0 as 'U',
            - 1 as 'G'.
        '''
        def format_score_default(score):
            return {
                None: '',
                0: 'U',
                1: 'G',
            }[score]
        if format_score is None:
            format_score = format_score_default

        (scores, summary) = value
        return general.map_keys_and_values(
            lambda lab_id: self.labs[lab_id].name,
            format_score,
            scores,
        ) | {'Grade': format_score(summary)}

    @contextlib.contextmanager
    def error_reporter(self, spreadsheet_id, sheet_id = 0):
        '''
        A context manager for reporting program errors via a Google sheet.
        Use change notifications on Google sheets to get notifications on failure.
        '''
        import traceback
        import google_tools.sheets

        # Shortcut
        spreadsheets = grading_sheet.GradingSpreadsheet(self.config, self.labs).google

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
