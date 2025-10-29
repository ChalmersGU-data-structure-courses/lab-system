import collections
import contextlib
import datetime
import enum
import functools
import json
import logging
import operator
import random
import shlex
import threading
import traceback
import types
from pathlib import Path
from typing import Iterable

import atomicwrites
import gitlab
import ldap
import more_itertools

import canvas.client_rest as canvas
import chalmers_pdb.tools
import events
import gitlab_.graphql
import gitlab_.tools
import gitlab_.users_cache
import google_tools.sheets
import grading_sheet
import group_set
import lab_interfaces
import util.gdpr_coding
import util.general
import util.instance_cache
import util.ip
import util.ldap
import util.print_parse
import util.subsuming_queue
import util.threading
import util.url
import webhook_listener


# ===============================================================================
# Tools


def dict_sorted(xs):
    return dict(sorted(xs, key=operator.itemgetter(0)))


# ===============================================================================
# Course labs management


class HookCallbackError(Exception):
    pass


class InvitationStatus(str, enum.Enum):
    """
    An invitation status.
    This is:
    * LIVE: for a live invitation (not yet accepted),
    * POSSIBLY_ACCEPTED: for an invitation that has disappeared on GitLab.
    The script has no way of knowing whether the invitation email was accepted,
    rejected, or deleted by another group/project owner.
    GitLab sends status updates to the email address of the user creating the invitation.
    It is not possible to query this via the API.
    """

    LIVE = "live"
    POSSIBLY_ACCEPTED = "possibly accepted"


class Course:
    """
    This class provides the lab management for a single course
    via Chalmers GitLab and optionally Canvas for group sign-up.

    This class manages instances of lab.Lab (see the attribute labs).

    This class is configured by the config argument to its constructor.
    The format of this argument is a module as documented in gitlab.config.py.template.

    Settable attributes:
    * ssh_multiplexer:
        An optional instance of util.ssh.Multiplexer.
        Used for executing git commands for Chalmers GitLab over SSH.
    """

    def __init__(
        self,
        config,
        auth: lab_interfaces.CourseAuth,
        dir=None,
        *,
        logger=logging.getLogger(__name__),
    ):
        """
        Arguments:
        * config: Course configuration, as documented in gitlab_config.py.template.
        * auth: Authentication secrets.
        * dir: Local directory used by the Course and Lab objects for storing information.
               Each local lab repository will be created as a subdirectory with full id as name (e.g. lab-3).
               Only needed by certain methods that depend on state not recorded on Canvas or GitLab.
               If given, should exist on filesystem.
        """
        self.logger = logger
        self.config = config
        self.auth = auth
        self.dir = None if dir is None else Path(dir)

        self.ssh_multiplexer = None

        # Map from group set names on Canvas to instances of group_set.GroupSet.
        self.group_sets = {}

        # Avoid cyclic import.
        # pylint: disable-next=import-outside-toplevel
        import lab

        def lab_dir(lab_id):
            if self.dir is None:
                return None

            return self.dir / self.config.lab_id.full_id.print(lab_id)

        self.labs = {
            lab_id: lab.Lab(self, lab_id, dir=lab_dir(lab_id))
            for lab_id in self.config.labs
        }

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
    def google_credentials(self):
        return google_tools.general.get_token_for_scopes(
            google_tools.sheets.default_scopes,
            credentials=self.auth.google_credentials,
            cached_token=self.dir / "google-token",
        )

    @functools.cached_property
    def canvas(self):
        return canvas.Canvas(
            self.config.canvas_domain,
            auth_token=self.auth.canvas_auth_token,
        )

    def canvas_course_get(self, use_cache):
        return canvas.Course(
            self.canvas,
            self.config.canvas_course_id,
            use_cache=use_cache,
        )

    @functools.cached_property
    def canvas_course(self):
        return self.canvas_course_get(True)

    def canvas_course_refresh(self):
        self.logger.debug("Refreshing Canvas course")
        self.canvas_course = self.canvas_course_get(False)
        if "student_name_coding" in self.__dict__.keys():
            self.student_name_coding_update()

    @functools.cached_property
    def student_name_coding(self):
        self.logger.debug("Creating student name codings")

        def first_and_last_name(cid):
            gitlab_username = self.rectify_cid_to_gitlab_username(cid)
            canvas_user = self.canvas_user_by_gitlab_username[gitlab_username]
            return canvas.user_first_and_last_name(canvas_user)

        self.student_name_coding = util.gdpr_coding.NameCoding(
            self.dir / "gdpr_coding.json",
            first_and_last_name,
        )
        self.student_name_coding_update()
        return self.student_name_coding

    def student_name_coding_update(self):
        self.logger.debug("Updating student name codings")
        self.student_name_coding.add_ids(
            self.rectify_gitlab_username_to_cid(x)
            for x in self.gitlab_username_by_canvas_user_id.values()
        )

    def canvas_user_login_id(self, user):
        # pylint: disable-next=protected-access
        return user._dict.get("login_id")

    def canvas_profile_login_id(self, user):
        return self.canvas.get(["users", user.id, "profile"], use_cache=True).login_id

    def canvas_login_id(self, canvas_user_id):
        """
        Retrieve the login id for a user id on Canvas.
        * If this is a Chalmers user, this is CID@chalmers.
        * If this is a GU user, this is GU-ID@gu.se.
        Sometimes, the login id is just the user part of the email.
        TODO: find out when exactly this happens.

        On Chalmers Canvas, you need the Examiner role for the login_id field to appear in user queries.
        If this is not the case, we perform a workaround: querying the user profile.
        This is more expensive (one call per user profile), but we use the local Canvas cache to record the result.
        """
        user = self.canvas_course.user_details[canvas_user_id]
        login_id = self.canvas_user_login_id(user)
        if login_id is not None:
            return login_id

        login_id = self.canvas_profile_login_id(user)
        # Canvas BUG (report):
        # The login_id for REDACTED_NAME is REDACTED_CHALMERS_EMAIL,
        # but shown as abhiroop when queried via profile or on GU Chalmers.
        if login_id == "abhiroop":
            login_id = "REDACTED_CHALMERS_EMAIL"
        return login_id

    def canvas_login_id_check_consistency(self):
        """
        Check whether the login_id field of the  user coincides with the login_id field of the profile of the user.
        Reports mismatches as errors via the logger.
        """
        for x in [self.canvas_course.teacher_details, self.canvas_course.user_details]:
            for user in x.values():
                user_login_id = self.canvas_user_login_id(user)
                profile_login_id = self.canvas_profile_login_id(user)
                if not user_login_id == profile_login_id:
                    # pylint: disable=protected-access
                    self.logger.error(
                        util.general.text_from_lines(
                            f"mismatch between login ids for user {user.name}:",
                            f"* in user object: {user_login_id}",
                            f"* in profile object: {profile_login_id}",
                        )
                    )
                    util.general.print_json(user._dict)
                    util.general.print_json(
                        self.canvas.get(
                            ["users", user.id, "profile"],
                            use_cache=True,
                        )._dict
                    )

    @functools.cached_property
    def ldap_client(self):
        return ldap.initialize("ldap://ldap.chalmers.se")

    @util.instance_cache.instance_cache
    def cid_from_ldap_name(self, name):
        """
        Raises a LookupError if the given name cannot be uniquely resolved to a CID.
        """
        results = util.ldap.search_people_by_name(self.ldap_client, name)
        try:
            (result,) = results
            return result[1]["uid"][0].decode()
        except Exception as e:
            raise LookupError(f"Could not resolve {name} via LDAP") from e

    def resolve_gu_students(self):
        for canvas_id, student_details in self.canvas_course.student_details.items():
            login_id = student_details.login_id
            parts = login_id.split("@", 1)
            if len(parts) == 1:
                if not parts[0].startswith("gus"):
                    raise ValueError(f"Not GU: {parts[0]}")
                gitlab_username = self.cid_from_ldap_name(student_details.name)
                if gitlab_username is not None:
                    print(f"{canvas_id}: {gitlab_username}")
                else:
                    print(f"Ambiguous results for {student_details.name}")

    def cid_from_canvas_id_via_login_id(self, user_id):
        """
        For login IDs that look like Chalmers login IDs, return the CID directly.
        Otherwise, return None.
        """
        user_details = self.canvas_course.user_details[user_id]

        if not hasattr(user_details, "login_id"):
            raise ValueError('Canvas access token does not have role "Examiner".')

        parts = user_details.login_id.split("@", 1)
        looks_like_gu_id = parts[0].startswith("gus")

        def is_cid():
            if len(parts) == 1:
                return not looks_like_gu_id

            domain = parts[1]
            if domain == "chalmers.se":
                return True

            if domain == "gu.se":
                return False

            # Peter's exeptions
            if domain == "cse.gu.se":
                return False

            raise ValueError(f"Unknown domain part in login_id {user_details.login_id}")

        if is_cid():
            return parts[0]

    @util.instance_cache.instance_cache
    def cid_from_canvas_id_via_login_id_or_ldap_name(self, user_id):
        """
        For login IDs that look like Chalmers login IDs, return the CID directly.
        Otherwise, attempt an LDAP lookup.
        Raises a LookupError if the student name (as on Canvas) cannot be uniquely resolved to a CID.
        """
        cid = self.cid_from_canvas_id_via_login_id(user_id)
        if cid is not None:
            return cid

        user_details = self.canvas_course.user_details[user_id]
        return self.cid_from_ldap_name(user_details.name)

    @functools.cached_property
    def chalmers_pdb(self) -> chalmers_pdb.Client:
        return chalmers_pdb.Client(auth=self.auth.pdb)

    @util.instance_cache.instance_cache
    def cid_from_canvas_id_via_login_id_or_pdb(self, user_id):
        """
        For login IDs that look like Chalmers login IDs, return the CID directly.
        Otherwise, attempt a PDB lookup using the personnummer
        Raises a LookupError if the personnummer cannot be uniquely resolved to a CID.
        """
        cid = self.cid_from_canvas_id_via_login_id(user_id)
        if cid is not None:
            return cid

        user_details = self.canvas_course.user_details[user_id]
        return self.chalmers_pdb.personnummer_to_cid(user_details.sis_user_id)

    @functools.cached_property
    def gl(self):
        r = gitlab.Gitlab(
            self.config.gitlab.url,
            private_token=self.auth.gitlab_token,
            timeout=self.config.timeout.total_seconds(),
        )
        r.auth()
        return r

    @functools.cached_property
    def lab_system_users(self):
        return {
            self.gitlab_users_cache.id_from_username[username]: username
            for username in self.config.gitlab.lab_system_users
        }

    @functools.cached_property
    def entity_cached_params(self):
        return types.SimpleNamespace(
            gl=self.gl,
            logger=self.logger,
        ).__dict__

    @functools.cached_property
    def course_group(self):
        return gitlab_.tools.CachedGroup(
            **self.entity_cached_params,
            path=self.config.gitlab_path,
            name="Course Name (TODO)",
        )

    @functools.cached_property
    def graders_group(self):
        return gitlab_.tools.CachedGroup(
            **self.entity_cached_params,
            path=self.config.gitlab_path_graders,
            name="Graders",
        )

    @functools.cached_property
    def graders(self):
        return gitlab_.tools.members_from_access(
            self.graders_group.lazy,
            [gitlab.const.OWNER_ACCESS],
        )

    @functools.cached_property
    def grader_ids(self):
        """
        A dictionary from grader ids to users on Chalmers GitLab.
        Derived from self.graders.
        """
        return dict({user.id: user for user in self.graders.values()})

    # This thing is a mess.
    # TODO: refactor.
    def clear_graders(self):
        with contextlib.suppress(AttributeError):
            del self.graders
            del self.graders_ids

    # @functools.cached_property
    # def labs(self):
    #     return frozenset(
    #         self.config.lab_id.id_gitlab.parse(lab.gitlab_path)
    #         for lab in gitlab_.tools.list_all(self.labs_group.lazy.subgroups)
    #     )

    @functools.cached_property
    def gitlab_graphql_client(self):
        return gitlab_.graphql.Client(
            domain="git.chalmers.se",
            token=self.auth.gitlab_private_token,
        )

    @functools.cached_property
    def gitlab_users_cache(self):
        x = gitlab_.users_cache.UsersCache(
            self.dir / "gitlab_users", self.gitlab_graphql_client
        )
        self.logger.info("Updating Chalmers GitLab users cache.")
        x.update()  # TODO: this shouldn't happen here.
        return x

    def gitlab_user_id(self, gitlab_username):
        """
        Return the Chalmers GitLab user for a username, or None if none is found.
        Uses self.gitlab_users_cache.
        """
        return self.gitlab_users_cache.id_from_username.get(gitlab_username)

    # HACK
    def rectify_gitlab_username_to_cid(self, gitlab_username):
        return gitlab_username.removesuffix("1")

    # HACK
    def rectify_cid_to_gitlab_username(self, cid):
        keys = self.gitlab_users_cache.id_from_username.keys()
        if cid in keys:
            return cid

        weird = cid + "1"
        if weird in keys:
            return weird

        return cid

    @functools.cached_property
    def gitlab_username_by_canvas_user_id(self):
        """
        A dictionary mapping Canvas user ids to Chalmers GitLab usernames.

        Currently, the only place where self.config.gitlab_username_from_canvas_user_id is called.
        So that function does not have to be cached.
        """

        def f():
            def canvas_users():
                yield from self.canvas_course.student_details.values()
                yield from self.canvas_course.teacher_details.values()

            for canvas_user in canvas_users():
                gitlab_username = self.config.gitlab_username_from_canvas_user_id(
                    self,
                    canvas_user.id,
                )
                if gitlab_username is not None:
                    yield (canvas_user.id, gitlab_username)

        return util.general.sdict(f(), strict=False)

    def gitlab_username_from_canvas_user_id(self, canvas_user_id, strict=True):
        """
        Prints a warning and returns None if the GitLab username could not be constructed and strict is not set.
        """
        gitlab_username = self.gitlab_username_by_canvas_user_id.get(canvas_user_id)
        if gitlab_username is not None:
            return gitlab_username

        canvas_user = self.canvas_course.user_details[canvas_user_id]
        msg = (
            f"No GitLab username constructable for Canvas user {canvas_user_id}:"
            f" {canvas_user.name}, {canvas_user.login_id}, {canvas_user.sis_user_id}"
        )
        if strict:
            raise LookupError(msg)

        self.logger.warning(msg)
        return None

    @functools.cached_property
    def canvas_user_by_gitlab_username(self):
        """
        A dictionary mapping usernames on Chalmers GitLab to Canvas users.
        """
        self.logger.debug(
            "Creating dictionary mapping GitLab usernames to Canvas users"
        )

        def f():
            for (
                canvas_user_id,
                gitlab_username,
            ) in self.gitlab_username_by_canvas_user_id.items():
                yield (gitlab_username, self.canvas_course.user_details[canvas_user_id])

        return util.general.sdict(f())

    # This thing is a mess.
    # TODO: refactor.
    def clear_user_assoc_caches(self):
        with contextlib.suppress(AttributeError):
            del self.gitlab_username_by_canvas_user_id
            del self.canvas_user_by_gitlab_username
            self.gitlab_users_cache.update()

    def gitlab_username_by_canvas_id(self, canvas_id):
        """Returns the Chalmers GitLab user ID for a given Canvas user id, or None if none is found."""
        return self.gitlab_username_by_canvas_user_id.get(canvas_id)

    def gitlab_username_by_canvas_name(self, canvas_name):
        """Returns the Chalmers GitLab user for a given full name on Canvas."""
        canvas_id = self.canvas_course.user_name_to_id[canvas_name]
        return self.gitlab_username_by_canvas_id(canvas_id)

    def canvas_user_informal_name(self, user):
        """
        Find the informal name of a user on Chalmers.
        Uses self.config.names_informal.
        Defaults to the first name as given on Canvas.
        """
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
                f"Invitation history file {shlex.quote(str(path))} not found;"
                " a new one will be created."
            )
            history = {}
        try:
            yield history
        finally:
            with atomicwrites.atomic_write(path, overwrite=True) as file:
                json.dump(history, file, ensure_ascii=False, indent=4)

    def add_teachers_to_gitlab(self):
        """
        Add or invite examiners, teachers, and TAs from Chalmers/GU Canvas to the graders group on Chalmers GitLab.
        This only sends invitiations or adds users for new graders.
        Existing members of the grader group not on Canvas are not removed.
        Outdated or unrecognized invitations are removed.

        Improved version of invite_teachers_to_gitlab that uses gitlab username resolution from a Canvas user.
        Does not need a ledger of past invitations.
        """
        self.logger.info("adding teachers from Canvas to the grader group")

        members = gitlab_.tools.members_dict(self.graders_group.lazy)
        invitations = gitlab_.tools.invitation_dict(self.gl, self.graders_group.lazy)

        # Returns the set of prior invitation emails still valid.
        def invite():
            for user in self.canvas_course.teachers:
                gitlab_username = self.gitlab_username_by_canvas_user_id.get(user.id)
                gitlab_user_id = self.gitlab_users_cache.id_from_username.get(
                    gitlab_username
                )
                if not gitlab_username in members:
                    if gitlab_user_id is not None:
                        self.logger.debug(f"adding {user.name}")
                        with gitlab_.tools.exist_ok():
                            self.graders_group.lazy.members.create(
                                {
                                    "user_id": gitlab_user_id,
                                    "access_level": gitlab.const.OWNER_ACCESS,
                                }
                            )
                    else:
                        invitation = invitations.get(user.email)
                        if invitation:
                            yield user.email
                        else:
                            self.logger.debug(f"inviting {user.name} via {user.email}")
                            with gitlab_.tools.exist_ok():
                                gitlab_.tools.invitation_create(
                                    self.gl,
                                    self.graders_group.lazy,
                                    user.email,
                                    gitlab.const.OWNER_ACCESS,
                                )

        for email in invitations.keys() - invite():
            self.logger.debug(f"deleting obsolete invitation of {email}")
            with gitlab_.tools.exist_ok():
                gitlab_.tools.invitation_delete(self.gl, self.graders_group.lazy, email)

    def student_members(self, cached_entity):
        """
        Get the student members of a group or project.
        We approximate this as meaning members that have developer or maintainer rights.
        """
        return gitlab_.tools.members_from_access(
            cached_entity.lazy,
            [
                gitlab.const.DEVELOPER_ACCESS,
                gitlab.const.MAINTAINER_ACCESS,
                gitlab.const.OWNER_ACCESS,
            ],
        )

    # def empty_groups(self):
    #     for canvas_group in self.canvas_group_set.details.values():
    #         group_id = self.config.group.name.parse(canvas_group.name)
    #         cached_entity = self.group(group_id)
    #         for gitlab_user in self.student_members(cached_entity).values():
    #             cached_entity.lazy.members.delete(gitlab_user.id)

    def student_projects(self):
        """A generator for all contained student group projects."""
        for lab in self.labs.values():
            yield from lab.groups.values()

    @functools.cached_property
    def hook_netloc_default(self) -> util.url.NetLoc:
        return util.url.NetLoc(
            host=util.ip.get_local_ip_routing_to(self.config.gitlab.git_netloc),
            port=self.config.webhook.local_port,
        )

    def hook_normalize_netloc(self, netloc=None):
        """
        Normalize the given net location.

        If netloc is not given, it is set as follows:
        * ip address: address of the local interface routing to git.chalmers.se,
        * port: as configured in course configuration.
        """
        if netloc is None:
            netloc = self.hook_netloc_default
        return netloc

    def hook_specs(self, netloc=None) -> Iterable[gitlab_.tools.HookSpec]:
        for lab in self.labs.values():
            yield from lab.hook_specs(netloc)

    def hooks_create(self, netloc=None):
        def f():
            for spec in self.hook_specs(netloc):
                yield gitlab_.tools.hook_create(spec)

        return list(f())

    def hooks_delete_all(self, netloc=None, netloc_keep=None):
        """
        Delete all webhooks in all group project in all labs on GitLab.
        See gitlab_.tools.hooks_delete_all.
        TODO: make use of netloc argument to only delete matching hooks.
        """
        self.logger.info("Deleting all project hooks in all labs")
        netloc = self.hook_normalize_netloc(netloc)
        for spec in self.hook_specs(netloc):
            gitlab_.tools.hooks_delete_all(spec.project, netloc_keep=netloc_keep)

    def hooks_ensure(self, netloc=None, sample_size=10):
        """
        Ensure that all hooks for student projects in this course are correctly configured.
        By default, only a random sample is checked.

        If 'netloc' is None, uses the configured default (see Course.hook_normalize_netloc).

        If sample_size is None, checks all student projects.
        """
        self.logger.info("Ensuring webhook configuration.")
        netloc = self.hook_normalize_netloc(netloc)
        if sample_size is None:
            for spec in self.hook_specs(netloc):
                gitlab_.tools.hook_ensure(spec)
        else:
            specs = list(self.hook_specs(netloc))
            specs_selection = random.sample(specs, min(len(specs), sample_size))
            try:
                for spec in specs_selection:
                    gitlab_.tools.hook_ensure(spec)
            except ValueError as e:
                self.logger.info(
                    f"Live webhook(s) do(es) not match hook configuration {spec}: {str(e)}"
                )
                self.hooks_delete_all()
                self.hooks_create(netloc=netloc)

    @contextlib.contextmanager
    def hooks_manager(self, netloc=None):
        """
        A context manager for installing GitLab web hooks for all student projects in all lab.
        This is an expensive operation, setting up and cleaning up costs one HTTP call per project.
        Yields an iterable of hooks created.
        If 'netloc' is None, uses the configured default (see Course.hook_normalize_netloc).
        """
        self.logger.info("Creating project hooks in all labs")
        try:
            with util.general.traverse_managers_iterable(
                gitlab_.tools.hook_manager(spec) for spec in self.hook_specs(netloc)
            ) as it:
                yield list(it)
        finally:
            self.logger.info("Deleted project hooks in all labs")

    def parse_hook_event(self, hook_event, lab_full_id, project_slug, strict=False):
        """
        Arguments:
        * hook_event:
            Dictionary (decoded JSON).
            Event received from a webhook in this course.
        * lab_full_id:
            Lab id as appearing in the project path of the event.
        * project_slug:
            Project as appearing in the project path of the event.
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
        """
        # Parse the lab and group id.
        lab_id = self.config.lab.full_id.parse(lab_full_id)

        # Delegate event to lab.
        lab = self.labs.get(lab_id)
        if lab is not None:
            yield from webhook_listener.map_with_callback(
                lab.course_event,
                lab.parse_hook_event(hook_event, project_slug, strict=strict),
            )
        else:
            if strict:
                raise ValueError(f"Unknown lab id {lab_id}")

            self.logger.warning(f"Received webhook event for unknown lab id {lab_id}.")
            self.logger.debug(f"Webhook event:\n{hook_event}")

    def program_event(self, course_event):
        return events.ProgramEventInCourse(
            course_dir=self.dir,
            course_event=course_event,
        )

    @functools.cached_property
    def grading_spreadsheet(self):
        if not self.config.grading_sheet:
            raise RuntimeError("no grading spreadsheet configured")

        config = grading_sheet.Config.build(
            external=self.config.grading_sheet,
            internal=grading_sheet.ConfigInternal(
                lab=self.config.lab_id.name,
            ),
        )
        lab_configs = {
            lab.id: grading_sheet.LabConfig.build(
                external=lab.config.grading_sheet,
                internal=grading_sheet.LabConfigInternal(
                    gdpr_coding=lab.student_connector.gdpr_coding(),
                    outcome=lab.config.outcomes.as_cell,
                ),
            )
            for lab in self.labs.values()
        }
        return grading_sheet.GradingSpreadsheet(
            config,
            lab_configs,
            credentials=self.google_credentials,
        )

    # def grading_template_issue_parser(self, parsed_issues):
    #     """Specialization of parse_issues for the grading template issue."""
    #
    #     def parser(issue):
    #         self.config.grading_response_template.parse(issue.title)
    #         return ((), issue)
    #
    #     return functools.partial(
    #         self.parse_issues, "grading template", parser, parsed_issues
    #     )

    def sync_teachers_and_lab_projects(self, lab_ids):
        """
        Update graders group and student lab membership on GitLab according to information on Canvas.
        Synchronizes only those labs whose ids are specified in the set self.config.labs_to_sync.

        Arguments:
        * lab_ids: iterable of lab ids to synchronize.
        """
        self.logger.info("synchronizing teachers and students from Canvas to GitLab")

        # Update the user information.
        self.clear_user_assoc_caches()
        self.canvas_course_refresh()

        # Sync teachers.
        self.clear_graders()
        self.add_teachers_to_gitlab()
        self.clear_graders()

        # Sync students.
        synced_group_sets = set()
        for lab_id in lab_ids:
            self.labs[lab_id].sync_projects_and_students_from_canvas(synced_group_sets)

    def setup(self, use_live_submissions_table=True):
        """Sets up all labs."""
        for lab in self.labs.values():
            lab.setup(use_live_submissions_table=use_live_submissions_table)

    def initial_run(self):
        """Does initial runs of all labs."""
        for lab in self.labs.values():
            lab.initial_run()

    def run_event_loop(self, netloc=None):
        """
        Run the event loop.

        This method only returns after an event of
        kind TerminateProgram has been processed.

        The event loop starts with processing of all labs.
        So it is unnecessary to prefix it with a call to initial_run.

        Arguments:
        * netloc:
            The local net location to listen to for webhook notifications.
            If 'netloc' is None, uses the configured default (see Course.hook_normalize_netloc).
        """
        # List of context managers for managing threads we create.
        thread_managers = []

        # The event queue.
        event_queue = util.subsuming_queue.SubsumingQueue()

        def shutdown():
            event_queue.add((events.TerminateProgram(), None))

        # Set up the server for listening for group project events.
        def add_webhook_event(hook_event):
            for result in webhook_listener.parse_hook_event(
                courses_by_groups_path={self.config.path_groups: self},
                hook_event=hook_event,
                strict=False,
            ):
                event_queue.add(result)

        netloc = self.hook_normalize_netloc(netloc)
        webhook_listener_manager = webhook_listener.server_manager(
            netloc,
            self.config.webhook.secret_token,
            add_webhook_event,
        )
        with webhook_listener_manager as webhook_server:

            def webhook_server_run():
                try:
                    webhook_server.serve_forever()
                finally:
                    shutdown()

            webhook_server_thread = threading.Thread(
                target=webhook_server_run,
                name="webhook-server-listener",
            )
            thread_managers.append(
                util.general.add_cleanup(
                    util.threading.thread_manager(webhook_server_thread),
                    webhook_server.shutdown,
                )
            )

            # Set up program termination timer.
            if self.config.webhook.event_loop_runtime is not None:
                shutdown_timer = util.threading.Timer(
                    self.config.webhook.event_loop_runtime,
                    shutdown,
                    name="shutdown-timer",
                )
                thread_managers.append(util.threading.timer_manager(shutdown_timer))

            # Set up lab refresh event timers and add initial lab refreshes.
            def refresh_lab(lab):
                event_queue.add(
                    (
                        self.program_event(lab.course_event(events.RefreshLab())),
                        lab.refresh_lab,
                    )
                )

            delays = more_itertools.iterate(
                lambda x: x + self.config.webhook.first_lab_refresh_delay,
                datetime.timedelta(),
            )
            for lab in self.labs.values():
                if lab.config.refresh_period is not None:
                    refresh_lab(lab)
                    lab.refresh_timer = util.threading.Timer(
                        lab.config.refresh_period + next(delays),
                        refresh_lab,
                        args=[lab],
                        name=f"lab-refresh-timer<{lab.name}>",
                        repeat=True,
                    )
                    thread_managers.append(
                        util.threading.timer_manager(lab.refresh_timer)
                    )

            # Start the threads.
            with contextlib.ExitStack() as stack:
                for manager in thread_managers:
                    stack.enter_context(manager)

                # The event loop.
                while True:
                    self.logger.info("Waiting for event.")
                    (event, callback) = event_queue.remove()
                    if isinstance(event, events.TerminateProgram):
                        self.logger.info(
                            "Program termination event received, shutting down."
                        )
                        return

                    self.logger.info(f"Handling event {event}")
                    callback()

    def grading_report(self, scoring=None, strict=True):
        """
        Prepare a grading report for this course.
        This returns a map sending a username on Chalmers GitLab to a map sending lab ids to scores.
        The inner map is defined on lab ids for which the given username is (indirect) member of a group project.
        Scores are user-defined.

        Arguments:
        * scoring:
            A function taking a list of submission outcomes and returning a score.
            Defaults to None for no submissions and the maximum function otherwise.
        * strict:
            Refuse to compute score if there is an ungraded submission.
        """
        r = collections.defaultdict(dict)
        for lab in self.labs.values():
            for gitlab_username, score in lab.grading_report(
                scoring=scoring,
                strict=strict,
            ).items():
                r[gitlab_username][lab.id] = score
        return r

    def grading_report_with_summary(self, scoring=None, strict=True, summary=None):
        """
        Prepare a grading report for this course.
        This returns a map sending a username on Chalmers GitLab to a pair of:
        * a map sending each lab ids to a score (can be None),
        * a summary score (can be None).
        Scores are user-defined.

        Arguments:
        * scoring:
            A function taking a list of submission outcomes and returning a score.
            Defaults to None for no submissions and the maximum function otherwise.
        * strict:
            Refuse to compute score if there is an ungraded submission.
        * summary:
            A function taking a map from lab ids to scores and returning a summary score.
            Defaults to None for maps with only values None and the minimum otherwise, with None counting as 0.
        """
        u = self.grading_report(scoring=scoring, strict=strict)

        def summary_default(xs):
            xs = xs.values()
            if all(x is None for x in xs):
                return None
            return min(0 if x is None else x for x in xs)

        if summary is None:
            summary = summary_default

        def f(scores):
            scores_with_none = {
                lab.id: scores.get(lab.id) for lab in self.labs.values()
            }
            return (scores_with_none, summary(scores_with_none))

        return util.general.map_values(f, u)

    def grading_report_format_value(self, value, format_score=None):
        """
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
        """

        def format_score_default(score):
            return {
                None: "",
                0: "U",
                1: "G",
            }[score]

        if format_score is None:
            format_score = format_score_default

        (scores, summary) = value
        return util.general.map_keys_and_values(
            lambda lab_id: self.labs[lab_id].name,
            format_score,
            scores,
        ) | {"Grade": format_score(summary)}

    @contextlib.contextmanager
    def error_reporter(self, spreadsheet_id, sheet_id=0):
        """
        A context manager for reporting program errors via a Google sheet.
        Use change notifications on Google sheets to get notifications on failure.
        """
        spreadsheets = google_tools.sheets.get_client(self.google_credentials)

        try:
            yield
        except Exception:
            report = traceback.format_exc()
            google_tools.sheets.batch_update(
                spreadsheets,
                spreadsheet_id,
                [
                    google_tools.sheets.request_update_cell_user_entered_value(
                        sheet_id,
                        0,
                        0,
                        google_tools.sheets.cell_value(report),
                    )
                ],
            )
            raise

    @functools.cached_property
    def report_assignment_name(self):
        return "Labs: Canvas mirror"

    def report_assignment_create(self):
        """test"""
        self.canvas_course.post_assignment(
            {
                "name": self.report_assignment_name,
                "grading_type": "pass_fail",
                "description": "This internal assignment is used for reporting whether all labs have passed via CanLa.",
                "published": "true",
            }
        )

    def report_assignment_get(self, ensure=True):
        try:
            id = self.canvas_course.assignments_name_to_id[self.report_assignment_name]
        except KeyError:
            # pylint: disable-next=protected-access
            self.canvas_course._init_assignments(False)
            try:
                id = self.canvas_course.assignments_name_to_id[
                    self.report_assignment_name
                ]
            except KeyError:
                if not ensure:
                    raise

                self.report_assignment_create()
                # pylint: disable-next=protected-access
                self.canvas_course._init_assignments(False)
                id = self.canvas_course.assignments_name_to_id[
                    self.report_assignment_name
                ]

        return self.canvas_course.assignment_details[id]

    def report_assignment_populate(self, combining=None, scoring=None, strict=True):
        if combining is None:

            def combining(grades):
                xs = grades.values()
                if all(x is None for x in xs):
                    return None
                return min(0 if x is None else x for x in xs)

        grades = {
            lab.id: lab.grading_report(scoring=scoring, strict=strict)
            for lab in self.labs.values()
        }

        id = self.report_assignment_get().id
        submissions = self.canvas_course.get_submissions(id, use_cache=False)
        for submission in submissions:
            canvas_user_id = submission.user_id
            try:
                canvas_user = self.canvas_course.student_details[canvas_user_id]
            except KeyError:
                self.logger.warning(
                    f"* Submission user {canvas_user_id} not a Canvas user"
                    " (probably it is the test student)."
                )
                continue

            gitlab_username = self.gitlab_username_by_canvas_id(canvas_user_id)
            if gitlab_username is None:
                self.logger.warning(
                    f"* Canvas user {canvas_user.name} not on Chalmers GitLab."
                )
                continue

            def f(lab):
                # pylint: disable=cell-var-from-loop
                try:
                    grade = grades[lab.id].pop(gitlab_username)
                except KeyError:
                    self.logger.warning(
                        f"* Canvas user {canvas_user.name} not"
                        f" in {lab.name} on Chalmers GitLab."
                    )
                    return None
                if grade is None:
                    self.logger.warning(
                        f"* {gitlab_username} ({canvas_user.name}):"
                        f" no graded submission in {lab.name}."
                    )
                return grade

            student_grades = {lab.id: f(lab) for lab in self.labs.values()}
            grade = combining(student_grades)
            if grade is None:
                continue

            self.logger.info(f"* {canvas_user.name}: {grade}")
            canvas_grade = {
                0: "incomplete",
                1: "complete",
            }[grade]
            endpoint = self.canvas_course.endpoint + [
                "assignments",
                id,
                "submissions",
                canvas_user_id,
            ]
            self.canvas.put(endpoint, {"submission[posted_grade]": canvas_grade})

        for lab in self.labs.values():
            if grades[lab.id]:
                self.logger.warning(
                    f"Chalmers GitLab users with unreported grades in {lab.name}:"
                )
                for gitlab_username, grade in grades[lab.id].items():
                    print(f"* {gitlab_username}: {grade}")
