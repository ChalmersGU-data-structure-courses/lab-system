import contextlib
import functools
import general
import json
import logging
from pathlib import PurePosixPath
import shlex

import git
import gitlab
import gitlab.v4.objects

import events
import instance_cache
import item_parser
import git_tools
import gitlab_tools
import print_parse
import webhook_listener


class RequestAndResponses:
    '''
    This class abstracts over a single request tag on Chalmers GitLab.
    It also collects the response issues posted by the lab system or graders
    in response to this request tag (as identified by their title).

    To process the request, an instance of this class is passed
    as argument to handle_request method of the corresponding request handler.
    That method may take a variety of actions such as creating tags (and tagged commits)
    in the local grading repository (which will afterwards be pushed to the grading repository
    on GitLab Chalmers) or posting issues in the student project on GitLab Chalmers.

    Each instances of this class is managed by an instance of HandlerData.
    Instances are rather transient.
    They are reconstructed every time request tags or response issues are refreshed.

    There are special instances of this class for the official problem and solution.
    In that case, the handler_data parameter is None and tag_data is a pair of
    the corresponding head and commit in the grading repository.
    '''
    def __init__(self, lab, handler_data, request_name, tag_data):
        self.lab = lab
        self.handler_data = handler_data

        self.request_name = request_name
        if isinstance(tag_data, gitlab.v4.objects.ProjectTag):
            self.gitlab_tag = tag_data
        else:
            self.gitlab_tag = None
            (self.repo_remote_tag, self.repo_remote_commit) = tag_data
        self.responses = dict()

    @property
    def course(self):
        return self.lab.course

    @property
    def group(self):
        return None if self.handler_data is None else self.handler_data.group

    @property
    def _group(self):
        return self.lab if self.group is None else self.group

    @property
    def logger(self):
        return self.lab.logger if self.handler_data is None else self.handler_data.logger

    @functools.cached_property
    def repo_remote_tag(self):
        return git.Reference(self.lab.repo, str(git_tools.remote_tag(self.request_name)))

    @functools.cached_property
    def repo_remote_commit(self):
        return self.repo_remote_tag.commit

    @functools.cached_property
    def date(self):
        return git_tools.commit_date(self.repo_remote_commit)

    def repo_tag(self, segments = ['tag']):
        '''Forwards to self.group.repo_tag.'''
        return GroupProject.repo_tag(self._group, self.request_name, segments)

    def repo_tag_exist(self, segments):
        '''Forwards to self.group.repo_tag_exist.'''
        return GroupProject.repo_tag_exist(self._group, self.request_name, segments)

    def repo_tag_create(self, segments = ['tag'], ref = None, **kwargs):
        '''Forwards to self.group.repo_tag_create.'''
        return GroupProject.repo_tag_create(self._group, self.request_name, segments, ref, **kwargs)

    def repo_tag_delete(self, segments = ['tag']):
        '''Forwards to self.group.repo_tag_delete.'''
        return GroupProject.repo_tag_delete(self._group, self.request_name, segments)

    def repo_tag_create_json(self, segments, ref = None, data = None, **kwargs):
        '''
        Create a tag with optional JSON-encoded data as message.
        Signature is as for repo_tag_create,
        except the message keyword argument must not be used.
        Returns the created tag.
        '''
        return self.repo_tag_create(
            segments,
            ref,
            message = None if data is None else json.dumps(data, indent = 2),
            **kwargs,
        )

    def repo_tag_read_json(self, segments):
        '''Read the JSON-encoded data in the message of a tag.'''
        return json.loads(git_tools.tag_message(self.repo_tag(segments)))

    def repo_tag_read_text_file(self, segments, path):
        '''
        Read a text file given by 'path' (PurePosixPath)
        in the commit corresponding to 'segments'.
        '''
        return git_tools.read_text_file_from_tree(self.repo_tag(segments).commit.tree, path)

    @contextlib.contextmanager
    def checkout_manager(self, segments = ['tag']):
        with git_tools.checkout_manager(self.lab.repo, self.repo_tag(segments)) as src:
            yield src

    def repo_report_create(self, segments, dir, commit_message = '', **kwargs):
        '''
        Commit the directory 'dir' as a descendant of self.repo_remote_commit
        and tag it as <group full id>/<request name>/<segments>.
        Further arguments are passed to self.repo_tag_create_json.
        Returns the created tag.

        Symlinks are currently handled transparently.
        We may wish to allow for committing symlinks in the future.
        '''
        tree = git_tools.create_tree_from_dir(self.lab.repo, dir)
        commit = git.Commit.create_from_tree(
            repo = self.lab.repo,
            tree = tree,
            message = commit_message,
            parent_commits = [],
            author_date = self.repo_remote_commit.authored_datetime,
            commit_date = self.repo_remote_commit.committed_datetime,
        )
        return self.repo_tag_create_json(segments, ref = commit, **kwargs)

    # Tag path segment suffix used for marking requests as handled.
    segment_handled = ['handled']

    def get_handled(self, read_data = False):
        '''
        Check the local grading repository whether this request has been handled.
        This checks for the existence of a tag <group full id>/<request name>/handled.
        If read_data is set, we read JSON-encoded data from the tag message.
        '''
        if not read_data:
            return self.repo_tag_exist(RequestAndResponses.segment_handled)
        return self.repo_tag_read_json(RequestAndResponses.segment_handled)

    @functools.cached_property
    def handled(self):
        return self.get_handled()

    @functools.cached_property
    def handled_result(self):
        return self.get_handled(read_data = True)

    def set_handled(self, data = None, **kwargs):
        '''
        Mark this request in the local grading repository as handled.
        See handled.
        If the optional argument data is given, it is stored in JSON-encoded format in the tag message.
        Further keyword arguments are passed to repo_tag_create.
        '''
        self.repo_tag_create_json(RequestAndResponses.segment_handled, data = data)
        self.handled = True
        if data is not None:
            self.handled_result = data

    @functools.cached_property
    def accepted(self):
        '''
        Returns a boolean indicating if the submission request has been accepted.
        This means that it counts as valid submission attempt, not that the submission has passed.
        See the documentation of submission handlers.
        Only valid for submission requests.
        '''
        return self.handled_result['accepted']

    @functools.cached_property
    def review_needed(self):
        '''
        Returns a boolean indicating if the submission handler has requested a review.
        See the documentation of submission handlers.
        Only valid for submission requests.
        '''
        return self.handled_result['review_needed']

    @functools.cached_property
    def review(self):
        '''
        Get the review response, or None if there is none.
        Only valid for accepted submission requests.

        Returns a pair (issue, title_data) on success where:
        - issue is the review issue on Chalmers GitLab,
        - title_data is the parsing produced by the response issue printer-parser.

        Can be used as a boolean to test for the existence of a review.
        '''
        # Review issues must be configured to proceed.
        response_key = self.handler_data.handler.review_response_key
        if response_key is None:
            return None

        return self.responses.get(response_key)

    @functools.cached_property
    def outcome_response_key(self):
        '''
        Get the outcome response key, or None if there is no outcome.
        Only valid for accepted submission requests.
        First checks for a review issue and then the result of the submission handler.
        '''
        if self.review is not None:
            return self.handler_data.handler.review_response_key

        return self.handled_result.get('outcome_response_key')

    @functools.cached_property
    def outcome_with_issue(self):
        '''
        Get the outcome and the associated response issue, or None if there is no outcome.
        In the former case, returns a pair (outcome, outcome_issue) where:
        - outcome is the submission outcome,
        - issue is an instance of gitlab.v4.objects.ProjectIssue.
        Only valid for accepted submission requests.
        '''
        if self.outcome_response_key is None:
            return None

        (issue, title_data) = self.responses[self.outcome_response_key]
        return (title_data['outcome'], issue)

    @functools.cached_property
    def outcome(self):
        '''
        The outcome part of 'outcome_with_issue'.
        None if the latter is None.
        '''
        if self.outcome_with_issue is None:
            return None

        (outcome, outcome_issue) = self.outcome_with_issue
        return outcome

    @functools.cached_property
    def outcome_issue(self):
        '''
        The outcome issue part of 'outcome_with_issue'.
        None if the latter is None.
        '''
        if self.outcome_with_issue is None:
            return None

        (outcome, outcome_issue) = self.outcome_with_issue
        return outcome_issue

    @functools.cached_property
    def informal_grader_name(self):
        '''
        Get the informal name the reviewer, or 'Lab system' if there is none.
        Only valid for submission requests with an outcome.
        '''
        if self.review is None:
            return 'Lab system'

        gitlab_username = self.outcome_issue.author['username']
        canvas_user = self.course.canvas_user_by_gitlab_username[gitlab_username]
        return self.course.canvas_user_informal_name(canvas_user)

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
    #     Check the local grading repository whether this request has been handled.
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

    def _repo_tag_after_segments(self, prev_name, segments = []):
        return [*segments, 'after', prev_name]

    @instance_cache.instance_cache
    def repo_tag_after(self, prev_name, segments = []):
        '''
        Returns an instance of git.TagReference for the tag with name
            <full group id>/<request name>/after/<prev_name>
        in the local grading repository.

        This points to a descendant commit of self.repo_remote_commit, identical in content,
        that is additionally a descendant of whatever commit prev_name refers to.
        '''
        return self._repo_tag_after_segments(prev_name, segments)

    def repo_tag_after_create(self, prev_name, prev_ref, segments = []):
        '''
        Given a reference prev_ref in the grading repository, create a tag
            <full group id>/<request name>/<segments>/after/<prev_name>
        for a commit that is a descendant of both self.repo_tag([*segments, 'tag']) and prev_ref.

        If the repository tag is a descendant of prev_commit, the commit is self.repo_remote_commit.
        Otherwise, it is created as a one-sided merge.

        Returns an instance of git.TagReference for the created tag.
        '''
        prev_commit = git_tools.resolve(self.lab.repo, prev_ref)
        commit = self.repo_tag([*segments, 'tag']).commit if segments else self.repo_remote_commit
        if not self.lab.repo.is_ancestor(prev_commit, commit):
            commit = git_tools.onesided_merge(self.lab.repo, commit, prev_commit)
        return self.repo_tag_create(self._repo_tag_after_segments(prev_name, segments), commit, force = True)

    def post_response_issue(self, response_key, title_data = dict(), description = str()):
        # Only allow posting if there is not already a response issue of the same type.
        if response_key in self.responses:
            ValueError(
                f'Response issue for {response_key} already exists '
                'for request {self.request_name} in {self.name} in {self.lab.name}'
            )

        # Make sure title_data is a dictionary and fill in request name.
        title_data = dict(title_data)
        title_data['tag'] = self.request_name

        # Post the issue.
        title = self.handler_data.handler.response_titles[response_key].print(title_data)
        self.logger.debug(general.join_lines([
            'Posting response issue:',
            f'* title: {title}',
            '* description:',
            *description.splitlines()
        ]))
        issue = self.group.project.lazy.issues.create({
            'title': title,
            'description': self.group.append_mentions(description),
        })

        # Make sure the local response issue caches are up to date.
        issue_data = (issue, title_data)
        self.responses[response_key] = issue_data
        self.handler_data.responses[response_key][self.request_name] = issue_data

    def process_request(self):
        '''
        Process request.
        This only proceeds if the request is not already
        marked handled in the local grading repository.

        Returns a boolean indicating if the request was not handled before.
        '''
        # Skip processing if we already handled this request.
        if self.get_handled():
            return False

        where = '' if self.group is None else f' in {self.group.name}'
        self.logger.info(f'Processing request {self.request_name}{where}.')

        # Create tag <full group id>/<request name>/tag copying the request tag.
        self.repo_tag_create(
            ref = self.repo_remote_commit,
            message = git_tools.tag_message(self.repo_remote_tag),
            force = True,
        )

        if self.group:
            # Call handler with this object as argment.
            self.logger.debug(
                f'Handling request {self.request_name} {where} '
                f'using handler {self.handler_data.handler_key}'
            )
            result = self.handler_data.handler.handle_request(self)
        else:  # Fake submission (official problem or solution).
            result = self.lab.submission_handler.handle_request(self)

        if result is not None:
            self.logger.debug(general.join_lines(['Handler result:', str(result)]))

        # Create tag <full-group-id>/<request_name>/handled
        # and store handler's result JSON-encoded as its message.
        self.set_handled(result)

        # Clear cache of tags in the local grading repository.
        with contextlib.suppress(AttributeError):
            del self.lab.tags

        return True

class HandlerData:
    '''
    This class abstracts over a request handler handling a single type of request
    students may make in their group project for a particular lab on Chalmers GitLab.
    It also collects request tags and response issues associated with this handler
    before they are combined into instances of RequestAndResponses,
    which are also collected by this class.

    Each instance of this class is managed by an instance of GroupProject.
    '''
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
            response_key: None
            for response_key in self.handler.response_titles.keys()
        }

        # Is this the submission handler?
        self.is_submission_handler = handler_key == self.lab.config.submission_handler_key

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
        '''
        Prepare parser_data entries for a request tag parsing call to item_parser.parse_all_items.
        Initializes the requests map.
        Returns an entry for use in the parser_data iterable.
        '''
        def parser(item):
            (tag_name, tag_data) = item
            if self.handler.request_matcher.parse(tag_name) is None:
                return None
            return (tag_name, tag_data)

        u = dict()
        self.requests = u
        return (parser, self.handler_key, u)

    def response_issue_parser_data(self):
        '''
        Prepare parser_data entries for a response issue parsing call to item_parser.parse_all_items.
        Initializes the responses map.
        Returns iterable of parser_data entries.
        '''
        for (response_key, response_title) in self.handler.response_titles.items():
            def parser(issue):
                title = issue.title
                parse = response_title.parse.__call__
                try:
                    r = parse(title)
                except Exception:
                    return None
                return (r['tag'], (issue, r))

            u = dict()
            self.responses[response_key] = u
            yield (parser, f'{self.handler_key} {response_key}', u)

    @functools.cached_property
    def requests_and_responses(self):
        '''
        A dictionary pairing request tags with response issues.
        The keys are request names.
        Each value is an instance of RequestAndResponses.
        Before this cached property can be constructed, calls
        to parse_request_tags and parse_response_issues need to complete.
        '''
        result = dict()
        for (request_name, tag_data) in self.requests.items():
            result[request_name] = RequestAndResponses(self.lab, self, request_name, tag_data)

        for (response_key, u) in self.responses.items():
            for (request_name, issue_data) in u.items():
                request_and_responses = result.get(request_name)
                if request_and_responses is None:
                    self.logger.warning(gitlab_tools.format_issue_metadata(
                        issue_data[0],
                        f'Response issue in {self.group.name} '
                        'with no matching request tag (ignoring):'
                    ))
                else:
                    request_and_responses.responses[response_key] = issue_data
        return result

    def process_requests(self):
        '''
        Process requests.
        This method assumes that requests_and_responses has been set up.
        It skips requests already marked as handled in the local grading repository.

        Returns the set of request names that were newly handled.
        '''
        def f():
            for request_and_responses in self.requests_and_responses.values():
                if request_and_responses.process_request():
                    yield request_and_responses.request_name
        return set(f())

class GroupProject:
    '''
    This class abstracts over a lab project of a lab group on Chalmers GitLab.
    It collects instances of HandlerData.
    Each instances of this class is managed by an instance of lab.Lab.
    '''
    def __init__(self, lab, id, logger = logging.getLogger(__name__)):
        self.lab = lab
        self.id = id
        self.logger = logger

        self.name = self.course.config.group.name.print(id)
        self.remote = self.course.config.group.full_id.print(id)

        self.handler_data = {
            handler_key: HandlerData(self, handler_key)
            for handler_key in self.lab.config.request_handlers.keys()
        }

    @property
    def course(self):
        return self.lab.course

    @functools.cached_property
    def gl(self):
        return self.lab.gl

    @functools.cached_property
    def project(self):
        '''
        A lab project for a student group.
        On creation, the repository is initialized with the problem branch of the local grading repository.
        That one needs to be initialized and have the problem branch.
        '''
        r = gitlab_tools.CachedProject(
            gl = self.gl,
            path = self.course.group(self.id).path / self.course.config.lab.full_id.print(self.lab.id),
            name = self.lab.name_full,
            logger = self.logger,
        )

        def create():
            project = gitlab_tools.CachedProject.create(r, self.course.group(self.id).get)
            try:
                self.repo.git.push(
                    project.ssh_url_to_repo,
                    git_tools.refspec(
                        git_tools.local_branch(self.course.config.branch.problem),
                        self.course.config.branch.master,
                        force = True,
                    )
                )
                self.lab.configure_student_project(project)
                self.repo_add_remote()
            except:  # noqa: E722
                r.delete()
                raise
        r.create = create

        return r

    def repo_add_remote(self, ignore_missing = False):
        '''
        Add the student repository on Chalmers GitLab as a remote to the local repository.
        This configures the refspecs for fetching in the manner expected by this script.
        This will only be done if the student project on Chalmers GitLab exists.
        If 'ignore_missing' holds, no error is raised if the project is missing.
        '''
        try:
            self.lab.repo_add_remote(
                self.remote,
                self.project.get,
                fetch_branches = [(git_tools.Namespacing.remote, git_tools.wildcard)],
                fetch_tags = [(git_tools.Namespacing.remote, git_tools.wildcard)],
                prune = True,
            )
        except gitlab.GitlabGetError as e:
            if ignore_missing and e.response_code == 404 and e.error_message == '404 Project Not Found':
                if self.logger:
                    self.logger.debug(f'Not adding remote {self.remote} because project is missing')
            else:
                raise e

    @functools.cached_property
    def members(self):
        '''
        The members of a student group project are taken from these sources:
        * members of the containing student group,
        * members of the project iself (for students that have been added because they changed groups).
        In both cases, we restrict to users with developer or maintainer rights.
        '''
        return general.dict_union(map(self.course.student_members, [
            self.course.group(self.id),
            self.project,
        ])).values()

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
        '''
        Append a mentions paragraph to a given Markdown text.
        This will mention all the student members.
        Under standard notification settings, it will trigger notifications
        when the resulting text is posted in an issue or comment.
        '''
        return gitlab_tools.append_mentions(text, self.members)

    @property
    def repo(self):
        return self.lab.repo

    def repo_fetch(self):
        '''
        Make sure the local grading repository as up to date with respect to
        the contents of the student repository on GitLab Chalmers.
        '''
        self.logger.info(f'Fetching from student repository, remote {self.remote}.')
        self.repo.remote(self.remote).fetch('--update-head-ok')
        self.lab.repo_updated = True
        with contextlib.suppress(AttributeError):
            del self.lab.remote_tags

    def repo_tag(self, request_name, segments = ['tag']):
        '''
        Construct a tag reference object for the current lab group.
        This only constructs an in-memory object and does not yet interact with the grading repository.
        The tag's name with habe the group's remote prefixed.

        HACK:
        This method and the following related ones may
        also be called with self an instance of lab.Lab.
        In that case, the remote is omitted from the tag name.
        This is used for the pseudo-instances of SubmissionAndResponse
        for the official problem and solution.

        Arguments:
        * tag_name: Instance of PurePosixPath, str, or gitlab.v4.objects.tags.ProjectTag.
        * segments:
            Iterable of path segments to attach to tag_name.
            Strings or instances of PurePosixPath.
            If not given, defaults to 'tag' for the request tag
            corresponding to the given request_name.

        Returns an instance of git.Tag.
        '''
        if isinstance(request_name, gitlab.v4.objects.tags.ProjectTag):
            request_name = request_name.name

        base = request_name
        if isinstance(self, GroupProject):
            base = git_tools.qualify(self.remote, request_name)
        request_name = base / PurePosixPath(*segments)
        return git_tools.normalize_tag(self.repo, request_name)

    def repo_tag_exist(self, request_name, segments = ['tag']):
        '''
        Test whether a tag with specified name and segments for the current lab group exists in the grading repository.
        Arguments are as for repo_tag.
        Returns a boolean.
        '''
        return git_tools.tag_exist(GroupProject.repo_tag(self, request_name, segments))

    def repo_tag_mark_repo_updated(self):
        # Mark local grading repository as updated and clear cache of tags.
        lab = self.lab if isinstance(self, GroupProject) else self
        lab.repo_updated = True
        with contextlib.suppress(AttributeError):
            del lab.tags

    def repo_tag_create(self, request_name, segments = ['tag'], ref = None, **kwargs):
        '''
        Create a tag in the grading repository for the current lab group.

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
        '''
        if ref is None:
            ref = GroupProject.repo_tag(self, request_name).commit

        tag = self.repo.create_tag(
            GroupProject.repo_tag(self, request_name, segments).name,
            ref = ref,
            **kwargs,
        )
        GroupProject.repo_tag_mark_repo_updated(self)
        return tag

    def repo_tag_delete(self, request_name, segments):
        '''
        Delete a tag in the grading repository for the current lab group.
        This can be required under normal circumstances if submission review issues are altered.

        Arguments:
        * request_name, segments: As for repo_tag.
        '''
        self.lab.delete_tag(GroupProject.repo_tag(self, request_name, segments).name)
        GroupProject.repo_tag_mark_repo_updated(self)

    def hotfix_group(self, branch_hotfix, branch_group):
        '''
        Attempt to hotfix the branch 'branch_group' of the group project.
        The hotfix branch 'branch_hotfix' in the local grading repository is a descendant of the problem branch.
        The metadata of the applied commit is taken from the commit pointed to by 'branch_hotfix'.
        Will log a warning if the merge cannot be performed.
        '''
        self.logger.info(f'Hotfixing {branch_group} in f{self.project.path}')

        # Make sure our local mirror of the student branches is as up to date as possible.
        self.repo_fetch()

        problem = self.lab.head_problem
        hotfix = git_tools.normalize_branch(self.repo, branch_hotfix)
        if problem == hotfix:
            self.logger.warn('Hotfixing: hotfix identical to problem.')
            return

        master = git_tools.remote_branch(self.remote, branch_group)
        index = git.IndexFile.from_tree(self.repo, problem, master, hotfix, i = '-i')
        merge = index.write_tree()
        diff = merge.diff(master)
        if not diff:
            self.logger.warn('Hotfixing: hotfix already applied')
            return
        for x in diff:
            self.logger.info(x)

        commit = git.Commit.create_from_tree(
            self.repo,
            merge,
            hotfix.message,
            parent_commits = [git_tools.resolve(self.repo, master)],
            author = hotfix.author,
            committer = hotfix.committer,
            author_date = hotfix.authored_datetime,
            commit_date = hotfix.committed_datetime,
        )

        return self.repo.remote(self.remote).push(git_tools.refspec(
            commit.hexsha,
            self.course.config.branch.master,
            force = False,
        ))

    def _hook_url(self, netloc = None):
        '''
        The URL to register for the given net location.
        If 'netloc' is None, uses the configured default (see Course.hook_normalize_netloc).
        '''
        netloc = self.course.hook_normalize_netloc(netloc = netloc)
        return print_parse.url.print(print_parse.URL_HTTPS(netloc))

    def hooks_get(self):
        '''
        Get the currently installed webhooks in this group projects.
        Returns a dictionary from net locations to lists of hooks.
        '''
        def f():
            for hook in gitlab_tools.list_all(self.project.lazy.hooks):
                url = print_parse.url.parse(hook.url)
                yield (url.netloc, hook)
        return general.multidict(f())

    @staticmethod
    def check_hook_configuration(hook):
        '''
        Check that the given hook is set up like expected.
        That means:
        * It should have notifications for the needed events enabled.
        * It should have SSL certificate verification disabled.

        Problems are raised as instances of ValueError.
        '''
        if not hook.tag_push_events:
            raise ValueError('tag push events are not configured')
        if not hook.issues_events:
            raise ValueError('issue events are not configured')
        if hook.enable_ssl_verification:
            raise ValueError('hook does not have SSL certificate verification disabled')

    def check_hooks(self, hooks = None, netloc = None):
        '''
        Check that the given hooks dictionary (as returned
        by hooks_get) corresponds to a correct configuration.
        Here, correct means: as created by a single call to hook_create.

        If 'hooks' is None, get the hooks from the project.
        If 'netloc' is None, uses the configured default (see Course.hook_normalize_netloc).

        Raises ValueError if the hooks are not correct.
        '''
        if hooks is None:
            hooks = self.hooks_get()
        netloc = self.course.hook_normalize_netloc(netloc = netloc)

        for (netloc_key, hook_list) in hooks.items():
            if not netloc_key == netloc:
                raise ValueError(f'hook for incorrect netloc {print_parse.netloc.print(netloc_key)}')

        hook_list = hooks.get(netloc)
        if not hook_list:
            raise ValueError(f'hook missing for given netloc {print_parse.netloc.print(netloc)}')

        try:
            [hook] = hook_list
        except ValueError:
            raise ValueError(
                f'more than one hook given netloc {print_parse.netloc.print(netloc)}'
            ) from None

        self.check_hook_configuration(hook)

    def hook_create(self, netloc = None):
        '''
        Create webhook in the student project on GitLab with the given net location.
        The hook is triggered via HTTPS if tags are updated or issues are changed.
        The argument netloc is an instance of print_parse.NetLoc.

        If 'netloc' is None, uses the configured default (see Course.hook_normalize_netloc).

        Note: Due to a GitLab bug, the hook is not called when an issue is deleted.
              Thus, before deleting a response issue, you should first rename it
              (triggering the hook)  so that it is no longer recognized as a response issue.
        '''
        url = self._hook_url(netloc = netloc)
        self.logger.debug(f'Creating project hook with url {url}')
        try:
            return self.project.lazy.hooks.create({
                'url': url,
                'enable_ssl_verification': 'false',
                'token': self.course.config.webhook.secret_token,
                'issues_events': 'true',
                'tag_push_events': 'true',
                'push_events': 'false',
            })
        except gitlab.exceptions.GitlabCreateError as e:
            if e.response_code == 422 and e.error_message == 'Invalid url given':
                host = print_parse.url.parse(self.course.config.base_url).netloc.host
                raise ValueError(
                    f'Invalid net location {print_parse.netloc.print(netloc)} '
                    f'for a GitLab webhook at {host}.'
                ) from e
            else:
                raise

    def hook_delete(self, hook):
        ''' Delete a webhook in the student project on GitLab. '''
        self.logger.debug(f'Deleting project hook {hook.id} with url {hook.url}')
        hook.delete()

    def hooks_delete_all(self, hooks = None, except_for = ()):
        '''
        Delete all webhook in the student project with the given netloc on GitLab.
        The argument netloc is an instance of print_parse.NetLoc.
        You should use this:
        * when manually creating and deleting hooks in separate program invocations,
        * when using hook_manager:
            if previous program runs where killed or stopped in a non-standard fashion
            that prevented cleanup and have left lingering webhooks.

        If 'hooks' is None, get the hooks from the project.

        If except_for is set, skips hooks that match the specified net location.
        If that is None, uses the configured default (see Course.hook_normalize_netloc).
        '''
        if except_for == ():
            self.logger.debug('Deleting all project hooks')
        else:
            netloc = self.course.hook_normalize_netloc(except_for)
            self.logger.debug(
                'Deleting all project hooks except those with '
                f'net location {print_parse.netloc.print(netloc)}'
            )

        if hooks is None:
            hooks = self.hooks_get()

        for (netloc_key, hook_list) in hooks.items():
            for hook in hook_list:
                if not (except_for != () and netloc_key == netloc):
                    self.hook_delete(hook)

    def hook_ensure(self, hooks = None, netloc = None):
        '''
        Ensure that the hook in this student project is correctly configured.
        Also makes sure there are no other hooks.
        (This is to deal with cases of changing IP addresses.)

        If 'hooks' is None, get the hooks from the project.
        If 'netloc' is None, uses the configured default (see Course.hook_normalize_netloc).
        '''
        self.logger.info('Ensuring webhook configuration.')
        if hooks is None:
            hooks = self.hooks_get()
        try:
            self.check_hooks(netloc = netloc)
        except ValueError:
            self.hook_delete_all()
            self.hook_create(netloc = netloc)

    @contextlib.contextmanager
    def hook_manager(self, netloc = None):
        '''
        A context manager for a webhook.
        Encapsulates hook_create and hool_delete.
        '''
        hook = self.hook_create(netloc = netloc)
        try:
            yield hook
        finally:
            self.hook_delete(hook)

    def tags_from_gitlab(self):
        self.logger.debug(f'Parsing request tags in {self.name} from Chalmers GitLab.')
        return [(tag.name, tag) for tag in gitlab_tools.get_tags_sorted_by_date(self.project.lazy)]

    def tags_from_repo(self):
        self.logger.debug(f'Parsing request tags in {self.name} from local grading repository.')
        return sorted((
            (str(key), (tag, tag.commit))
            for (key, tag) in self.lab.remote_tags[self.id].items()
        ), key = lambda x: git_tools.commit_date(x[1][1]))

    def parse_request_tags(self, from_gitlab = True):
        '''
        Parse request tags for this project and store the result in self.handler_data.
        The boolean parameter from_gitlab determines if:
        * (True) tags read from Chalmers GitLab (a HTTP call)
        * (False) tags are read from the local grading repository.

        This method needs to be called before requests_and_responses
        in each handler data instance can be accessed.
        '''
        # To be a valid request, the tag name must consist of a single path segment.
        # That is, it must be non-empty and cannot contain the character '/'.
        def check_single_path_segment(item):
            (tag_name, tag_data) = item
            tag_parts = PurePosixPath(tag_name).parts
            try:
                (_,) = tag_parts
            except ValueError:
                # Take tag out of the parsing stream.
                self.logger.warn(
                    'Ignoring tag {} in student group {} not composed '
                    "of exactly one path part (with respect to separator '/').".format(
                        shlex.quote(tag_name), self.name
                    )
                )
                return ()

            # Keep tag for further parsing
            return None

        def f():
            yield (check_single_path_segment, None, None)
            for handler_data in self.handler_data.values():
                yield handler_data.request_tag_parser_data()

        item_parser.parse_all_items(
            item_parser.Config(
                location_name = self.name,
                item_name = 'request tag',
                item_formatter = lambda x: gitlab_tools.format_tag_metadata(self.project.get, x[0]),
                logger = self.logger,
            ),
            f(),
            {
                True: self.tags_from_gitlab,
                False: self.tags_from_repo,
            }[from_gitlab](),
        )

        # Clear requests and responses cache.
        for handler_data in self.handler_data.values():
            with contextlib.suppress(AttributeError):
                del handler_data.requests_and_responses

    def official_issues(self):
        '''
        Generator function retrieving the official issues.
        An official issue is one created by a grader.
        Only official issues can be response issues.
        '''
        self.logger.debug(f'Retrieving response issues in {self.name}.')
        for issue in gitlab_tools.list_all(self.project.lazy.issues):
            if issue.author['id'] in self.course.graders:
                yield issue

    @property
    def submission_handler_data(self):
        '''The instance of HandlerData for the submission handler.'''
        return self.handler_data[self.lab.config.submission_handler_key]

    @property
    def reviews(self):
        '''
        The review response dictionary of the submission handler.
        This is a dictionary mapping request names to response issue title parsings.
        Is None before parse_response_issues is called.

        Only valid if review issues are configured.
        '''
        return self.submission_handler_data.responses.get(
            self.lab.submission_handler.review_response_key
        )

    @property
    def reviews_data(self):
        '''
        Modified version of reviews.
        The returned dictionary has as values only the issue title parsing.
        Is None before parse_response_issues is called.
        '''
        def action(x):
            (_, r) = x
            return r

        return general.maybe(functools.partial(general.map_values, action))(self.reviews)

    def parse_response_issues(self):
        '''
        Parse response issues for this project on Chalmers GitLab
        on store the result in self.handler_data.
        Cost: one HTTP call.

        This method needs to be called before requests_and_responses
        in each contained handler data instance can be accessed.

        Returns a boolean indicating if there is
        a change in the review responses, if configured.
        This includes the full issue title parsing, in particular the outcome.
        '''
        if self.lab.have_reviews:
            data_previous = self.reviews_data

        def f():
            for handler_data in self.handler_data.values():
                yield from handler_data.response_issue_parser_data()

        item_parser.parse_all_items(
            item_parser.Config(
                location_name = self.name,
                item_name = 'response issue',
                item_formatter = gitlab_tools.format_issue_metadata,
                logger = self.logger,
            ),
            f(),
            self.official_issues(),
        )

        # Clear requests and responses cache.
        for handler_data in self.handler_data.values():
            with contextlib.suppress(AttributeError):
                del handler_data.requests_and_responses

        if self.lab.have_reviews:
            data_current = self.reviews_data
            self.logger.debug(f'current reviews: {data_current}')
            if data_previous is None:
                self.logger.debug('previous reviews not fetched')
                return True
            self.logger.debug(f'previous reviews: {data_previous}')
            return data_current != data_previous
        return False

    def process_requests(self):
        '''
        Process requests.
        This skips requests already marked as handled in the local grading repository.

        Returns a dictionary mapping handler keys to sets of newly handed request names.
        '''
        return {
            handler_key: handler_data.process_requests()
            for (handler_key, handler_data) in self.handler_data.items()
        }

    def submissions(self, deadline = None):
        '''
        Counts only the accepted submission attempts.
        If deadline is given, we restrict to prior submissions.
        Here, the date refers to the date of the submission commit.
        Returns an iterable of instances of SubmissionAndRequests ordered by the date.
        '''
        submission_handler_data = self.handler_data[self.lab.config.submission_handler_key]
        for request_and_responses in submission_handler_data.requests_and_responses.values():
            if request_and_responses.accepted:
                if deadline is None or request_and_responses.date <= deadline:
                    yield request_and_responses

    def submissions_with_outcome(self, deadline = None):
        '''
        Restricts the output of self.submissions to instances of SubmissionAndRequests with an outcome.
        This could be a submission-handler-provided outcome or a review by a grader.
        Returns an iterable of instances of SubmissionAndRequests ordered by the date.
        '''
        for submission in self.submissions(deadline = deadline):
            if submission.outcome is not None:
                yield submission

    def submissions_relevant(self, deadline = None):
        '''
        Restrict the output of self.submissions to all relevant submissions.
        A submission is *relevant* if it has an outcome or is the last submission and needs a review.
        Returns an iterable of instances of SubmissionAndRequests ordered by the date.
        '''
        submissions = list(self.submissions(deadline = deadline))
        for (i, submission) in enumerate(submissions):
            if i + 1 == len(submissions) or submission.outcome is not None:
                yield submission

    def submission_current(self, deadline = None):
        '''
        With respect to the output of self.submissions, return the last submission
        if it needs a review (i.e. does not uet have an outcome), otherwise return None.
        Returns an instances of SubmissionAndRequests or None.
        '''
        submissions = list(self.submissions(deadline = deadline))
        if submissions:
            submission_last = submissions[-1]
            if submission_last.outcome is None:
                return submission_last

    def parse_hook_event_tag(self, hook_event, strict):
        '''
        For a tag push event, we always generate a queue event.
        TODO (optimization): Check that the tag name matches a request matcher.
        '''
        self.logger.debug('Received a tag push event.')
        ref = hook_event.get('ref')
        self.logger.debug(f'Reference: {ref}.')
        yield (
            events.GroupProjectTagEvent(),
            lambda: self.lab.refresh_group(self, refresh_responses = False),
        )

    def parse_hook_event_issue(self, hook_event, strict):
        '''
        We only generate a group projectevent if both:
        - the (current or previous) author is a grader,
        - the title has changed.

        Note: uses self.course.graders.
        '''
        self.logger.debug('Received an issue event.')
        object_attributes = hook_event.get('object_attributes')
        title = None if object_attributes is None else object_attributes['title']
        self.logger.debug(f'Issue title: {title}.')

        changes = hook_event.get('changes')

        def author_id():
            if object_attributes is not None:
                return object_attributes['author_id']

            author_id_changes = changes['author_id']
            for version in ['current', 'previous']:
                author_id = author_id_changes[version]
                if author_id is not None:
                    return author_id

            raise ValueError('author id missing')
        author_id = author_id()
        author_is_grader = author_id in self.course.grader_ids
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

        # TODO.
        # We could go further and only queue and event
        # if the old or new title parses as a review issue.
        # Then GroupProjectIssueEvent should be renamed GroupProjectReviewEvent.
        # We don't do much work in handling GroupProjectIssueEvent for non-review issues anyway.
        # And it might be beneficial to be up-to-date also with non-review response issues.
        # So keeping this as is for now.
        if author_is_grader and title_change:
            yield (
                events.GroupProjectIssueEvent(),
                lambda: self.lab.refresh_group(self, refresh_responses = True),
            )

    def parse_hook_event(self, hook_event, strict = False):
        '''
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
        '''
        event_type = webhook_listener.event_type(hook_event)
        if event_type == 'tag_push':
            yield from self.parse_hook_event_tag(hook_event, strict)
        elif event_type == 'issue':
            yield from self.parse_hook_event_issue(hook_event, strict)
        else:
            if strict:
                raise ValueError(f'Unknown event {event_type}')

            self.logger.warning(f'Received unknown webhook event of type {event_type}.')
            self.logger.debug(f'Webhook event:\n{hook_event}')

    @property
    def lab_event(self):
        return lambda group_project_event: events.LabEventInGroupProject(
            group_id = self.id,
            group_project_event = group_project_event,
        )
