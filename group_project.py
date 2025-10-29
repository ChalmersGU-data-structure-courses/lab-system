import contextlib
import functools
import itertools
import json
import logging
import shlex
import subprocess
from pathlib import PurePosixPath
from typing import Iterable

import git
import gitlab
import gitlab.v4.objects

import events
import gitlab_.tools
import grading_via_merge_request
import util.general
import util.git
import util.instance_cache
import util.item_parser
import util.markdown


class RequestAndResponses:
    """
    This class abstracts over a single request tag on Chalmers GitLab.
    It also collects the response issues posted by the lab system or graders
    in response to this request tag (as identified by their title).

    To process the request, an instance of this class is passed
    as argument to the handle_request method of the corresponding request handler.
    That method may take a variety of actions such as creating tags (and tagged commits)
    in the local collection repository (which will afterwards be pushed to the collection repository
    on GitLab Chalmers) or posting issues in the student project on GitLab Chalmers.

    Each instances of this class is managed by an instance of HandlerData.
    Instances are rather transient.
    They are reconstructed every time request tags or response issues are refreshed.
    """

    _variant: str | None
    variants: list[str] | None
    request_name: str

    def __init__(self, lab, handler_data, request_name, tag_data):
        self.lab = lab
        self.handler_data = handler_data

        self.request_name = request_name
        if isinstance(tag_data, gitlab.v4.objects.ProjectTag):
            self.gitlab_tag = tag_data
        else:
            self.gitlab_tag = None
            (self.repo_remote_tag, self.repo_remote_commit) = tag_data
        self.responses = {}

    @property
    def course(self):
        return self.lab.course

    @property
    def group(self):
        return self.handler_data.group

    @property
    def logger(self):
        return self.handler_data.logger

    @functools.cached_property
    def repo_remote_tag(self):
        return git.Reference(
            self.lab.repo,
            str(util.git.remote_tag(self.group.remote, self.request_name)),
        )

    @functools.cached_property
    def repo_remote_commit(self):
        return util.git.tag_commit(self.repo_remote_tag)

    @functools.cached_property
    def date(self):
        return util.git.commit_date(self.repo_remote_commit)

    def repo_tag(self, segments=None):
        """Forwards to self.group.repo_tag."""
        return GroupProject.repo_tag(self.group, self.request_name, segments)

    def repo_tag_exist(self, segments):
        """Forwards to self.group.repo_tag_exist."""
        return GroupProject.repo_tag_exist(self.group, self.request_name, segments)

    def repo_tag_create(self, segments=None, ref=None, **kwargs):
        """Forwards to self.group.repo_tag_create."""
        return GroupProject.repo_tag_create(
            self.group, self.request_name, segments, ref, **kwargs
        )

    def repo_tag_delete(self, segments=None):
        """Forwards to self.group.repo_tag_delete."""
        return GroupProject.repo_tag_delete(self.group, self.request_name, segments)

    def repo_tag_create_json(self, segments, ref=None, data=None, **kwargs):
        """
        Create a tag with optional JSON-encoded data as message.
        Signature is as for repo_tag_create,
        except the message keyword argument must not be used.
        Returns the created tag.
        """
        return self.repo_tag_create(
            segments,
            ref,
            message=None if data is None else json.dumps(data, indent=2),
            **kwargs,
        )

    def repo_tag_read_json(self, segments):
        """Read the JSON-encoded data in the message of a tag."""
        return json.loads(util.git.tag_message(self.repo_tag(segments)))

    def repo_tag_read_text_file(self, segments, path):
        """
        Read a text file given by 'path' (PurePosixPath)
        in the commit corresponding to 'segments'.
        """
        return util.git.read_text_file_from_tree(
            self.repo_tag(segments).commit.tree,
            path,
        )

    class CheckoutError(Exception):
        def __init__(self, request_and_responses, e):
            self.message = e.stderr
            self.request_and_responses = request_and_responses
            super().__init__(self.message)

        def report_markdown(self):
            blocks = [
                util.general.text_from_lines(
                    f"I failed to check out your commit "
                    f"`{util.markdown.escape(self.request_and_responses.request_name)}`.",
                    "This was the problem:",
                ),
                util.markdown.escape_code_block(self.message),
                util.general.text_from_lines(
                    "Please fix the problem and try again.",
                    "If you are unable to do so,"
                    " please contact the person responsible for the labs.",
                ),
            ]
            return util.markdown.join_blocks(blocks)

    def checkout(self, dir, segments=None):
        """
        Use this method instead of checkout_manager if you want to deal with checkout errors.
        """
        try:
            util.git.checkout(
                self.lab.repo,
                dir,
                self.repo_tag(segments),
                capture_stderr=True,
            )
        except subprocess.CalledProcessError as e:
            raise RequestAndResponses.CheckoutError(self, e) from e

    @contextlib.contextmanager
    def checkout_manager(self, segments=None):
        """
        In contrast to checkout, errors raised by this manager are not supposed to be catched.
        Any error is printed to stderr.
        """
        with util.git.checkout_manager(self.lab.repo, self.repo_tag(segments)) as src:
            yield src

    def repo_report_create(self, segments, dir, commit_message="", **kwargs):
        """
        Commit the directory 'dir' as a descendant of self.repo_remote_commit
        and tag it as <group full id>/<request name>/<segments>.
        Further arguments are passed to self.repo_tag_create_json.
        Returns the created tag.

        Symlinks are currently handled transparently.
        We may wish to allow for committing symlinks in the future.
        """
        tree = util.git.create_tree_from_dir(self.lab.repo, dir)
        commit = git.Commit.create_from_tree(
            repo=self.lab.repo,
            tree=tree,
            message=commit_message,
            parent_commits=[],
            author_date=self.repo_remote_commit.authored_datetime,
            commit_date=self.repo_remote_commit.committed_datetime,
        )
        return self.repo_tag_create_json(segments, ref=commit, **kwargs)

    # Tag path segment suffix used for marking requests as handled.
    segment_handled = ["handled"]

    def get_handled(self, read_data=False):
        """
        Check the local collection repository whether this request has been handled.
        This checks for the existence of a tag <group full id>/<request name>/handled.
        If read_data is set, we read JSON-encoded data from the tag message.
        """
        if not read_data:
            return self.repo_tag_exist(RequestAndResponses.segment_handled)
        return self.repo_tag_read_json(RequestAndResponses.segment_handled)

    @functools.cached_property
    def handled(self):
        return self.get_handled()

    @functools.cached_property
    def handled_result(self):
        return self.get_handled(read_data=True)

    def set_handled(self, data=None, **_kwargs):
        """
        Mark this request in the local collection repository as handled.
        See handled.
        If the optional argument data is given, it is stored in JSON-encoded format in the tag message.
        Further keyword arguments are passed to repo_tag_create.
        """
        self.repo_tag_create_json(RequestAndResponses.segment_handled, data=data)
        self.handled = True
        if data is not None:
            self.handled_result = data

    @functools.cached_property
    def accepted(self):
        """
        Returns a boolean indicating if the submission request has been accepted.
        This means that it counts as valid submission attempt, not that the submission has passed.
        See the documentation of submission handlers.
        Only valid for submission requests.
        """
        return self.handled_result["accepted"]

    @functools.cached_property
    def review_needed(self):
        """
        Returns a boolean indicating if the submission handler has requested a review.
        See the documentation of submission handlers.
        Only valid for submission requests.
        """
        return self.handled_result["review_needed"]

    @functools.cached_property
    def review(self):
        """
        Get the review response, or None if there is none.
        Only valid for accepted submission requests.

        Returns a pair (issue, title_data) on success where:
        - issue is the review issue on Chalmers GitLab,
        - title_data is the parsing produced by the response issue printer-parser.

        Can be used as a boolean to test for the existence of a review.
        """
        # Review issues must be configured to proceed.
        response_key = self.handler_data.handler.review_response_key
        if response_key is None:
            return None

        return self.responses.get(response_key)

    @functools.cached_property
    def outcome_response_key(self):
        """
        Get the outcome response key, or None if there is no outcome.
        Only valid for accepted submission requests.
        First checks for a review issue and then the result of the submission handler.
        """
        if self.review is not None:
            return self.handler_data.handler.review_response_key

        return self.handled_result.get("outcome_response_key")

    @functools.cached_property
    def outcome_with_issue(self):
        """
        Get the outcome and the associated response issue, or None if there is no such outcome.
        In the former case, returns a pair (outcome, issue) where:
        - outcome is the submission outcome,
        - issue is an instance of gitlab.v4.objects.ProjectIssue.
        Only valid for accepted submission requests.
        """
        if self.outcome_response_key is None:
            return None

        (issue, title_data) = self.responses[self.outcome_response_key]
        return (title_data["outcome"], issue)

    @functools.cached_property
    def outcome_issue(self):
        """
        The outcome issue part of 'outcome_with_issue'.
        None if the latter is None.
        """
        if self.outcome_with_issue is None:
            return None

        (_, issue) = self.outcome_with_issue
        return issue

    @functools.cached_property
    def variant(self):
        with contextlib.suppress(AttributeError):
            return self._variant

        if self.lab.config.multi_variant is None:
            return None

        return self.handled_result["variant"]

    @functools.cached_property
    def grading_merge_request(self):
        if not self.lab.config.grading_via_merge_request:
            return None

        if self.lab.config.multi_variant is None:
            return self.group.grading_via_merge_request

        return self.group.grading_via_merge_request[self.variant]

    @functools.cached_property
    def head_problem(self):
        return self.lab.head_problem(variant=self.variant)

    def outcome_link_grader_from_grading_merge_request_acc(self, accumulative=False):
        """None unless grading via merge requests has been configured"""
        if not self.lab.config.grading_via_merge_request:
            return None

        return self.grading_merge_request.outcome_with_link_and_grader(
            self.request_name, accumulative=accumulative
        )

    @functools.cached_property
    def outcome_link_grader_from_grading_merge_request(self):
        return self.outcome_link_grader_from_grading_merge_request_acc()

    def outcome_acc(self, accumulative=False):
        if self.outcome_with_issue:
            (outcome, _) = self.outcome_with_issue
            return outcome

        x = self.outcome_link_grader_from_grading_merge_request_acc(
            accumulative=accumulative
        )
        if x:
            (outcome, _, _) = x
            return outcome

        return None

    @functools.cached_property
    def outcome(self):
        return self.outcome_acc()

    @functools.cached_property
    def link(self):
        """
        Link to the outcome evidence.
        Should be viewable by students and graders.
        Only valid for submission requests with an outcome.
        """
        if self.outcome_with_issue:
            (_, issue) = self.outcome_with_issue
            return issue.web_url

        if self.outcome_link_grader_from_grading_merge_request:
            (_, link, _) = self.outcome_link_grader_from_grading_merge_request
            return link

        raise ValueError("no outcome")

    @functools.cached_property
    def grader_username(self):
        """
        Usename of grader on Chalmers GitLab.
        Only valid for submission requests with an outcome.
        """
        if self.outcome_with_issue:
            (_, issue) = self.outcome_with_issue
            return issue.author["username"]

        if self.outcome_link_grader_from_grading_merge_request:
            (_, _, grader) = self.outcome_link_grader_from_grading_merge_request
            return grader

        raise ValueError("no outcome")

    @functools.cached_property
    def grader_informal_name(self):
        """
        Get the informal name of the reviewer, or 'Lab system' for an outcome with no reviewer.
        Only valid for submission requests with an outcome.
        """
        if self.outcome_with_issue and self.review is None:
            return "Lab system"

        if self.grader_username:
            try:
                canvas_user = self.course.canvas_user_by_gitlab_username[
                    self.grader_username
                ]
            except KeyError as e:
                if self.grader_username in self.course.config.gitlab_lab_system_users:
                    return "Lab system"
                raise ValueError(
                    f"Unknown GitLab grader username {self.grader_username}. "
                    "If different from CID, consider adding as override"
                    " in _cid_to_gitlab_username in course configuration file."
                ) from e
            return self.course.canvas_user_informal_name(canvas_user)

        raise ValueError("no outcome")

    # TODO:
    # Shelved for now.
    # Best to avoid state when we can.
    # Can activate if performance becomes an issue.
    #
    # # Tag path segment suffix used for marking requests as reviewed.
    # segment_review = ['review']
    #
    # def review(self):
    #     '''
    #     Check the local collection repository whether this request has been handled.
    #     This checks for the existence of a tag <group full id>/<request name>/review.
    #     If it exists, reads the JSON-encoded data, a dictionary with the following structure:
    #     * grader: The grader who did the review (username on Chalmers Gitlab).
    #     * outcome: The outcome of the submission (submission-handler-specific).
    #     If it does not exist, returns None.
    #     '''
    #     try:
    #         return self.repo_tag_read_json(self, RequestAndResponses.segment_review)
    #     except ValueError:
    #         return None
    #
    # def update_review(self, result):
    #     '''
    #     Update the result of the review.
    #     A value of None signifies deletion.
    #     If the given value is the same as the stored one,
    #     no update occurs and we return True.
    #     Otherwise, we return False.
    #     '''
    #     if result == self.review():
    #         return False
    #
    #     if result == None:
    #         self.repo_tag_delete(RequestAndResponses.segment_review)
    #     else:
    #         self.repo_tag_create_json(RequestAndResponses.segment_review, data = result,force = True)
    #     return True

    def _repo_tag_after_segments(self, prev_name, segments=None):
        if segments is None:
            segments = []

        return [*segments, "after", prev_name]

    @util.instance_cache.instance_cache
    def repo_tag_after(self, prev_name, segments=None):
        """
        Returns an instance of git.TagReference for the tag with name
            <full group id>/<request name>/after/<prev_name>
        in the local collection repository.

        This points to a descendant commit of self.repo_remote_commit, identical in content,
        that is additionally a descendant of whatever commit prev_name refers to.
        """
        return self._repo_tag_after_segments(prev_name, segments)

    def repo_tag_after_create(self, prev_name, prev_ref, segments=None):
        """
        Given a reference prev_ref in the collection repository, create a tag
            <full group id>/<request name>/<segments>/after/<prev_name>
        for a commit that is a descendant of both self.repo_tag([*segments, 'tag']) and prev_ref.

        If the repository tag is a descendant of prev_commit, the commit is self.repo_remote_commit.
        Otherwise, it is created as a one-sided merge.

        Returns an instance of git.TagReference for the created tag.
        """
        if segments is None:
            segments = []

        prev_commit = util.git.resolve(self.lab.repo, prev_ref)
        commit = (
            self.repo_tag([*segments, "tag"]).commit
            if segments
            else self.repo_remote_commit
        )
        if not self.lab.repo.is_ancestor(prev_commit, commit):
            commit = util.git.onesided_merge(self.lab.repo, commit, prev_commit)
        return self.repo_tag_create(
            self._repo_tag_after_segments(prev_name, segments), commit, force=True
        )

    def post_response_issue(self, response_key, title_data=None, description=str()):
        if title_data is None:
            title_data = {}

        # Only allow posting if there is not already a response issue of the same type.
        if response_key in self.responses:
            raise ValueError(
                f"Response issue for {response_key} already exists "
                "for request {self.request_name} in {self.name} in {self.lab.name}"
            )

        # Make sure title_data is a dictionary and fill in request name.
        title_data = dict(title_data)
        title_data["tag"] = self.request_name

        # Post the issue.
        title = self.handler_data.handler.response_titles[response_key].print(
            title_data
        )
        self.logger.debug(
            util.general.text_from_lines(
                "Posting response issue:",
                f"* title: {title}",
                "* description:",
                *description.splitlines(),
            )
        )
        issue_data = {
            "title": title,
            "description": self.group.append_mentions(description),
        }
        issue = self.group.project.lazy.issues.create(issue_data)

        # Make sure the local response issue caches are up to date.
        issue_data = (issue, title_data)
        self.responses[response_key] = issue_data
        self.handler_data.responses[response_key][self.request_name] = issue_data

    def post_variant_failure_issue(self, response_key, title_data=None):
        assert self.variants is not None

        # TODO: change get to lazy once web_url is confirmed to exist there.
        project = self.group.project.get

        def problems():
            for variant in self.variants:
                yield self.lab.variant_problem_names[variant]

        url = gitlab_.tools.url_tag_name(project, self.request_name)
        ref = f"[{self.request_name}]({url})"
        if not self.variants:
            reason = "does not have a problem stub"
        else:
            reason = f"has multiple problem stubs ({", ".join(problems())})"

        history = gitlab_.tools.url_history(project, self.request_name, True)
        msg = (
            f"The lab system is confused because your tag {ref}"
            f" {reason} in its [commit history]({history})."
        )

        def all_problems():
            for problem in self.lab.variant_problem_names.values():
                url = gitlab_.tools.url_tree(project, problem, False)
                yield f"* [{problem}]({url})"

        description = util.general.text_from_lines(
            msg,
            "The following problem stubs were searched for:",
            *all_problems(),
            "",
            "Please create another tag for a commit that has exactly one of the above commits as an ancestor.",
            "If you are unsure how to do this, please seek help.",
        )
        self.post_response_issue(response_key, title_data, description)

    def process_request_inner(self):
        where = "" if self.group is None else f" in {self.group.name}"
        self.logger.info(f"Processing request {self.request_name}{where}.")

        # Create tag <full group id>/<request name>/tag copying the request tag.
        self.repo_tag_create(
            ref=self.repo_remote_commit,
            message=util.git.tag_message(self.repo_remote_tag),
            force=True,
        )

        # If a submission failure already exists, we are happy.
        variant_failure_key = None
        with contextlib.suppress(AttributeError):
            variant_failure_key = self.handler_data.handler.variant_failure_key
        if variant_failure_key in self.responses:
            return {"accepted": False}

        # Attempt to detect variant.
        self._variant = None
        self.variants = None
        try:
            self._variant = self.group.detect_variant(self.repo_remote_commit)
        except util.general.UniquenessError as e:
            self.variants = list(e.iterator)
            self.logger.warn(
                util.general.text_from_lines(
                    f"Language detection failure: (candidates {self.variants}).",
                    f"* {self.lab.name}",
                    f"* {self.group.name}",
                    f"* {self.request_name}",
                )
            )

            # Language detection failure for official solution is not allowed.
            if self.group.is_solution:
                raise ValueError(
                    "Language detection failure in official solution."
                ) from e

            if (
                variant_failure_key is not None
                and self.lab.config.multi_variant is not None
            ):
                self.post_variant_failure_issue(variant_failure_key, {})
                return {"accepted": False}

        # Call handler with this object as argment.
        self.logger.debug(
            f"Handling request {self.request_name} {where} "
            f"using handler {self.handler_data.handler_key}"
        )
        result = self.handler_data.handler.handle_request(self)

        if result is not None:
            self.logger.debug(util.general.join_lines(["Handler result:", str(result)]))

        def checks():
            yield self.lab.config.grading_via_merge_request
            yield self.group
            yield self.handler_data.is_submission_handler
            yield result["accepted"]
            yield result["review_needed"]

        if all(checks()):
            if self.lab.config.multi_variant is not None:
                if self._variant is None:
                    msg = "Language detection failed, but submission handler successed."
                    self.logger.error(msg)
                    raise ValueError(msg)

                # Hacky workaround to an issue in redesign of variant handling.
                if result is None:
                    result = {}

                assert isinstance(result, dict)
                result["variant"] = self._variant

            self.grading_merge_request.sync_submission(self)

        return result

    def process_request(self):
        """
        Process request.
        This only proceeds if the request is not already
        marked handled in the local collection repository.

        Returns a boolean indicating if the request was not handled before.
        """
        # Skip processing if we already handled this request.
        if self.get_handled():
            return False

        self.lab.update_manager.mark_dirty(self.group.id)
        result = self.process_request_inner()

        # Create tag <full-group-id>/<request_name>/handled
        # and store handler's result JSON-encoded as its message.
        self.set_handled(result)

        # Clear cache of tags in the local collection repository.
        with contextlib.suppress(AttributeError):
            del self.lab.tags

        return True


class HandlerData:
    """
    This class abstracts over a request handler handling a single type of request
    students may make in their group project for a particular lab on Chalmers GitLab.
    It also collects request tags and response issues associated with this handler
    before they are combined into instances of RequestAndResponses,
    which are also collected by this class.

    Each instance of this class is managed by an instance of GroupProject.
    """

    def __init__(self, group, handler_key):
        self.group = group
        self.handler_key = handler_key
        self.handler = self.lab.config.request_handlers[handler_key]

        # A dictionary mapping request names to tags, which are an instance of one of:
        # - gitlab.v4.objects.tags.ProjectTag,
        # - pairs of git.Reference and git.Commit.
        # Ordered by date.
        #
        # Populated by GroupProject.parse_requests_tags.
        # Initializes with None.
        self.requests = None

        # A dictionary mapping keys of response titles to dictionaries
        # mapping request names to pairs of issues and issue title parsings.
        #
        # Populated by GroupProject.parse_response_issues.
        # Initialized with inner dictionaries set to None.
        self.responses = {
            response_key: None for response_key in self.handler.response_titles.keys()
        }

        # Ist his the submission handler?
        self.is_submission_handler = (
            handler_key == self.lab.config.submission_handler_key
        )

    @property
    def course(self):
        return self.group.course

    @property
    def lab(self):
        return self.group.lab

    @property
    def logger(self):
        return self.group.logger

    def request_tag_parser_data(self):
        """
        Prepare parser_data entries for a request tag parsing call to util.item_parser.parse_all_items.
        Initializes the requests map.
        Returns an entry for use in the parser_data iterable.
        """

        def parser(item):
            (tag_name, tag_data) = item
            if self.handler.request_matcher.parse(tag_name) is None:
                return None
            return (tag_name, tag_data)

        u = {}
        self.requests = u
        return (parser, self.handler_key, u)

    def response_issue_parser_data(self):
        """
        Prepare parser_data entries for a response issue parsing call to util.item_parser.parse_all_items.
        Initializes the responses map.
        Returns iterable of parser_data entries.
        """
        for response_key, response_title in self.handler.response_titles.items():
            # Python scoping is bad.
            # Do the workaround using default arguments.
            def parser(
                issue,
                _response_key=response_key,
                response_title=response_title,
            ):
                title = issue.title
                parse = response_title.parse.__call__
                try:
                    r = parse(title)
                # We currently rely on generic exceptions to detect parse failure.
                # For example, these can be ValueError, LookupError, IndexError.
                # pylint: disable-next=broad-exception-caught
                except Exception:
                    return None
                return (r["tag"], (issue, r))

            u = {}
            self.responses[response_key] = u
            yield (parser, f"{self.handler_key} {response_key}", u)

    @functools.cached_property
    def requests_and_responses(self):
        """
        A dictionary pairing request tags with response issues.
        The keys are request names.
        Each value is an instance of RequestAndResponses.
        Before this cached property can be constructed,
        calls parse_request_tags and parse_response_issues need to complete.
        """
        result = {}
        for request_name, tag_data in self.requests.items():
            result[request_name] = RequestAndResponses(
                self.lab,
                self,
                request_name,
                tag_data,
            )

        for response_key, u in self.responses.items():
            for request_name, issue_data in u.items():
                request_and_responses = result.get(request_name)
                if request_and_responses is None:
                    self.logger.warning(
                        gitlab_.tools.format_issue_metadata(
                            issue_data[0],
                            f"Response issue in {self.group.name} "
                            "with no matching request tag (ignoring):",
                        )
                    )
                else:
                    request_and_responses.responses[response_key] = issue_data
        return result

    def requests_and_responses_handled(self):
        def f():
            for request_and_responses in self.requests_and_responses.values():
                if request_and_responses.handled:
                    yield request_and_responses

        return tuple(f())

    def process_requests(self):
        """
        Process requests.
        This method assumes that requests_and_responses has been set up.
        It skips requests already marked as handled in the local collection repository.

        Returns the set of request names that were newly handled.
        """

        def f():
            for request_and_responses in self.requests_and_responses.values():
                if request_and_responses.process_request():
                    yield request_and_responses.request_name

        return set(f())


class GroupProject:
    """
    This class abstracts over:
    * a lab project of a student or lab group,
    * a primary solution
    on Chalmers GitLab.
    It collects instances of HandlerData.
    Each instances of this class is managed by an instance of lab.Lab.
    """

    def __init__(self, lab, id, logger=logging.getLogger(__name__)):
        self.lab = lab
        self.id = id
        self.logger = logger

        self.is_solution = lab.group_id_is_solution(id)
        if self.is_solution:
            self.is_known = True
            self.remote = self.id
            self.path_name = self.id
            self.name = self.lab.solutions[self.id]
        else:
            c = self.lab.student_connector
            self.is_known = self.id in self.lab.group_ids_desired
            self.remote = c.gitlab_group_slug_pp().print(id)
            self.path_name = f"{self.lab.group_prefix}{self.remote}"
            self.name = (
                f"{self.lab.name_full} "
                f"— {self.lab.student_connector.gitlab_group_name(id)}"
            )

        self.path = self.lab.path / self.path_name
        # if self.is_known:
        self.handler_data = {
            handler_key: HandlerData(self, handler_key)
            for handler_key in self.lab.config.request_handlers.keys()
        }

    @property
    def course(self):
        return self.lab.course

    @property
    def gl(self):
        return self.lab.gl

    @functools.cached_property
    def group(self):
        r = gitlab_.tools.CachedGroup(
            gl=self.gl,
            logger=self.logger,
            path=self.path,
            name=self.name,
        )

        def create():
            gitlab_.tools.CachedGroup.create(r, self.lab.gitlab_group.get)
            with contextlib.suppress(AttributeError):
                del self.lab.groups

        r.create = create

        def delete():
            gitlab_.tools.CachedGroup.delete(r)
            with contextlib.suppress(AttributeError):
                self.lab.groups.pop(self.id)

        r.delete = delete

        return r

    @functools.cached_property
    def project(self):
        """
        The lab project on Chalmers GitLab.
        On creation, the repository is forked from the primary repository.
        That one needs to be initialized.
        """
        r = gitlab_.tools.CachedProject(
            gl=self.gl,
            logger=self.logger,
            path=self.path,
            name=self.name,
        )

        def create():
            # Handle duplicate project name.
            # GitLab does not allow this.
            # This will happen for individual labs where two students have the same name.
            # Can just retry with 2, 3, 4, ... appended.
            for i in itertools.count(0):
                try:
                    suffix = "" if i == 0 else " " + str(i + 1)
                    project_data = {
                        "namespace_path": str(r.path.parent),
                        "path": r.path.name,
                        "name": r.name + suffix,
                    }
                    project = self.lab.primary_project.get.forks.create(project_data)
                    break
                except gitlab.exceptions.GitlabCreateError as e:
                    if e.response_code == 409 and e.error_message == [
                        "Project namespace name has already been taken",
                        "Name has already been taken",
                    ]:
                        continue
                    raise
            try:
                project = self.gl.projects.get(project.id, lazy=True)
                project.lfs_enabled = False
                project.packages_enabled = False
                project.save()

                project = gitlab_.tools.wait_for_fork(self.gl, project)
                self.lab.configure_student_project(project, self.is_solution)

                r.get = project
                self.repo_add_remote()
            except:  # noqa: E722
                r.delete()
                raise

        r.create = create
        return r

    # TODO: parametrize over submission tag printing.
    def upload_solution(self, path=None, variant=None, force=False):
        """
        If path is None, we look for a solution in 'solution' or 'solution/<id>' relative to the lab sources.
        We include a prefix of the hash of the submission so that reuploads will be reprocessed by the submission system.

        BUG: Solution reprocessing does not work if  solution commits starts with the same prefix.
        """
        if not self.is_solution:
            self.logger.warn("Uploading solution to student project.")
            if not force:
                raise ValueError("not solution project")

        if path is None:
            if variant is not None:
                path = PurePosixPath() / "solution" / variant
            elif self.id in self.lab.solutions.keys() and self.id != "solution":
                path = PurePosixPath() / "solution" / self.id
            else:
                path = PurePosixPath() / "solution"

        tree = util.git.create_tree_from_dir(
            self.lab.repo, self.lab.config.path_source / path
        )
        msg = (
            self.lab.solutions[self.id]
            if self.is_solution
            else "Solution in student project"
        ) + "."
        commit = git.Commit.create_from_tree(
            self.lab.repo, tree, msg, [self.lab.head_problem(variant=variant).commit]
        )
        if self.is_solution:
            # hash = commit.hexsha[:8]
            tag_name = (
                "submission" if variant is None else f"submission-{variant}"
            )
            with util.git.with_tag(self.lab.repo, tag_name, commit) as tag:
                self.lab.repo.remote(self.remote).push(tag, force=True)

    def repo_add_remote(self, ignore_missing=False, **kwargs):
        """
        Add the student repository on Chalmers GitLab as a remote to the local repository.
        This configures the refspecs for fetching in the manner expected by this script.
        This will only be done if the student project on Chalmers GitLab exists.
        If 'ignore_missing' holds, no error is raised if the project is missing.
        """
        try:
            self.lab.repo_add_remote(
                self.remote,
                self.project.get,
                fetch_branches=[(util.git.Namespacing.remote, util.git.wildcard)],
                fetch_tags=[(util.git.Namespacing.remote, util.git.wildcard)],
                prune=True,
                **kwargs,
            )
        except gitlab.GitlabGetError as e:
            if (
                ignore_missing
                and e.response_code == 404
                and e.error_message == "404 Project Not Found"
            ):
                if self.logger:
                    self.logger.debug(
                        f"Not adding remote {self.remote} because project is missing"
                    )
            else:
                raise e

    @functools.cached_property
    def members(self):
        """
        The members of this student project.
        """
        return self.course.student_members(self.project).values()

    def make_members_direct(self):
        """
        Make student members direct developers in the group project.
        Useful in preparation for removing members from the student group.
        """
        for gitlab_user in self.members:
            with gitlab_.tools.exist_ok():
                members_data = {
                    "user_id": gitlab_user.id,
                    "access_level": gitlab.const.DEVELOPER_ACCESS,
                }
                self.project.lazy.members.create(members_data)

    def non_empty(self):
        return bool(self.members)

    # TODO.
    # We could improve caching of members if we had a way to detect updates.
    # But e.g. group hooks monitoring for membership updates are only
    # available in the "Premium tier" version of GitLab, not the open source one.
    def members_clear(self):
        with contextlib.suppress(AttributeError):
            del self.members

    def append_mentions(self, text):
        """
        Append a mentions paragraph to a given Markdown text.
        This will mention all the student members.
        Under standard notification settings, it will trigger notifications
        when the resulting text is posted in an issue or comment.
        """
        return gitlab_.tools.append_mentions(text, self.members)

    @property
    def repo(self):
        return self.lab.repo

    def repo_fetch(self):
        """
        Make sure the local collection repository as up to date with respect to
        the contents of the student repository on GitLab Chalmers.
        """
        self.logger.info(f"Fetching from student repository, remote {self.remote}.")
        self.lab.repo_command_fetch(self.repo, [self.remote])

    def repo_tag(self, request_name, segments=None):
        """
        Construct a tag reference object for the current lab group.
        This only constructs an in-memory object and does not yet interact with the collection repository.
        The tag's name has the group's remote prefixed.

        Arguments:
        * tag_name: Instance of PurePosixPath, str, or gitlab.v4.objects.tags.ProjectTag.
        * segments:
            Optional iterable of path segments to attach to tag_name.
            Strings or instances of PurePosixPath.
            If not given, defaults to 'tag' for the request tag corresponding to the given request_name.

        Returns an instance of git.Tag.
        """
        if segments is None:
            segments = ["tag"]

        if isinstance(request_name, gitlab.v4.objects.tags.ProjectTag):
            request_name = request_name.name

        base = util.git.qualify(self.remote, request_name)
        request_name = base / PurePosixPath(*segments)
        return util.git.normalize_tag(self.repo, request_name)

    def repo_tag_exist(self, request_name, segments=None):
        """
        Test whether a tag with specified name and segments for the current lab group exists in the collection repository.
        Arguments are as for repo_tag.
        Returns a boolean.
        """
        return util.git.tag_exist(GroupProject.repo_tag(self, request_name, segments))

    def repo_tag_mark_repo_updated(self):
        # Mark local collection repository as updated and clear cache of tags.
        self.lab.repo_updated = True
        with contextlib.suppress(AttributeError):
            del self.lab.tags

    def repo_tag_create(self, request_name, segments=None, ref=None, **kwargs):
        """
        Create a tag in the collection repository for the current lab group.

        Arguments:
        * request_name, segments: As for repo_tag.
        * ref:
            The object to tag (for example, an instance of git.Commit).
            If None, we take the commit referenced by the tag with segments replaced by ['tag'].
        * kwargs:
            Additional keyword arguments are forwarded.
            For example:
            - message:
                A string for the message of an annotated tag.
                TODO: Investigate if this can also be a bytes object.
                      This probably comes down to parse_arglist in Modules/posixmodule.c of CPython.
            - force:
                A boolean indicating whether to force creation of the tag.
                If true, any existing reference with this name is overwritten.

        Returns an instance of git.Tag.
        """
        if ref is None:
            ref = GroupProject.repo_tag(self, request_name).commit

        tag = self.repo.create_tag(
            GroupProject.repo_tag(self, request_name, segments).name,
            ref=ref,
            **kwargs,
        )
        self.repo_tag_mark_repo_updated()
        return tag

    def repo_tag_delete(self, request_name, segments=None):
        """
        Delete a tag in the collection repository for the current lab group.
        This can be required under normal circumstances if submission review issues are altered.

        Arguments:
        * request_name, segments: As for repo_tag.
        """
        self.lab.delete_tag(GroupProject.repo_tag(self, request_name, segments).name)
        self.repo_tag_mark_repo_updated()

    def ancestral_tag(self, problem):
        return util.git.normalize_tag(
            self.repo,
            util.git.refs / "ancestral" / self.remote / problem,
        )

    def update_problem(
        self,
        force=False,
        notify_students: str = None,  # pylint: disable=unused-argument
        ensure_ancestral=True,
    ):
        """
        Update problem branch(es) in student repositories to the problem commit in the primary repository.
        No merging is happening.

        Arguments:
        * force: whether to force push,
        * notify_students: unimplemented [TODO, see hotfix_branch],
        * ensure_ancestral:
            If set, ensure there is a local tag ancestral/<group remote>/<problem> with the previous group problem or earlier.
            This can be used for variant detection in merge_problem_into_branch.

            If this complains it cannot find the remote problem head, the fix is to run self.repo_fetch().
            If you are updating the problem for all the groups, it is more efficient to run l.repo_fetch_all().
            TODO:
            Create the ancestral tag already when the group project is created.
            Then no fetch is needed (as long as run with the same local course directory).
        """
        self.logger.info(f"Updating problem branches in {self.project.path}")
        for problem in self.lab.heads_problem:
            if ensure_ancestral:
                tag = self.ancestral_tag(problem)
                if not util.git.tag_exist(tag):
                    self.repo.create_tag(
                        tag.name,
                        ref=util.git.remote_branch(self.remote, problem),
                    )

            branch = util.git.normalize_branch(self.lab.repo, problem).commit
            self.repo.remote(self.remote).push(
                util.git.refspec(
                    problem.hexsha,
                    branch,
                    force=force,
                )
            )

    def detect_variant(self, commit):
        """
        Find out which variant problem a commit derives from.
        The variant will be None for labs that are not multi-variant.
        """
        return util.git.find_unique_ancestor(
            self.repo,
            commit,
            {
                variant: util.git.normalize_branch(self.lab.repo, problem)
                for (variant, problem) in self.lab.variant_problem_names.items()
            },
        )

    def detect_ancestor_problem_for_merge(self, commit, ancestor_override=None):
        """
        Find out which variant problem a commit derives from in the situation of a hotfix.
        There, the problem branches in the student project have already been updated.

        Arguments:
        * ancestors_override:
            Optional map of optional entries from problem branch names to commits.
            For missing entries, we use the ancestral tag ancestral/<group remote>/<problem>.
        """
        if ancestor_override is None:
            ancestor_override = {}

        def get_commit(problem):
            try:
                return ancestor_override[problem]
            except KeyError:
                return self.ancestral_tag(problem).commit

        return util.git.find_unique_ancestor(
            self.repo,
            commit,
            {problem: get_commit(problem) for problem in self.lab.heads_problem},
        )

    # TODO.
    # Consider writing version of hotfix_branch_by_ancestor that goes over all non-protected branches.
    # That should cover the case where students create their own branch, different from main.
    # However, students may also have test or feature branches where they do not want automatic problem merges.

    def merge_problem_into_branch(
        self,
        problem=None,
        problem_old=None,
        target_branch="main",
        merge_files=False,
        fail_on_problem=True,
        notify_students: str | None = None,
    ):
        """
        Hotfix the branch 'target_branch' of the group project.
        This uses a fast-forward if possible, falling back to creating a merge commit.

        To avoid push failure, make sure the local repository is up to date (e.g., self.repo_fetch() or self.lab.repo_fetch_all()).

        Arguments:
        * problem:
            Problem commit to merge into the target branch.
            If not specified, it will be automatically detected using detect_ancestor_problem_for_merge.
        * problem_old:
            Previous problem commit, ancestor of both the problem commit and the target branch.
            If unspecified, computed using the git merge base.
        * target_branch: branch in the student repository to update.
        * merge_files: if True, attempt a 3-way merge to resolve conflicting files.
        * fail_on_problem:
            Fail with an exception if a merge cannot be performed.
            If False, only an error is logged.
        * notify_students:
            Notify student members of the hotfix commit by creating a commit comment with this message.
            The message is appended with mentions of the student members.
            Example: 'We updated your branch <target_branch> with fixes. Remember to pull!'

        Will log a warning if the merge has already been applied.
        """
        self.logger.info(f"Hotfixing {target_branch} in {self.project.path}")

        target_ref = util.git.resolve(
            self.repo,
            util.git.remote_branch(self.remote, target_branch),
        )

        if problem is None:
            try:
                problem = self.detect_ancestor_problem_for_merge(target_ref)
            except util.general.UniquenessError as e:
                ancestors = list(e.iterator)
                self.logger.error(
                    f"Hotfixing: could not determine unique ancestor for"
                    f" {self.name}: detected {ancestors}"
                )
                if not fail_on_problem:
                    return
                raise RuntimeError(
                    "could not detect ancestor problem",
                    ancestors,
                ) from None

        problem = util.git.resolve(
            self.repo,
            util.git.local_branch(problem),
        )

        if problem_old is None:
            problem_old = self.repo.merge_base(
                problem,
                target_ref,
            )  # TOOD: handle errors

        if problem_old == problem:
            self.logger.warning("Hotfixing: hotfix identical to problem.")
            return

        target_ref = util.git.resolve(
            self.repo,
            util.git.remote_branch(self.remote, target_branch),
        )
        if self.repo.is_ancestor(problem, target_ref):
            self.logger.info("Hotfixing: hotfix already applied")
            return

        if self.repo.is_ancestor(target_ref, problem):
            self.logger.info("fast-forwarding...")
            resolved_commit = problem
        else:
            index = git.IndexFile.from_tree(
                self.repo,
                problem_old,
                target_ref,
                problem,
                i="-i",
            )
            if index.unmerged_blobs():
                if not merge_files:
                    self.logger.error(
                        f"Hotfixing: merge conflict for {self.name},"
                        " refusing to resolve."
                    )
                    if not fail_on_problem:
                        return
                    raise RuntimeError("could not perform merge")

                try:
                    util.git.resolve_unmerged_blobs(self.repo, index)
                except git.exc.GitCommandError as e:
                    exit_code = e.args[1]
                    if exit_code == 255:
                        raise
                    if exit_code != 0:
                        self.logger.error(
                            f"Hotfixing: could not resolve merge conflict"
                            f" for {self.name}."
                        )
                        if not fail_on_problem:
                            return
                        raise RuntimeError("could not perform merge") from e

            merge = index.write_tree()
            diff = merge.diff(target_ref)
            for x in diff:
                self.logger.info(x)

            resolved_commit = git.Commit.create_from_tree(
                self.repo,
                merge,
                problem.message,
                parent_commits=[target_ref, problem],
                # author = problem.author,
                # committer = problem.committer,
                # author_date = problem.authored_datetime,
                # commit_date = problem.committed_datetime,
            )

        self.repo.remote(self.remote).push(
            util.git.refspec(
                resolved_commit.hexsha,
                target_branch,
                force=False,
            )
        )
        if notify_students is not None:
            self.project.lazy.commits.get(
                resolved_commit.hexsha,
                lazy=True,
            ).comments.create({"note": self.append_mentions(notify_students)})

    def hook_specs(self, netloc=None) -> Iterable[gitlab_.tools.HookSpec]:
        def events_gen():
            yield "issues"
            yield "tag_push"
            if self.lab.config.grading_via_merge_request:
                yield "merge_requests"

        netloc = self.course.hook_normalize_netloc(netloc=netloc)
        yield gitlab_.tools.HookSpec(
            project=self.project.lazy,
            netloc=netloc,
            events=tuple(events_gen()),
            secret_token=self.course.config.webhook.secret_token,
        )

    @functools.cached_property
    def grading_via_merge_request(self):
        if self.lab.config.multi_variant is None:
            return grading_via_merge_request.GradingViaMergeRequest(
                self.lab.grading_via_merge_request_setup_data,
                self,
            )

        return {
            variant: grading_via_merge_request.GradingViaMergeRequest(
                self.lab.grading_via_merge_request_setup_data[variant],
                self,
            )
            for variant in self.lab.config.branch_problem.keys()
        }

    def tags_from_gitlab(self):
        self.logger.debug(f"Parsing request tags in {self.name} from Chalmers GitLab.")
        x = [
            (tag.name, tag)
            for tag in gitlab_.tools.get_tags_sorted_by_date(self.project.lazy)
        ]
        return sorted(x, key=lambda x: (x[1].date, x[0]))

    def tags_from_repo(self):
        self.logger.debug(
            f"Parsing request tags in {self.name} from local collection repository."
        )
        xs = (
            (str(key), (tag, util.git.tag_commit(tag)))
            for (key, tag) in self.lab.remote_tags[self.id].items()
        )
        return sorted(xs, key=lambda x: (util.git.commit_date(x[1][1]), x[0]))

    def parse_request_tags(self, from_gitlab=True):
        """
        Parse request tags for this project and store the result in self.handler_data.
        The boolean parameter from_gitlab determines if:
        * (True) tags read from Chalmers GitLab (a HTTP call)
        * (False) tags are read from the local collection repository.

        This method needs to be called before requests_and_responses
        in each handler data instance can be accessed.
        """

        # To be a valid request, the tag name must consist of a single path segment.
        # That is, it must be non-empty and cannot contain the character '/'.
        def check_single_path_segment(item):
            (tag_name, _tag_data) = item
            tag_parts = PurePosixPath(tag_name).parts
            try:
                (_,) = tag_parts
            except ValueError:
                # Take tag out of the parsing stream.
                self.logger.warning(
                    f"Ignoring tag {shlex.quote(tag_name)}"
                    f" in student group {self.name} not composed of"
                    " exactly one path part (with respect to separator '/')."
                )
                return ()

            # Keep tag for further parsing
            return None

        def f():
            yield (check_single_path_segment, None, None)
            for handler_data in self.handler_data.values():
                yield handler_data.request_tag_parser_data()

        util.item_parser.parse_all_items(
            util.item_parser.Config(
                location_name=self.name,
                item_name="request tag",
                item_formatter=lambda x: gitlab_.tools.format_tag_metadata(
                    self.project.lazy,
                    x[0],
                ),
                logger=self.logger,
            ),
            f(),
            (self.tags_from_gitlab if from_gitlab else self.tags_from_repo)(),
        )

        # Clear requests and responses cache.
        for handler_data in self.handler_data.values():
            with contextlib.suppress(AttributeError):
                del handler_data.requests_and_responses

    def official_issues(self):
        """
        Generator function retrieving the official issues.
        An official issue is one created by a grader.
        Only official issues can be response issues.
        """
        self.logger.debug(f"Retrieving response issues in {self.name}.")
        for issue in gitlab_.tools.list_all(
            self.project.lazy.issues,
            order_by="created_at",
            sort="desc",
        ):
            if any(
                issue.author["id"] in ids
                for ids in [self.course.lab_system_users, self.course.graders]
            ):
                yield issue

    @property
    def submission_handler_data(self):
        """The instance of HandlerData for the submission handler."""
        return self.handler_data[self.lab.config.submission_handler_key]

    @property
    def reviews(self):
        """
        The review response dictionary of the submission handler.
        This is a dictionary mapping request names to response issue title parsings.
        Is None before parse_response_issues is called.

        Only valid if review issues are configured.
        """
        return self.submission_handler_data.responses.get(
            self.lab.submission_handler.review_response_key
        )

    @property
    def reviews_data(self):
        """
        Modified version of reviews.
        The returned dictionary has as values only the issue title parsing.
        Is None before parse_response_issues is called.
        """

        def action(x):
            (_, r) = x
            return r

        return util.general.maybe(functools.partial(util.general.map_values, action))(
            self.reviews
        )

    def parse_response_issues(self, on_duplicate=True, delete_duplicates=False):
        """
        Parse response issues for this project on Chalmers GitLab
        on store the result in self.handler_data.
        Cost: one HTTP call.

        This method needs to be called before requests_and_responses
        in each contained handler data instance can be accessed.

        Arguments:
        * on_duplicate:
            - None: Raise an exception.
            - True: Log a warning and keep the first (newer) item.
            - False: Log a warning and keep the second (older) item.
        * delete_duplicates: if true, delete duplicate issues.

        Returns a boolean indicating if there is
        a change in the review responses, if configured.
        This includes the full issue title parsing, in particular the outcome.
        """
        if self.lab.have_reviews:
            data_previous = self.reviews_data

        def closed_issue_parser(issue):
            return () if issue.state == "closed" else None

        def parser_data():
            for handler_data in self.handler_data.values():
                yield from handler_data.response_issue_parser_data()

            # Disregard unrecognized issues that are closed.
            yield (closed_issue_parser, "disregard closed issues", None)

        if delete_duplicates:

            def delete_duplicates_fun(item, _key, _value):
                item.delete()

        else:
            delete_duplicates_fun = None

        util.item_parser.parse_all_items(
            util.item_parser.Config(
                location_name=self.name,
                item_name="response issue",
                item_formatter=gitlab_.tools.format_issue_metadata,
                logger=self.logger,
                on_duplicate=on_duplicate,
                delete_duplicates=delete_duplicates_fun,
            ),
            parser_data(),
            self.official_issues(),
        )

        # Clear requests and responses cache.
        for handler_data in self.handler_data.values():
            with contextlib.suppress(AttributeError):
                del handler_data.requests_and_responses

        if self.lab.have_reviews:
            data_current = self.reviews_data
            self.logger.debug(f"current reviews: {data_current}")
            if data_previous is None:
                self.logger.debug("previous reviews not fetched")
                return True
            self.logger.debug(f"previous reviews: {data_previous}")
            return data_current != data_previous
        return False

    def parse_grading_merge_request_responses(self):
        if self.lab.config.multi_variant is None:
            return self.grading_via_merge_request.update_outcomes()

        def f():
            for m in self.grading_via_merge_request.values():
                yield m.update_outcomes()

        return any(list(f()))

    def process_requests(self):
        """
        Process requests.
        This skips requests already marked as handled in the local collection repository.

        Returns a dictionary mapping handler keys to sets of newly handed request names.
        """
        return {
            handler_key: handler_data.process_requests()
            for (handler_key, handler_data) in self.handler_data.items()
        }

    def submissions(self, deadline=None):
        """
        Counts only the accepted submission attempts.
        If deadline is given, we restrict to prior submissions.
        Here, the date refers to the date of the submission commit.
        Returns an iterable of instances of RequestAndResponses ordered by the date.
        """
        for (
            request_and_responses
        ) in self.submission_handler_data.requests_and_responses.values():
            if request_and_responses.accepted:
                if deadline is None or request_and_responses.date <= deadline:
                    yield request_and_responses

    def submissions_with_outcome(self, deadline=None):
        """
        Restricts the output of self.submissions to instances of SubmissionAndRequests with an outcome.
        This could be a submission-handler-provided outcome or a review by a grader.
        Returns an iterable of instances of RequestAndResponses ordered by the date.
        """
        for submission in self.submissions(deadline=deadline):
            if submission.outcome is not None:
                yield submission

    def submissions_relevant(self, deadline=None):
        """
        Restrict the output of self.submissions to all relevant submissions.
        A submission is *relevant* if it has an outcome or is the last submission and needs a review.
        Returns an iterable of instances of RequestAndResponses ordered by the date.
        """
        submissions = list(self.submissions(deadline=deadline))
        for i, submission in enumerate(submissions):
            if i + 1 == len(submissions) or submission.outcome is not None:
                yield submission

    def submission_current(self, deadline=None):
        """
        With respect to the output of self.submissions, return the last submission
        if it needs a review (i.e. does not yet have an outcome), otherwise return None.
        Returns an instances of RequestAndResponses or None.
        """
        submissions = list(self.submissions(deadline=deadline))
        if submissions:
            submission_last = submissions[-1]
            if submission_last.outcome_acc(accumulative=True) is None:
                return submission_last

        return None

    def parse_hook_event_tag(self, hook_event, _strict):
        """
        For a tag push event, we always generate a queue event.
        TODO (optimization): Check that the tag name matches a request matcher.
        """
        self.logger.debug("Received a tag push event.")
        ref = hook_event.get("ref")
        self.logger.debug(f"Reference: {ref}.")
        yield (
            events.GroupProjectTagEvent(),
            lambda: self.lab.refresh_group(self),
        )

    def parse_hook_event_issue(self, hook_event, _strict):
        """
        We only generate a group project event if both:
        - the (current or previous) author is a grader,
        - the title has changed.

        Note: uses self.course.graders.
        """
        self.logger.debug("Received an issue event.")
        object_attributes = hook_event.get("object_attributes")
        title = None if object_attributes is None else object_attributes["title"]
        self.logger.debug(f"Issue title: {title}.")
        changes = hook_event.get("changes")

        def author_id():
            if object_attributes is not None:
                return object_attributes["author_id"]

            author_id_changes = changes["author_id"]
            for version in ["current", "previous"]:
                author_id = author_id_changes[version]
                if author_id is not None:
                    return author_id

            raise ValueError("author id missing")

        author_id = author_id()
        author_is_grader = author_id in self.course.grader_ids
        self.logger.debug(
            f"Detected issue author id {author_id},"
            f" member of graders: {author_is_grader}"
        )

        def title_change():
            if changes is None:
                return False

            title_changes = changes.get("title")
            if title_changes is None:
                return False

            return title_changes["current"] != title_changes["previous"]

        title_change_ = title_change()
        self.logger.debug(f"Detected title change: {title_change_}")

        # TODO.
        # We could go further and only queue an event
        # if the old or new title parses as a review issue.
        # Then GroupProjectIssueEvent should be renamed GroupProjectReviewEvent.
        # We don't do much work in handling GroupProjectIssueEvent for non-review issues anyway.
        # And it might be beneficial to be up-to-date also with non-review response issues.
        # So keeping this as is for now.
        if author_is_grader and title_change_:
            yield (
                events.GroupProjectWebhookResponseEvent(
                    events.GroupProjectIssueEvent()
                ),
                lambda: self.lab.refresh_group(self, refresh_issue_responses=True),
            )

    def parse_hook_event_grading_merge_request(self, hook_event, _strict):
        self.logger.debug("Received a grading merge request event.")
        changes = hook_event.get("changes")
        if changes and "labels" in changes:
            # self.logger.debug(f'Detected label change from {} to {}')
            self.logger.debug("Detected label change")
            yield (
                events.GroupProjectWebhookResponseEvent(
                    events.GroupProjectGradingMergeRequestEvent()
                ),
                lambda: self.lab.refresh_group(
                    self,
                    refresh_grading_merge_request=True,
                ),
            )

    def parse_hook_event(self, hook_event, strict=False):
        """
        Arguments:
        * hook_event:
            Dictionary (decoded JSON).
            Event received from a webhook in this group project.
        * strict:
            Whether to fail on unknown events.

        Returns an iterator of pairs of:
        - an instance of events.GroupProjectEvent,
        - a callback function to handle the event.
        These are the group project events triggered by the webhook event.
        """
        project_name = hook_event["project"]["name"]
        event_type = gitlab_.tools.event_type(hook_event)

        def handlers():
            yield ((self.project.name, "tag_push"), self.parse_hook_event_tag)
            yield ((self.project.name, "issue"), self.parse_hook_event_issue)
            if self.lab.config.grading_via_merge_request:
                yield (
                    (self.project.name, "merge_request"),
                    self.parse_hook_event_grading_merge_request,
                )

        handler = dict(handlers()).get((project_name, event_type))

        if handler is not None:
            yield from handler(hook_event, strict)
        else:
            if strict:
                raise ValueError(f"Unknown event {event_type}")

            self.logger.warning(
                f"Received unknown webhook event of type {event_type}"
                f" for project {hook_event["project"]["path_with_namespace"]}"
                f" with name {project_name}."
            )
            self.logger.debug(f"Webhook event:\n{hook_event}")

    def lab_event(self, group_project_event):
        return events.LabEventInGroupProject(
            group_id=self.id,
            group_project_event=group_project_event,
        )

    def get_score(self, scoring=None, strict=True):
        """
        Get the grading score for this group.
        Scores are user-defined.

        Arguments:
        * scoring:
            A function taking a list of submission outcomes and returning a score.
            Defaults to None for no submissions and the maximum function otherwise.
        * strict:
            Refuse to compute score if there is an ungraded submission.
        """
        if strict and self.submission_current() is not None:
            raise ValueError(f"ungraded submission in {self.lab.name} for {self.name}")

        def scoring_default(s):
            return max(s) if s else None

        if scoring is None:
            scoring = scoring_default
        return scoring(
            [submission.outcome for submission in self.submissions_with_outcome()]
        )
