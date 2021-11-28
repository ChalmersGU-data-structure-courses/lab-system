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

import instance_cache
import item_parser
import git_tools
import gitlab_tools
import print_parse


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
    '''
    def __init__(self, handler_data, request_name, tag_data):
        self.course = handler_data.course
        self.lab = handler_data.lab
        self.group = handler_data.group
        self.handler_data = handler_data
        self.logger = handler_data.logger

        self.request_name = request_name
        if isinstance(tag_data, gitlab.v4.objects.ProjectTag):
            self.gitlab_tag = tag_data
        else:
            self.gitlab_tag = None
            (self.repo_remote_tag, self.repo_remote_commit) = tag_data
        self.responses = dict()

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
        return self.group.repo_tag(self.request_name, segments)

    def repo_tag_exist(self, segments):
        '''Forwards to self.group.repo_tag_exist.'''
        return self.group.repo_tag_exist(self.request_name, segments)

    def repo_tag_create(self, segments = ['tag'], ref = None, **kwargs):
        '''Forwards to self.group.repo_tag_create.'''
        return self.group.repo_tag_create(self.request_name, segments, ref, **kwargs)

    def repo_tag_delete(self, segments = ['tag']):
        '''Forwards to self.group.repo_tag_delete.'''
        return self.group.repo_tag_delete(self.request_name, segments)

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

    def repo_report_create(self, segments, dir, follow_symlinks = False, commit_message = '', **kwargs):
        '''
        Commit the directory 'dir' as a descendant of self.repo_remote_commit
        and tag it as <group full id>/<request name>/<segments>.
        Further arguments are passed to self.repo_tag_create_json.
        Returns the created tag.
        '''
        tree = git_tools.create_tree_from_dir(self.lab.repo, dir, follow_symlinks = follow_symlinks)
        commit = git.Commit.create_from_tree(
            repo = self.lab.repo,
            tree = tree,
            message = commit_message,
            parent_commits = [self.repo_remote_commit],
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

    def _repo_tag_after_segments(self, prev_name):
        return ['after', prev_name]

    @instance_cache.instance_cache
    def repo_tag_after(self, prev_name):
        '''
        Returns an instance of git.TagReference for the tag with name
            <full group id>/<request name>/after/<prev_name>
        in the local grading repository.

        This points to a descendant commit of self.repo_remote_commit, identical in content,
        that is additionally a descendant of whatever commit prev_name refers to.
        '''
        return self._repo_tag_after_segments(prev_name)

    def repo_tag_after_create(self, prev_name, prev_ref):
        '''
        Given a reference prev_ref in the grading repository, create a tag
            <full group id>/<request name>/after/<prev_name>
        for a commit that is a descendant of both self.repo_tag and prev_ref.

        If self.repo_tag is a descendant of prev_commit, the commit is self.repo_remote_commit.
        Otherwise, it is created as a one-sided merge.

        Returns an instance of git.TagReference for the created tag.
        '''
        prev_commit = git_tools.resolve(self.lab.repo, prev_ref)
        if self.lab.repo.is_ancestor(prev_commit, self.repo_remote_commit):
            commit = self.repo_remote_commit
        else:
            commit = git_tools.onesided_merge(self.lab.repo, self.repo_remote_commit, prev_commit)
        return self.repo_tag_create(self._repo_tag_after_segments(prev_name), commit, force = True)

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
        '''
        # Skip processing if we already handled this request.
        if self.get_handled():
            return

        self.logger.info(f'Processing request {self.request_name} in {self.group.name}.')

        # Create tag <full group id>/<request name>/tag copying the request tag.
        self.repo_tag_create(
            ref = self.repo_remote_commit,
            message = git_tools.tag_message(self.repo_remote_tag),
            force = True,
        )

        # Call handler with this object as argment.
        self.logger.debug(
            f'Handling request {self.request_name} in {self.group.name} '
            f'using handler {self.handler_data.handler_key}'
        )
        result = self.handler_data.handler.handle_request(self)
        if result is not None:
            self.logger.debug(general.join_lines(['Handler result:', str(result)]))

        # Create tag <full-group-id>/<request_name>/handled
        # and store handler's result JSON-encoded as its message.
        self.set_handled(result)

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
        self.course = group.course
        self.lab = group.lab
        self.group = group
        self.logger = group.logger

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
        # mapping request names to issues and issue title parsings.
        #
        # Populated by GroupProject.parse_response_issues.
        # Initialized with inner dictionaries set to None.
        self.responses = {
            response_key: None
            for (response_key, issue_title) in self.handler.response_titles.items()
        }

        # Is this the submission handler?
        self.is_submission_handler = handler_key == self.lab.config.submission_handler_key

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
            result[request_name] = RequestAndResponses(self, request_name, tag_data)

        for (response_key, u) in self.responses.items():
            for (request_name, issue_data) in u.items():
                request_and_responses = result.get(request_name)
                if request_and_responses is None:
                    self.logger.warning(gitlab_tools.format_issue_metadata(
                        issue_data[0],
                        f'Response issue in {self.group.name} with no matching request tag:'
                    ))
                else:
                    request_and_responses.responses[response_key] = issue_data
        return result

    def process_requests(self):
        '''
        Process requests.
        This method assumes that requests_and_responses has been set up.
        It skips requests already marked as handled in the local grading repository.
        '''
        for request_and_responses in self.requests_and_responses.values():
            request_and_responses.process_request()

class GroupProject:
    '''
    This class abstracts over a lab project of a lab group on Chalmers GitLab.
    It collects instances of HandlerData.
    Each instances of this class is managed by an instance of lab.Lab.
    '''
    def __init__(self, lab, id, logger = logging.getLogger(__name__)):
        self.course = lab.course
        self.lab = lab
        self.id = id
        self.logger = logger

        self.name = self.course.config.group.name.print(id)
        self.remote = self.course.config.group.full_id.print(id)

        self.handler_data = {
            handler_key: HandlerData(self, handler_key)
            for handler_key in self.lab.config.request_handlers.keys()
        }

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
                self.lab.repo.git.push(
                    project.ssh_url_to_repo,
                    git_tools.refspec(
                        git_tools.local_branch(self.course.config.branch.problem),
                        self.course.config.branch.master,
                        force = True,
                    )
                )
                self.course.configure_student_project(project)
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

    def repo_fetch(self):
        '''
        Make sure the local repository as up to date with respect to
        the contents of the student repository on GitLab Chalmers.
        '''
        self.logger.info(f'Fetching from student repository, remote {self.remote}.')
        self.lab.repo.remote(self.remote).fetch('--update-head-ok')

    def repo_tag(self, request_name, segments = ['tag']):
        '''
        Construct a tag reference object for the current lab group.
        This only constructs an in-memory object and does not yet interact with the grading repository.
        The tag's name with habe the group's remote prefixed.

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

        request_name = git_tools.qualify(self.remote, request_name) / PurePosixPath(*segments)
        return git_tools.normalize_tag(self.lab.repo, request_name)

    def repo_tag_exist(self, request_name, segments = ['tag']):
        '''
        Test whether a tag with specified name and segments for the current lab group exists in the grading repository.
        Arguments are as for repo_tag.
        Returns a boolean.
        '''
        return git_tools.tag_exist(self.repo_tag(request_name, segments))

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
            ref = self.repo_tag(request_name).commit

        tag = self.lab.repo.create_tag(
            self.repo_tag(request_name, segments).name,
            ref = ref,
            **kwargs,
        )
        self.lab.repo_updated = True
        return tag

    def repo_tag_delete(self, request_name, segments):
        '''
        Delete a tag in the grading repository for the current lab group.
        This can be required under normal circumstances if submission review issues are altered.

        Arguments:
        * request_name, segments: As for repo_tag.
        '''
        self.lab.delete_tag(self.repo_tag(request_name, segments).name)
        self.lab.repo_updated = True

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
        index = git.IndexFile.from_tree(self.lab.repo, problem, master, hotfix, i = '-i')
        merge = index.write_tree()
        diff = merge.diff(master)
        if not diff:
            self.logger.warn('Hotfixing: hotfix already applied')
            return
        for x in diff:
            self.logger.info(x)

        commit = git.Commit.create_from_tree(
            self.lab.repo,
            merge,
            hotfix.message,
            parent_commits = [git_tools.resolve(self.lab.repo, master)],
            author = hotfix.author,
            committer = hotfix.committer,
            author_date = hotfix.authored_datetime,
            commit_date = hotfix.committed_datetime,
        )

        return self.lab.repo.remote(self.remote).push(git_tools.refspec(
            commit.hexsha,
            self.course.config.branch.master,
            force = False,
        ))

    def _hook_url(self, netloc):
        return print_parse.url.print(print_parse.URL_HTTPS(netloc))

    def hook_create(self, netloc):
        '''
        Create webhook in the student project on GitLab with the given net location.
        The hook is triggered via HTTPS if tags are updated or issues are changed.
        The argument netloc is an instance of print_parse.NetLoc.

        Note: Due to a GitLab bug, the hook is not called when an issue is deleted.
              Thus, before deleting a response issue, you should first rename it
              (triggering the hook)  so that it is no longer recognized as a response issue.
        '''
        url = self._hook_url(netloc)
        self.logger.debug(f'Creating project hook with url {url}')
        return self.project.lazy.hooks.create({
            'url': url,
            'enable_ssl_verification': 'false',
            'token': self.course.config.gitlab_webhook_secret_token,
            'issues_events': 'true',
            'tag_push_events': 'true',
        })

    def hook_delete(self, hook):
        ''' Delete a webhook in the student project on GitLab. '''
        self.logger.debug(f'Deleting project hook with url {hook.url}')
        hook.delete()

    def hook_delete_all(self, netloc):
        '''
        Delete all webhook in the student project with the given netloc on GitLab.
        The argument netloc is an instance of print_parse.NetLoc.
        You should use this:
        * when manually creating and deleting hooks in separate program invocations,
        * when using hook_manager:
            if previous program runs where killed or stopped in a non-standard fashion
            that prevented cleanup and have left lingering webhooks.
        '''
        url = self._hook_url(netloc)
        for hook in self.project.lazy.hooks.list(all = True):
            if hook.url == url:
                self.hook_delete(hook)

    @contextlib.contextmanager
    def hook_manager(self, netloc):
        '''
        A context manager for a webhook.
        Encapsulates hook_create and hool_delete.
        '''
        hook = self.hook_create(netloc)
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
                True: self.tags_from_gitlab(),
                False: self.tags_from_repo(),
            }[from_gitlab],
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

    def parse_response_issues(self):
        '''
        Parse response issues for this project on Chalmers GitLab
        on store the result in self.handler_data.
        Cost: one HTTP call.

        This method needs to be called before requests_and_responses
        in each contained handler data instance can be accessed.
        '''
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

    def process_requests(self):
        '''
        Process requests.
        This skips requests already marked as handled in the local grading repository.
        '''
        for handler_data in self.handler_data.values():
            handler_data.process_requests()

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
