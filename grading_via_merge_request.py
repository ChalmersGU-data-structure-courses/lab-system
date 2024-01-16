import bisect
import contextlib
import datetime
import functools
import logging
import shutil
import time

import git
import gitlab
import more_itertools

import general
import git_tools
import gitlab_.tools
import markdown
import path_tools
import print_parse


class SetupData:
    def __init__(self, lab):
        self.lab = lab

    @functools.cached_property
    def label_pp(self):
        return print_parse.from_dict(
            (outcome, label_spec.name)
            for (outcome, label_spec) in self.lab.config.outcome_labels.items()
        )

class GradingViaMergeRequest:
    sync_message = print_parse.regex_many(
        'Synchronized submission branch with [{}]({}).',
        [r'[^\]]*', r'[^\)]*'],
    )

    def __init__(self, setup_data, group, logger = logging.getLogger(__name__)):
        self.setup_data = setup_data
        self.group = group
        self.logger = logger

        parent = self.lab.dir_status_repos
        self.status_repo_dir = None if parent is None else parent / self.group.remote
        self.status_repo_up_to_date = False

        self.notes_suppress_cache_clear_counter = 0

    @property
    def course(self):
        return self.group.course

    @property
    def gl(self):
        return self.group.gl

    @property
    def lab(self):
        return self.group.lab

    @functools.cached_property
    def status_repo(self):
        '''
        Local status repository.
        This is used as staging for pushing the status report to the main branch in the student grading project.
        '''
        try:
            repo = git.Repo(self.status_repo_dir)
        except git.NoSuchPathError:
            self.status_repo_init()
            return self.repo
        else:
            self.status_repo_up_to_date = False
            return repo

    def status_repo_exists(self):
        return self.status_repo_dir.exists()

    def status_repo_delete(self, force = False):
        '''
        Delete the repository directory.
        Warning: Make sure that self.dir is correctly configured before calling.
        '''
        try:
            shutil.rmtree(self.status_repo_dir)
        except FileNotFoundError:
            if not force:
                raise

        self.status_repo_up_to_date = False

    def status_repo_init(self, project = None):
        '''
        Initialize the local grading repository.
        If the directory exists, we assume that all remotes are set up.
        Otherwise, we create the directory and populate it with remotes on Chalmers GitLab as follows.
        Fetching remotes are given by the official repository and student group repositories.
        Pushing remotes are just the grading repository.
        '''
        self.logger.debug('Initializing local grading status repository.')
        try:
            repo = git.Repo.init(
                str(self.status_repo_dir),
                initial_branch = self.course.config.branch.status,
                bare = True,
            )
            with repo.config_writer() as c:
                c.add_value('advice', 'detachedHead', 'false')

            git_tools.add_tracking_remote(
                repo,
                'origin',
                (project if project else self.project.get).ssh_url_to_repo,
                no_tags = True,
                overwrite = True,
                fetch_branches = [(git_tools.Namespacing.local, self.course.config.branch.status)],
                push_branches = [self.course.config.branch.status],
            )

            if project:
                with self.status_tree_manager(repo, for_real = False) as tree:
                    commit = git.Commit.create_from_tree(
                        repo = repo,
                        tree = tree,
                        message = 'Initial status commit.',
                        parent_commits = [],
                    )
                # TODO: outputs "creating head" (on stderr)
                repo.create_head(self.course.config.branch.status, commit, force = True)
                repo.remote('origin').push()

        except:  # noqa: E722
            self.status_repo_delete(force = True)
            raise

        self.repo = repo
        if project:
            self.status_repo_up_to_date = True

    def status_repo_report_status(self):
        '''Returns a boolean indicating if the status changes.'''
        self.project.create_ensured()  # do we need this here?
        if not self.status_repo_up_to_date:
            self.lab.repo_command_fetch(self.status_repo, ['origin'])
            self.status_repo_up_to_date = True

        branch = getattr(self.status_repo.heads, self.course.config.branch.status)
        commit_prev = branch.commit
        with self.status_tree_manager(self.status_repo) as tree:
            if tree == commit_prev.tree:
                return False

            commit = git.Commit.create_from_tree(
                repo = self.status_repo,
                tree = tree,
                message = 'Status update.',
                parent_commits = [commit_prev],
            )
        branch.reference = commit
        self.status_repo.remote('origin').push()
        return True

    def merge_request_description(self):
        return self.group.append_mentions(markdown.join_blocks([
            general.join_lines([
                'Your submission will be reviewed here.',
                'Feel free to discuss and ask questions!',
            ]),
            general.join_lines([
                '**Labels** record your grading status.',
            ]),
        ])).strip()

    @functools.cached_property
    def project(self):
        '''
        A project used exclusively for grading.
        Branches:
        * main: containing a readme linking to the merge request,
        * problem: lab problem stub,
        * submission: branch tracking submission tags in the student project,
        '''
        r = gitlab_.tools.CachedProject(
            gl = self.gl,
            logger = self.logger,
            path = self.group.path / 'grading',
            name = '{} — Grading'.format(self.lab.name_full),
        )

        def create():
            project = self.lab.official_project.get.forks.create({
                'namespace_path': str(r.path.parent),
                'path': r.path.name,
                'name': r.name,
                'description': f'Grading for [{self.lab.name_full}]({self.group.project.lazy.web_url})',
            })
            try:
                project = self.gl.projects.get(project.id, lazy = True)
                project.issues_enabled = False
                project.lfs_enabled = False
                project.packages_enabled = False
                project.save()

                for label_spec in self.lab.config.outcome_labels.values():
                    project.labels.create({
                        'name': label_spec.name,
                        'color': label_spec.color,
                    })

                project = gitlab_.tools.wait_for_fork(self.gl, project)

                project.branches.create({
                    'branch': 'submission',
                    'ref': self.course.config.branch.master,
                })

                self.merge_request = project.mergerequests.create({
                    'source_branch': 'submission',
                    'target_branch': self.course.config.branch.master,
                    'title': f'Grading for {self.group.name}',
                    'description': self.merge_request_description(),
                })

                self.status_repo_init(project)

                # Hack
                time.sleep(0.1)

                #project = gitlab_.tools.wait_for_fork(self.gl, project)
                project.default_branch = self.course.config.branch.status
                project.save()

                # Hack
                time.sleep(0.1)
                r.get = project

            except:  # noqa: E722
                r.delete()
                self.status_repo_delete(force = True)
                raise

        r.create = create
        return r

    def update_merge_request_description(self):
        '''
        Call after a change in group members.
        Returns a boolean indicating if an update was performed.
        '''
        description_new = self.merge_request_description()
        update_needed = self.merge_request.description != description_new
        if update_needed:
            self.merge_request.description = description_new
            self.merge_request.save()
            # Don't invalidate the cached merge request notes.
            # The edit note is not relevant for us.
        return update_needed

    @functools.cached_property
    def merge_request(self):
        self.project.create_ensured()  # do we need this here?
        (merge_request,) = gitlab_.tools.list_all(self.project.lazy.mergerequests)
        return merge_request

    def merge_request_cached(self):
        return 'merge_request' in self.__dict__

    def merge_request_clear(self):
        with contextlib.suppress(AttributeError):
            del self.merge_request

    def with_merge_request_url(self, line):
        return general.join_lines([line, f'* {self.merge_request.web_url}'])

    @functools.cached_property
    def notes(self):
        return gitlab_.tools.list_all(self.merge_request.notes, sort = 'asc')

    def notes_cached(self):
        return 'notes' in self.__dict__

    def notes_clear(self):
        '''Actually, cleares cache for notes and label events.'''
        for x in [
            'notes',
            'synced_submissions',
            'synced_submissions_by_date',
            'reviewer_intervals',
            'reviewer_current',
            'label_events',
            'submission_outcomes',
        ]:
            with contextlib.suppress(AttributeError):
                delattr(self, x)

    @contextlib.contextmanager
    def notes_suppress_cache_clear(self):
        self.notes_suppress_cache_clear_counter += 1
        try:
            yield
        finally:
            self.notes_suppress_cache_clear_counter -= 1

    @functools.cached_property
    def notes_by_date(self):
        return [(gitlab_.tools.parse_date(note.created_at), note) for note in self.notes]

    def synced_submissions_generator(self):
        for note in self.notes:
            if note.author['id'] in self.course.lab_system_users:
                try:
                    line = note.body.splitlines()[0]
                    (request_name, _) = self.sync_message.parse(line)
                    yield (request_name, (gitlab_.tools.parse_date(note.created_at), note))
                except ValueError:
                    pass
        pass

    @functools.cached_property
    def synced_submissions(self):
        return dict(self.synced_submissions_generator())

    @functools.cached_property
    def synced_submissions_by_date(self):
        return [(date, request_name) for (request_name, (date, _)) in self.synced_submissions.items()]

    @functools.cached_property
    def reviewer_intervals(self):
        return list(gitlab_.tools.parse_reviewer_intervals(self.notes))

    @functools.cached_property
    def reviewer_current(self):
        '''
        The pair of the current reviewer and the point when they started reviewing.
        The point is a pair of a note id and instance of datetime.datetime.
        None if no reviewer is currently assigned (according to the notes).
        '''
        with contextlib.suppress(IndexError):
            (reviewer, (start, end)) = self.reviewer_intervals[-1]
            if end is None:
                return (reviewer, start)

    def label_events_generator(self):
        for label_event in gitlab_.tools.list_all(self.merge_request.resourcelabelevents):
            try:
                outcome = self.setup_data.label_pp.parse(label_event.label['name'])
            except KeyError:
                continue

            user_id = label_event.user['id']
            action = gitlab_.tools.parse_label_event_action(label_event.action)
            if user_id in self.course.lab_system_users and (outcome is None if action else not outcome is None):
                system = True
            elif user_id in self.course.graders:
                system = False
            else:
                self.logger.warn(self.with_merge_request_url(
                    f'Grading label changed by non-grader {user_id} in {self.group.name} in {self.lab.name}:',
                ))
                continue

            username = label_event.user['username']
            date = gitlab_.tools.parse_date(label_event.created_at)
            yield (date, (outcome, action), (username, system))

    @functools.cached_property
    def label_events(self):
        xs = list(self.label_events_generator())
        if not general.is_sorted(xs, key = lambda x: x[0]):
            self.logger.warn(self.with_merge_request_url('Grading label events not sorted by creation date:'))
            raise ValueError
        return xs

    def label_event_url(self, date):
        '''
        Hacky workaround.
        See gitlab-resource-label-event-url.md for why is this broken.
        '''
        # TODO: we want to write:
        # i = bisect.bisect_right(self.notes_by_date, date, key = lambda x: x[0]) - 1
        # But the key argument is only supported from 3.10.
        i = bisect.bisect_right([date for (date, _) in self.notes_by_date], date) - 1
        note = self.notes_by_date[i][1] if i >= 0 else None
        return gitlab_.tools.url_merge_request_note(self.merge_request, note)

    def submission_label_events(self, request_from = None, request_to = None):
        if not request_from is None:
            date_from = self.sync_submissions[request_from]
        if not request_to is None:
            date_to = self.sync_submissions[request_to]

        def conditions(x):
            if not request_from is None:
                yield x[0] > date_from
            if not request_to is None:
                yield x[0] <= date_to
        return filter(self.label_events, lambda x: all(conditions(x)))

    def play_submission_label_events(self, outcome_status, events):
        for (date, (outcome, action), info) in events:
            if outcome in outcome_status:
                (status, _) = outcome_status[outcome]
                if action == status:
                    self.logger.warn(self.with_merge_request_url(
                        f'Duplicate action for label {self.setup_data.label_pp.print(outcome)} at {date}:',
                    ))
            outcome_status[outcome] = (action, (date, info))

    def consolidate_outcome(self, outcome_status, request_name, warn_if_no_outcome = True):
        outcomes = set(outcome for (outcome, (status, _)) in outcome_status.items() if status)
        try:
            (outcome,) = outcomes
            if outcome is not None:
                (_, info) = outcome_status[outcome]
                return (outcome, info)
        except ValueError:
            if outcomes or warn_if_no_outcome:
                n = self.setup_data.label_pp.print(None)
                s = ', '.join(self.setup_data.label_pp.print(outcome) for outcome in outcomes)
                msg = f'Multiple outcomes [{s}]' if outcomes else 'Missing outcome'
                self.logger.warn(self.with_merge_request_url(
                    f'{msg} for submission {request_name}, defaulting to {n}:'
                ))

    @functools.cached_property
    def submission_outcomes(self):
        outcome_status = dict()

        def f():
            it = iter(self.label_events)
            for (request_name, request_name_next) in more_itertools.stagger(
                self.synced_submissions,
                offsets = [0, 1],
                longest = True,
            ):
                if not request_name_next is None:
                    (date_to, _) = self.synced_submissions[request_name_next]
                (jt, it) = general.before_and_after(lambda x: request_name_next is None or x[0] <= date_to, it)
                self.play_submission_label_events(outcome_status, jt)
                consolidated_outcome = self.consolidate_outcome(outcome_status, request_name, not request_name_next)
                if consolidated_outcome:
                    yield (request_name, consolidated_outcome)
            more_itertools.consume(it)
        return dict(f())

    def update_outcomes(self, clear_cache = True):
        '''
        Checks if there have been outcome changes since the last time this method was called.
        If within the context of notes_cache_clearing_suppressor, the clear_cache flag is ignored.
        Updates the readme of the student grading project on outcome update.
        '''
        try:
            x = self.outcome_last_checked
        except AttributeError:
            x = None

        if self.notes_suppress_cache_clear_counter == 0 and clear_cache:
            self.notes_clear()
        updated = self.submission_outcomes != x

        self.logger.debug(f'old outcomes: {x}')
        self.logger.debug(f'new outcomes: {self.submission_outcomes}')
        self.logger.debug(f'updated: {updated}')

        if updated:
            self.status_repo_report_status()
        self.outcome_last_checked = self.submission_outcomes
        return updated

    def has_outcome(self):
        return any(outcome is not None for (outcome, _) in self.submission_outcomes.values())

    def outcome_with_link_and_grader(self, request_name):
        '''Returns None if no outcome exists (e.g. waiting-for-grading).'''
        try:
            (outcome, (date, (username, system))) = self.submission_outcomes[request_name]
        except KeyError:
            return None

        return (outcome, self.label_event_url(date), username)

    def summary_table(self):
        def column_specs():
            yield markdown.ColumnSpec(title = markdown.link(
                'Submission tag',
                gitlab_.tools.url_tag_name(self.group.project.lazy),
            ))
            yield markdown.ColumnSpec(title = 'Synchronized')
            yield markdown.ColumnSpec(title = 'Outcome', align = markdown.Alignment.CENTER)
            yield markdown.ColumnSpec(title = 'Grader', align = markdown.Alignment.CENTER)

        def rows():
            for (request_name, (date, note)) in self.synced_submissions.items():
                has_outcome = self.outcome_with_link_and_grader(request_name)
                if has_outcome:
                    (outcome, link, grader) = has_outcome

                def col_request_name():
                    return markdown.link(
                        request_name,
                        gitlab_.tools.url_tree(self.group.project.lazy, request_name)
                    )

                def col_sync():
                    return markdown.link(
                        self.course.format_datetime(gitlab_.tools.parse_date(note.created_at)),
                        gitlab_.tools.url_merge_request_note(self.merge_request, note)
                    )

                def col_outcome():
                    if has_outcome:
                        return markdown.link(self.course.config.outcome.name.print(outcome), link)

                def col_grader():
                    if has_outcome:
                        return markdown.link(grader, gitlab_.tools.url_username(self.gl, grader))

                yield (col_request_name(), col_sync(), col_outcome(), col_grader())

        return markdown.table(column_specs(), rows())

    def summary(self, for_real = True):
        '''Unless for_real is set, produces only an initial stub.'''
        def blocks():
            mod = 'is' if for_real and self.has_outcome() else 'will be'
            link = markdown.link('this merge request', f'!{self.merge_request.iid}')
            yield general.join_lines([f'You submission {mod} graded in {link}.'])
            if for_real and self.synced_submissions:
                yield markdown.heading('Status', 1)
                yield self.summary_table()

        return markdown.join_blocks(blocks())

    @contextlib.contextmanager
    def status_dir_manager(self, for_real = True):
        with path_tools.temp_dir() as dir:
            (dir / 'README.md').write_text(self.summary(for_real = for_real))
            yield dir

    @contextlib.contextmanager
    def status_tree_manager(self, repo, for_real = True):
        with self.status_dir_manager(for_real = for_real) as dir:
            yield git_tools.create_tree_from_dir(repo, dir)

    def add_students(self):
        self.group.members_clear()
        for gitlab_user in self.group.members:
            with gitlab_.tools.exist_ok():
                self.project.lazy.members.create({
                    'user_id': gitlab_user.id,
                    'access_level': gitlab.const.REPORTER_ACCESS,
                })
        self.update_merge_request_description()

    # TODO
    def sync_submission(self, submission):
        return self.sync_submissions([submission])

    def sync_submissions(self, submissions, clear_cache = True):
        '''
        Returns the list of newly synchronized submission request names.
        If within the context of notes_cache_clearing_suppressor, the clear_cache flag is ignored.
        '''
        def filter_out_synced_submissions(submissions):
            for submission in submissions:
                if not submission.request_name in self.synced_submissions:
                    yield submission

        if self.notes_suppress_cache_clear_counter == 0 and clear_cache:
            # Quick check if current cache of synced submissions include all the given ones.
            if self.notes_cached():
                submissions = list(filter_out_synced_submissions(submissions))
            if not submissions:
                return []

            # Redo the check with up-to-date synced submissions.
            self.notes_clear()

        submissions = list(filter_out_synced_submissions(submissions))
        if not submissions:
            return []

        # Block syncing if a review is happening.
        if self.reviewer_current:
            (reviewer, (start_id, start_date)) = self.reviewer_current
            block_period = self.course.config.grading_via_merge_request.maximum_reserve_time
            if not block_period or datetime.datetime.now(datetime.timezone.utc) < start_date + block_period:
                self.logger.warn(self.with_merge_request_url(
                    f'New submission(s) made in {self.group.name} in {self.lab.name}'
                    f' while {self.reviewer_current[0]} is reviewer '
                    f'(blocking push of {submissions[0].request_name} to submission branch):',
                ))
            return []

        for submission in submissions:
            self.logger.info(f'Syncing submission {submission.request_name}.')
            self.lab.repo.git.push(
                self.project.get.ssh_url_to_repo,
                git_tools.refspec(submission.repo_tag().commit, 'submission', force = True),
            )

            # Hack
            time.sleep(0.1)

            def body():
                link = gitlab_.tools.url_tree(self.group.project.get, submission.request_name)
                yield general.join_lines([self.sync_message.print((submission.request_name, link))])
                submission_message = git_tools.tag_message(
                    submission.repo_remote_tag,
                    default_to_commit_message = False,
                )
                if submission_message:
                    yield markdown.quote(submission_message)
            self.merge_request.notes.create({'body': markdown.join_blocks(body())})

        for outcome in self.course.config.outcomes:
            with contextlib.suppress(ValueError):
                self.merge_request.labels.remove(self.setup_data.label_pp.print(outcome))
        self.merge_request.labels.append(self.setup_data.label_pp.print(None))
        self.merge_request.save()
        self.add_students()

        self.notes_clear()
        self.status_repo_report_status()

        return [submission.request_name for submission in submissions]
