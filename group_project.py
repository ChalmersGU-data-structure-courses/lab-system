import contextlib
import functools
import general
import git
import gitlab
import logging
import tempfile
import types

import course_basics
import git_tools
import gitlab_tools
import grading_sheet
import print_parse

class HandlerData:
    def __init__(self, group, name, handler):
        self.course = group.lab.course
        self.lab = group.lab
        self.group = group
        self.logger = group.logger

        self.name = name
        self.handler = handler
        self.is_set_up = False

    def setup(self):
        if not self.is_set_up:
            with self.lab.checkout_and_compile_problem() as (src, bin):
                self.handler.setup(self.lab, src, bin)
            self.is_set_up = True

    def register_student_project_parsers(self, request_parsers, response_parsers):
        raise NotImplementedError()

    def process_parsing(self):
        raise NotImplementedError()

    def handle_requests(self):
        raise NotImplementedError()

class StudentCallableRobograderData(HandlerData):
    def register_student_project_parsers(self, request_parsers, response_parsers):
        self.request_tags = dict()
        request_parsers.append(self.course.request_tag_parser(
            self.handler.request_matcher,
            self.request_tags,
        ))

        self.response_issues = dict()
        response_parsers.append(self.course.simple_response_issue_parser(
            self.name,
            self.handler.response_title,
            self.response_issues,
        ))

    def process_parsing(self):
        self.requests_and_responses = self.course.pair_requests_and_responses(
            self.group.project.get,
            self.request_tags,
            self.response_issues,
        )

    def handle_requests(self):
        for (request, (tag, response)) in list(self.requests_and_responses.items()):
            if response == None:
                self.setup()
                self.requests_and_responses[request] = (tag, (self.robograde(request), ()))

    def robograde(self, request):
        self.logger.info(f'Robograding {request}')

        def post_issue(description):
            title = self.handler.response_title.print({'tag': request})
            return self.group.post_response_issue(title, description)

        # Check the commit out.
        with self.lab.checkout_with_empty_bin_manager(self.group.repo_tag(request).path) as (src, bin):
            # If a compiler is configured, compile first.
            if self.lab.config.compiler:
                self.logger.info('* compiling')
                try:
                    self.lab.compiler.compile(src, bin)
                except course_basics.SubmissionHandlingException as e:
                    description = gitlab_tools.append_paragraph(
                        e.markdown(),
                        'If you believe this is a mistake on our end, please contact the responsible teacher.'
                    )
                    return post_issue(description)

            # Call the robograder.
            try:
                self.logger.info('* robograding')
                description = self.handler.run(src, bin)
            except course_basics.SubmissionHandlingException as e:
                description = e.markdown()
            return post_issue(description)

class GroupProject:
    def build_handler_data(self, name, handler):
        if isinstance(handler, course_basics.StudentCallableRobograder):
            return StudentCallableRobograderData(self, name, handler)
        raise ValueError(f'Unimplemented handler type {handler} for handler {name}')

    def __init__(self, lab, id, logger = logging.getLogger('group-project')):
        self.course = lab.course
        self.lab = lab
        self.id = id
        self.logger = logger

        self.remote = self.course.config.group.full_id.print(id)

        # Submission handlers.
        self.handler_data = dict(
            (name, self.build_handler_data(name, handler))
            for (name, handler) in self.lab.config.submission_handlers.items()
        )

        #def f(x):
        #    return self.course.request_namespace(lambda request_type, spec: x)

        #self.request_tags = self.course.request_namespace(lambda x, y: dict())
        #self.response_issues = self.course.request_namespace(lambda x, y: dict())
        #self.requests_and_responses = self.course.request_namespace(lambda x, y: dict())

        # Map from submissions to booleans.
        # Values mean the following:
        # * not in map: submission has not yet been considered
        # * False: submission is invalid (for example, because compilation is required and it didn't compile)
        # * True: submission is valid (to be sent to graders)
        #self.submission_valid = dict()

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
            except:
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
                fetch_tags = [(git_tools.Namespacing.qualified_suffix_tag, git_tools.wildcard)],
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

    # def repo_tag_names(self):
    #     '''
    #     Read the local tags fetched from the student project on GitLab.
    #     Returns a list of tag names.
    #     '''
    #     dir = Path(self.lab.repo.git_dir) / git_tools.refs / git_tools.remote_tags / self.remote
    #     return [file.name for file in dir.iterdir()]

    def repo_tag(self, tag_name):
        '''
        Construct the tag (instance of git.Tag) in the grading repository
        corresponding to the tag with given name in the student repository.
        This will have the group's remote prefixed.

        Arguments:
        * tag_name: Instance of PurePosixPath, str, or gitlab.v4.objects.tags.ProjectTag.
        '''
        if isinstance(tag_name, gitlab.v4.objects.tags.ProjectTag):
            tag_name = tag_name.name
        tag_name = git_tools.qualify(self.remote, tag_name) / 'tag'
        return git_tools.normalize_tag(self.lab.repo, tag_name)

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
            head = False,
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

    def hook_create(self, netloc):
        '''
        Create webhook in the student project on GitLab.
        The hook is triggered if tags are updated or issues are changed.
        This r

        Note: Due to a GitLab bug, the hook is not called when an issue is deleted.
              Thus, before deleting a response issue, you should first rename it
              (triggering the hook)  so that it is no longer recognized as a response issue.
        '''
        url = print_parse.url.print(print_parse.URL_HTTPS(netloc))
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

    def hook_delete_all(self):
        '''
        Delete all webhook in the student project on GitLab.
        You should use this when previous program runs where killed or stopped
        in a non-standard fashion that prevented cleanup and have left lingering webhooks.
        '''
        for hook in self.project.lazy.hooks.list(all = True):
            self.hook_delete(hook)

    @contextlib.contextmanager
    def hook_manager(self, netloc):
        '''A context manager for creating a webhook.'''
        hook = self.hook_create(netloc)
        try:
            yield hook
        finally:
            self.hook_delete(hook)

    def post_response_issue(self, title, description):
        self.logger.debug(general.join_lines([
            'Posting response issue:',
            f'* title: {title}',
            f'* description:',
            *description.splitlines()
        ]))
        return self.project.lazy.issues.create({
            'title': title,
            'description': self.append_mentions(description)
        })

    def get_requests_and_responses(self):
        request_parsers = []
        response_parsers = []

        tags_submission = dict()
        request_parsers.append(self.course.submission_tag_parser(tags_submission))

        issues_grading = dict()
        response_parsers.append(self.course.grading_issue_parser(issues_grading))

        for handler in self.handler_data.values():
            handler.register_student_project_parsers(request_parsers, response_parsers)

        self.course.parse_all_tags(self.project.get, request_parsers)
        self.course.parse_all_response_issues(self.project.get, response_parsers)

        self.submissions_and_gradings = self.course.pair_requests_and_responses(
            self.project.get,
            tags_submission,
            issues_grading,
        )
        for handler in self.handler_data.values():
            handler.process_parsing()

    def handle_requests(self):
        for handler in self.handler_data.values():
            handler.handle_requests()
        



    def update_submissions_and_gradings(self, reload = False):
        if reload:
            with contextlib.suppress(AttributeError):
                del self.submissions_and_gradings
        self.submissions_and_gradings

    def submissions_and_gradings_before(self, deadline = None):
        return dict(filter(
            lambda x: deadline == None or x[1][0].date < deadline,
            self.submissions_and_gradings.items()
        ))

    def graded_submissions(self, deadline = None):
        def f():
            for entry in self.submissions_and_gradings_before(deadline).items():
                if entry[1][1] != None:
                    yield entry[1]
        return list(f())

    def current_submission(self, deadline = None):
        x = list(self.submissions_and_gradings_before(deadline).items())
        if x and x[-1][1][1] == None:
            return x[-1][1][0]
        return None

    def relevant_submissions(self, deadline = None):
        def f():
            yield from self.graded_submissions(deadline)
            x = list(self.submissions_and_gradings_before(deadline).items())
            if x and x[-1][1][1] == None:
                yield x[-1][1]
        return list(f())

    def update_request_tags(self):
        '''
        Update the request tags attribute from Chalmers GitLab.
        Returns an object with request types as attributes and values indicating if there was an update.
        '''
        request_tags = self.course.parse_request_tags(self.project.get)
        updated = self.course.request_namespace(lambda request_type, _:
            general.ne_on(
                request_tags,
                self.request_tags,
                lambda x: tuple(tag.name for tag in x.__dict__[request_type])
            )
        )
        self.request_tags = request_tags

        if any(updated.__dict__.values()):
            self.repo_fetch()
        return updated

    def response_key(self, response):
        '''
        When to consider two response issues to be the same.
        Used in update_response_issues.
        '''
        if response == None:
            return None

        (issue, parsed_issue) = response
        return parsed_issue

    def update_response_issues(self):
        '''
        Update the stored response issues attribute from Chalmers GitLab.
        Returns an object with request types as attributes and values indicating if there was an update.
        '''
        response_issues = self.course.parse_response_issues(self.project.get)
        updated = self.course.request_namespace(lambda request_type, _:
            general.ne_on(
                response_issues,
                self.response_issues,
                lambda x: dict(
                    (response_type, self.response_key(response))
                    for (response_type, response) in x.__dict__[request_type].items()
                )
            )
        )
        self.response_issues = response_issues
        return updated

    def update_requests_and_responses(self):
        '''
        Update the requests_and_responses attribute from the request_tag and response_issues attributes.
        Returns an object with request types as attributes and values indicating if there was an update.
        Updates are defined as in update_request_tags and update_response_issues.
        '''
        def key(x):
            if not x:
                return None

            (request, response) = next(reversed(x.items()))
            return dict(
                (request, self.response_key(response))
                for (response_type, response) in response.__dict__.items()
                if response_type != 'tag'
            )

        requests_and_responses = self.course.merge_requests_and_responses(
            self.project.get,
            self.request_tags,
            self.response_issues
        )
        updated = self.course.request_namespace(lambda request_type, _:
            general.ne_on(
                requests_and_responses,
                self.requests_and_responses,
                lambda x: key(x.__dict__[request_type]))
        )
        self.requests_and_responses = requests_and_responses
        return updated

    def post_issue(self, project, request_type, request, response_type, description, params):
        title = self.course.config.request.__dict__[request_type].issue.__dict__[response_type].print(
            params | {'tag': request}
        )
        self.logger.debug(general.join_lines([
            f'Title: {title}',
            'Description:',
        ]) + description)
        return project.lazy.issues.create({'title': title, 'description': description})

    def create_response_issue(
        self,
        request_type,
        request,
        response_type,
        description,
        params = dict(),
        exist_ok = True
    ):
        '''
        Create a response issue in the student project.
        Also update the local response cache ('response') with this response.
        If a response issue of the given response type already exists, do nothing if exist_ok holds.
        Otherwise, raise an error.
        '''
        self.logger.info(f'Creating {response_type} issue for {request_type} {request}.')

        response = self.requests_and_responses.__dict__[request_type][request]
        if response.__dict__[response_type]:
            raise ValueError(f'{response_type} issue for {request_type} {request} already exists.')

        description += self.mention_paragraph()
        qualified_request = self.course.qualify_request.print((self.id, request))
        issue = self.post_issue(self.project, request_type, qualified_request, response_type, description, params)
        response.__dict__[response_type] = (issue, params)
        return issue

    def create_response_issue_in_grading_project(
        self,
        request_type,
        request,
        response_type,
        description,
        params = dict(),
        exist_ok = True
    ):
        '''
        Create a response issue in the grading project (only visible to graders).
        Also update the local grading issue  cache ('grading_issue') with this response.
        If a response issue of the given response type already exists, do nothing if exist_ok holds.
        Otherwise, raise an error.
        '''
        key = (request, response_type)
        self.logger.info(f'Grading project: creating {response_type} issue for {request_type} {request}.')

        if key in self.grading_issues:
            raise ValueError(f'Grading project: {response_type} issue for {request_type} {request} already exists.')

        issue = self.post_issue(self.lab.grading_project, request_type, request, response_type, description, params)
        self.grading_issues[key] = (issue, params)
        return issue

    def process_robograding(self, request):
        '''
        Process a robograding request.
        The request is ignored if it has already been answered.
        There are two possible types of answers:
        * reporting a compilation problem,
        * the robograding report.
        '''
        # Get the response on record so far.
        response = self.requests_and_responses.robograding[request]

        # Have we already handled this request?
        if response.compilation or response.robograding:
            return

        self.logger.info(f'Robograding {request}')
        issue_params = types.SimpleNamespace(
            request_type = 'robograding',
            request = request,
        ).__dict__

        # Check the commit out.
        with (
            git_tools.with_checkout(self.lab.repo, git_tools.remote_tag(self.remote, request)) as src,
            tempfile.TemporaryDirectory() as bin
        ):
            # If a compiler is configured, compile first.
            if self.lab.config.compiler:
                self.logger.info('* compiling')
                try:
                    self.lab.config.compiler(src, bin)
                except course_basics.SubmissionHandlingException as e:
                    self.create_response_issue(**issue_params,
                        response_type = 'compilation',
                        description = e.markdown() + general.join_lines([
                            '',
                            'If you believe this is a mistake on our end, please contact the responsible teacher.'
                        ]),
                    )
                    return

            # Call the robograder.
            try:
                self.logger.info('* robograding')
                r = self.lab.config.robograder.run(src, bin)
                description = r.report
            except course_basics.SubmissionHandlingException as e:
                description = e.markdown()
            self.create_response_issue(**issue_params,
                response_type = 'robograding',
                description = description,
            )

    def process_robogradings(self):
        ''' Process all robograding requests. '''
        for request in self.requests_and_responses.robograding.keys():
            self.process_robograding(request)

    def process_submission(self, request):
        '''
        Process a submission request.
        '''
        # Have we already handled this request?
        if request in self.submissions_valid:
            return

        # Get the response on record so far.
        response = self.requests_and_responses.robograding[request]

        # If compilation is required and there is already a compilation response,
        # we record the submission as rejected.
        if all([
            self.lab.config.compilation_requirement == CompilationRequirement.require,
            response.compilation
        ]):
            self.submission_valid[request] = False
            return

        # Otherwise,

        self.logger.info(f'Handling submission {request}')
        issue_params = types.SimpleNamespace(
            request_type = 'submission',
            request = request,
        ).__dict__

        has_grading_robograding = self.grading_issues.get((request, 'robograding'))
        has_grading_compilation = self.grading_issues.get((request, 'compilation'))
        has_grading_issue = has_grading_robograding or has_grading_compilation

        #require_compilation = not has_grading_issue or False # Unfinished

        # Check the commit out.
        with (
            git_tools.with_checkout(self.lab.repo, git_tools.remote_tag(self.remote, request)) as src,
            tempfile.TemporaryDirectory() as bin,
        ):

            has_compilation: response.compilation

            # If a compiler is configured, compile first, but only if actually needed.
            compilation_okay = True
            if self.lab.config.compiler and not (response.compilation and has_grading_issue):
                self.logger.info('* compiling')
                try:
                    self.lab.config.compiler(src, bin)
                except course_basics.SubmissionHandlingException as e:
                    compilation_okay = False

                    # Only report problem if configured and not yet reported.
                    message = self.lab.config.compilation_message.get(self.lab.config.compilation_requirement)
                    if message != None:
                        self.create_response_issue(**issue_params,
                            response_type = 'compilation',
                            description = str().join([
                                message,
                                general.join_lines([]),
                                e.markdown(),
                            ])
                        )

                    # Stop if compilation is required.
                    if self.lab.config.compilation_requirement == CompilationRequirement.require:
                        self.submissions_valid[request] = False
                        return

                    # Report compilation problem in grading project.
                    if not has_grading_compilation:
                        self.create_response_issue_in_grading_project(**issue_params,
                            response_type = 'compilation',
                            description = e.markdown(),
                        )

            # Prepare robograding report for graders if configured.
            if self.lab.config.robograder and compilation_okay:
                try:
                    r = self.lab.config.robograder.run(src, bin)
                    description = r.report
                except course_basics.SubmissionHandlingException as e:
                    description = e.markdown()
                self.create_response_issue_in_grading_project(**issue_params,
                    response_type = 'robograding',
                    description = description,
                )

    def process_submissions(self):
        ''' Processes the latest submission, if any. '''
        x = self.requests_and_responses.submission
        if not x:
            return

        self.process_submission(next(reversed(x.keys())))


        # how do we know a submission has been processed?
        # ultimately, we can never know: we might have crashed.
        # we could run with a flag 'force' to indicate that we don't know.
        # if 'force' is false, then existing an robograding in the grading repository can indicate that we don't need to process.
        # but what if we don't have a robograder?
        # we would also have to compile again.
        # we could check in the google doc.
        # if we have an entry there, then we processed it already.

        # if self.lab.config.compiler:

        # with_remote = lambda s: '{}/{}'.format(remote, s)
        # logger.log(logging.INFO, 'Robograding {}...'.format(with_remote(tag)))

        # with tempfile.TemporaryDirectory() as dir:
        #     dir = Path(dir)
        #     self.submission_checkout(dir, abs_remote_tag(with_remote(tag)))

        #     response = None

        #     # TODO: Escape embedded error for Markdown.
        #     def record_error(description, error, is_code):
        #         nonlocal response
        #         code = '```' if is_code else ''
        #         response = '{}\n{}\n{}\n{}\n'.format(description, code, error.strip(), code)

        #     try:
        #         self.submission_check_symlinks(dir)
        #         self.submission_compile(dir)
        #         response = self.submission_robograde(dir)
        #     except check_symlinks.SymlinkException as e:
        #         record_error('There is a problem with symbolic links in your submission.', e.text, True)
        #     except java.CompileError as e:
        #         record_error('I could not compile your Java files:', e.compile_errors, True)
        #     except robograde.RobogradeFileConflict as e:
        #         response = 'I could not test your submission because the compiled file\n```\n{}\n```\nconflicts with files I use for testing.'.format(e.file)
        #     except robograde.RobogradeException as e:
        #         record_error('Oops, you broke me!\n\nI encountered a problem while testing your submission.\nThis could be a problem with myself (a robo-bug) or with your code (unexpected changes to class or methods signatures). If it is the latter, you might be able to elucidate the cause from the below error message and fix it. If not, tell my designers!', e.errors, True)

        #     if in_student_repo:
        #         response = '{}\n{}\n'.format(response, Course.mention(self.course.students(n)))

        #     p = self.lab_group_project(n) if in_student_repo else self.grading_project()
        #     logger.log(logging.INFO, response)
        #     p.issues.create({
        #         'title': self.config.testing_issue_print(tag if in_student_repo else with_remote(tag)),
        #         'description': response,
        #     })

        # logger.log(logging.INFO, 'Robograded {}.'.format(with_remote(tag)))
