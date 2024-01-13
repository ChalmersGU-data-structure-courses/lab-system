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
                    description = gitlab.tools.append_paragraph(
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

        self.name = self.course.config.group.name.print(id)

        self.handler_data = {
            handler_key: HandlerData(self, handler_key)
            for handler_key in self.lab.config.request_handlers.items()
        }

        # Submission handlers.
        #self.handler_data = dict(
        #    (name, self.build_handler_data(name, handler))
        #    for (name, handler) in self.lab.config.submission_handlers.items()
        #)

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

    # def repo_tag_names(self):
    #     '''
    #     Read the local tags fetched from the student project on GitLab.
    #     Returns a list of tag names.
    #
    #     TODO:
    #     Doesn't work references are packed by git.
    #     We should not assume they are unpacked.
    #     '''
    #     dir = Path(self.lab.repo.git_dir) / git_tools.refs / git_tools.remote_tags / self.remote
    #     return [file.name for file in dir.iterdir()]

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
