import bisect
import contextlib
import datetime
import functools
import logging
import time

import more_itertools

import gitlab_.tools
import util.general
import util.git
import util.markdown
import util.print_parse


class SetupData:
    def __init__(self, lab, variant=None):
        self.lab = lab
        self.variant = variant

    @functools.cached_property
    def label_pp(self):
        return util.print_parse.Dict(
            (outcome, label_spec.name)
            for (outcome, label_spec) in self.lab.config.outcomes.labels.items()
        )

    @property
    def title_pp(self):
        return self.lab.config.variants.submission_grading_title

    @functools.cached_property
    def title(self):
        return self.title_pp.print(self.variant)

    # TODO: remove hard-coding
    @functools.cached_property
    def source_branch(self):
        return self.lab.config.branch_submission(self.variant)

    @functools.cached_property
    def target_branch(self):
        return self.lab.config.branch_problem(variant=self.variant)


class GradingViaMergeRequest:
    sync_message = util.print_parse.compose(
        util.print_parse.combine(
            (util.print_parse.escape_brackets, util.print_parse.escape_parens)
        ),
        util.print_parse.regex_many(
            "Synchronized submission branch with [{}]({}).",
            [r"(?:[^\[\]\\]|\\[\[\]\\])*", r"(?:[^\(\)\\]|\\[\(\)\\])*"],
        ),
    )

    non_grader_change_message = util.general.join_lines(
        ["⚠️**WARNING**⚠️ Grading label change by non-grader detected."]
    )

    def __init__(self, setup_data, group, logger=logging.getLogger(__name__)):
        self.setup_data = setup_data
        self.group = group
        self.logger = logger

        self.notes_suppress_cache_clear_counter = 0
        self.non_grader_change = False
        self.outcome_last_checked = None

    @property
    def course(self):
        return self.group.course

    @property
    def gl(self):
        return self.group.gl

    @property
    def lab(self):
        return self.group.lab

    @property
    def project(self):
        return self.group.project.get

    def update_merge_request_description(self):
        """
        Call after a change in group members.
        Returns a boolean indicating if an update was performed.
        """
        description_new = self.merge_request_description()
        update_needed = self.merge_request.description != description_new
        if update_needed:
            self.merge_request.description = description_new
            self.merge_request.save()
            # Don't invalidate the cached merge request notes.
            # The edit note is not relevant for us.
        return update_needed

    def merge_request_create(self):
        """
        Branches:
        * main: containing a readme linking to the merge request,
        * problem: lab problem stub,
        * submission: branch tracking submission tags in the student project,
        """
        for label_spec in self.lab.config.outcomes.labels.values():
            with gitlab_.tools.exist_ok():
                label_data = {
                    "name": label_spec.name,
                    "color": label_spec.color,
                }
                self.project.labels.create(label_data)

        with gitlab_.tools.exist_ok():
            self.project.branches.create(
                {
                    "branch": self.setup_data.source_branch,
                    "ref": self.setup_data.target_branch,
                }
            )
        with gitlab_.tools.exist_ok():
            gitlab_.tools.protect_branch(
                self.project,
                self.setup_data.source_branch,
            )

        merge_request_data = {
            "source_branch": self.setup_data.source_branch,
            "target_branch": self.setup_data.target_branch,
            "title": self.setup_data.title,
        }
        self.merge_request = self.project.mergerequests.create(merge_request_data)

    @functools.cached_property
    def merge_request(self):
        def f():
            for merge_request in gitlab_.tools.list_all(self.project.mergerequests):
                if all(
                    [
                        merge_request.author["id"] in self.course.lab_system_users,
                        merge_request.title == self.setup_data.title,
                    ]
                ):
                    yield merge_request

        merge_requests = list(f())
        try:
            merge_request_maybe = util.general.from_singleton_maybe(merge_requests)
        except ValueError:
            raise ValueError(
                "More than one lab system merge request"
                f" detected in {self.group.path_name}"
            ) from None

        return merge_request_maybe

    def merge_request_ensure(self):
        if self.merge_request is None:
            self.merge_request_create()

    def merge_request_cached(self):
        return "merge_request" in self.__dict__

    def merge_request_clear(self):
        with contextlib.suppress(AttributeError):
            del self.merge_request

    def with_merge_request_url(self, line):
        return util.general.join_lines([line, f"* {self.merge_request.web_url}"])

    @functools.cached_property
    def notes(self):
        return gitlab_.tools.list_all(self.merge_request.notes, sort="asc")

    def notes_cached(self):
        return "notes" in self.__dict__

    def notes_clear(self):
        """Actually, cleares cache for notes and label events."""
        for x in [
            "notes",
            "synced_submissions",
            "synced_submissions_by_date",
            "reviewer_intervals",
            "reviewer_current",
            "label_events",
            "submission_outcomes",
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
        return [
            (gitlab_.tools.parse_date(note.created_at), note) for note in self.notes
        ]

    def synced_submissions_generator(self):
        for note in self.notes:
            if note.author["id"] in self.course.lab_system_users:
                try:
                    line = note.body.splitlines()[0]
                    (request_name, _) = self.sync_message.parse(line)
                    yield (
                        request_name,
                        (gitlab_.tools.parse_date(note.created_at), note),
                    )
                except ValueError:
                    pass

    @functools.cached_property
    def synced_submissions(self):
        return dict(self.synced_submissions_generator())

    @functools.cached_property
    def synced_submissions_by_date(self):
        return [
            (date, request_name)
            for (request_name, (date, _)) in self.synced_submissions.items()
        ]

    @functools.cached_property
    def reviewer_intervals(self):
        return list(gitlab_.tools.parse_reviewer_intervals(self.notes))

    @functools.cached_property
    def reviewer_current(self):
        """
        The pair of the current reviewer and the point when they started reviewing.
        The point is a pair of a note id and instance of datetime.datetime.
        None if no reviewer is currently assigned (according to the notes).
        """
        with contextlib.suppress(IndexError):
            (reviewer, (start, end)) = self.reviewer_intervals[-1]
            if end is None:
                return (reviewer, start)

        return None

    def label_events_generator(self):
        for label_event in gitlab_.tools.list_all(
            self.merge_request.resourcelabelevents
        ):
            try:
                outcome = self.setup_data.label_pp.parse(label_event.label["name"])
            except KeyError:
                continue

            user_id = label_event.user["id"]
            action = gitlab_.tools.parse_label_event_action(label_event.action)
            if user_id in self.course.lab_system_users and (
                outcome is None if action else outcome is not None
            ):
                system = True
            elif user_id in self.course.graders:
                system = False
            else:
                self.non_grader_change = True
                self.logger.warn(
                    self.with_merge_request_url(
                        f"Grading label changed by non-grader {user_id} in"
                        f" {self.group.name} in {self.lab.name}:",
                    )
                )
                continue

            username = label_event.user["username"]
            date = gitlab_.tools.parse_date(label_event.created_at)
            yield (date, (outcome, action), (username, system))

    @functools.cached_property
    def label_events(self):
        xs = list(self.label_events_generator())
        if not util.general.is_sorted(xs, key=lambda x: x[0]):
            self.logger.warn(
                self.with_merge_request_url(
                    "Grading label events not sorted by creation date:"
                )
            )
            raise ValueError
        return xs

    def label_event_url(self, date):
        """
        Hacky workaround.
        See gitlab-resource-label-event-url.md for why is this broken.
        """
        i = bisect.bisect_right(self.notes_by_date, date, key=lambda x: x[0]) - 1
        note = self.notes_by_date[i][1] if i >= 0 else None
        return gitlab_.tools.url_merge_request_note(self.merge_request, note)

    def submission_label_events(self, request_from=None, request_to=None):
        if request_from is not None:
            date_from = self.sync_submissions([request_from])
        if request_to is not None:
            date_to = self.sync_submissions([request_to])

        def conditions(x):
            if request_from is not None:
                yield x[0] > date_from
            if request_to is not None:
                yield x[0] <= date_to

        return filter(self.label_events, lambda x: all(conditions(x)))

    def play_submission_label_events(self, outcome_status, events):
        for date, (outcome, action), info in events:
            if outcome in outcome_status:
                (status, _) = outcome_status[outcome]
                if action == status:
                    self.logger.warn(
                        self.with_merge_request_url(
                            "Duplicate action for label"
                            f" {self.setup_data.label_pp.print(outcome)} at {date}:",
                        )
                    )
            outcome_status[outcome] = (action, (date, info))

    def consolidate_outcome(
        self,
        outcome_status,
        request_name,
        warn_if_no_outcome=True,
    ):
        outcomes = set(
            outcome for (outcome, (status, _)) in outcome_status.items() if status
        )
        try:
            (outcome,) = outcomes
            if outcome is not None:
                (_, info) = outcome_status[outcome]
                return (outcome, info)
        except ValueError:
            if outcomes or warn_if_no_outcome:
                n = self.setup_data.label_pp.print(None)
                s = ", ".join(
                    self.setup_data.label_pp.print(outcome) for outcome in outcomes
                )
                msg = f"Multiple outcomes [{s}]" if outcomes else "Missing outcome"
                self.logger.warn(
                    self.with_merge_request_url(
                        f"{msg} for submission {request_name}, defaulting to {n}:"
                    )
                )
        return None

    @functools.cached_property
    def submission_outcomes(self):
        outcome_status = {}

        def f():
            # pylint: disable=cell-var-from-loop
            it = iter(self.label_events)
            for request_name, request_name_next in more_itertools.stagger(
                self.synced_submissions.keys(),
                offsets=[0, 1],
                longest=True,
            ):
                if request_name_next is not None:
                    (date_to, _) = self.synced_submissions[request_name_next]
                (jt, it) = util.general.before_and_after(
                    # pylint: disable-next = possibly-used-before-assignment
                    lambda x: request_name_next is None or x[0] <= date_to,
                    it,
                )
                self.play_submission_label_events(outcome_status, jt)
                consolidated_outcome = self.consolidate_outcome(
                    outcome_status,
                    request_name,
                    not request_name_next,
                )
                if consolidated_outcome:
                    yield (request_name, consolidated_outcome)
            more_itertools.consume(it)

        return dict(f())

    @property
    def next_submission_with_outcome(self):
        """
        A dictionary sending each request name to the closest future request name with an outcome, if existing.
        Needed for the case that submissions are synced in the merge request in an order different from the submission dates.
        """

        def f():
            request_name_with_outcome = None
            for request_name in reversed(self.synced_submissions.keys()):
                if request_name in self.submission_outcomes:
                    request_name_with_outcome = request_name
                if request_name_with_outcome is not None:
                    yield (request_name, request_name_with_outcome)

        return dict(f())

    @property
    def last_outcome(self):
        if not self.submission_outcomes:
            return None

        return list(self.submission_outcomes.values())[-1]

    def set_labels(self, outcome_new):
        for outcome in self.lab.config.outcomes.outcomes:
            with contextlib.suppress(ValueError):
                self.merge_request.labels.remove(
                    self.setup_data.label_pp.print(outcome)
                )
        self.merge_request.labels.append(self.setup_data.label_pp.print(outcome_new))
        self.merge_request.save()

    # TODO: can't use because of race conditions.
    def reset_labels(self):
        self.set_labels(self.last_outcome)

    def update_outcomes(self, clear_cache=True):
        """
        Checks if there have been outcome changes since the last time this method was called.
        If within the context of notes_cache_clearing_suppressor, the clear_cache flag is ignored.
        """
        if self.merge_request is None:
            return None

        if self.notes_suppress_cache_clear_counter == 0 and clear_cache:
            self.notes_clear()
        updated = self.submission_outcomes != self.outcome_last_checked

        self.logger.debug(f"old outcomes: {self.outcome_last_checked}")
        self.logger.debug(f"new outcomes: {self.submission_outcomes}")
        self.logger.debug(f"updated: {updated}")

        if updated:
            self.update_merge_request_description()
        self.outcome_last_checked = self.submission_outcomes
        return updated

    def has_outcome(self):
        return any(
            outcome is not None for (outcome, _) in self.submission_outcomes.values()
        )

    def outcome_with_link_and_grader(self, request_name, accumulative=False):
        """
        Returns None if no outcome exists (e.g. waiting-for-grading).
        If accumulative is true, consider each outcome to also apply to previous synced submissions that do not have their own outcome.
        """
        if accumulative:
            request_name = self.next_submission_with_outcome.get(
                request_name,
                request_name,
            )

        try:
            (outcome, (date, (username, _system))) = self.submission_outcomes[
                request_name
            ]
        except KeyError:
            return None

        return (outcome, self.label_event_url(date), username)

    def summary_table(self):
        def column_specs():
            yield util.markdown.ColumnSpec(
                title=util.markdown.link(
                    "Submission tag",
                    gitlab_.tools.url_tag_name(self.group.project.lazy),
                )
            )
            yield util.markdown.ColumnSpec(title="Synchronized")
            yield util.markdown.ColumnSpec(
                title="Outcome",
                align=util.markdown.Alignment.CENTER,
            )
            yield util.markdown.ColumnSpec(
                title="Grader",
                align=util.markdown.Alignment.CENTER,
            )

        def rows():
            # pylint: disable=cell-var-from-loop
            for request_name, (_date, note) in self.synced_submissions.items():
                has_outcome = self.outcome_with_link_and_grader(request_name)
                if has_outcome:
                    (outcome, link, grader) = has_outcome

                def col_request_name():
                    return util.markdown.link(
                        request_name,
                        gitlab_.tools.url_tree(
                            self.group.project.lazy,
                            request_name,
                            True,
                        ),
                    )

                def col_sync():
                    return util.markdown.link(
                        self.course.format_datetime(
                            gitlab_.tools.parse_date(note.created_at)
                        ),
                        gitlab_.tools.url_merge_request_note(self.merge_request, note),
                    )

                def col_outcome():
                    # pylint: disable=possibly-used-before-assignment

                    if not has_outcome:
                        return None

                    return util.markdown.link(
                        self.lab.config.outcomes.name.print(outcome),
                        link,
                    )

                def col_grader():
                    # pylint: disable=possibly-used-before-assignment

                    if not has_outcome:
                        return None

                    return util.markdown.link(
                        grader,
                        gitlab_.tools.url_username(self.gl, grader),
                    )

                yield (col_request_name(), col_sync(), col_outcome(), col_grader())

        return util.markdown.table(column_specs(), rows())

    def merge_request_description(self, for_real=True):
        def lines(mod):
            yield f"Your submission {mod} reviewed below."
            if self.synced_submissions:
                yield "Feel free to discuss, ask questions, and request clarifications!"
                yield "**Labels** record your grading status, so do not change them."

        def blocks():
            if not for_real:
                yield util.general.join_lines(
                    ["Your submission will be reviewed in this merge request."]
                )
            else:
                yield util.general.join_lines(
                    lines("is" if self.has_outcome() else "will be")
                )

                if self.non_grader_change:
                    yield self.non_grader_change_message

                if self.synced_submissions:
                    yield util.markdown.heading("Status", 1)
                    yield self.summary_table()

        result = util.markdown.join_blocks(blocks())
        if for_real and self.synced_submissions:
            result = self.group.append_mentions(result)
        return result.strip()

    # TODO
    def sync_submission(self, submission):
        return self.sync_submissions([submission])

    def sync_submissions(self, submissions, clear_cache=True):
        """
        Returns the list of newly synchronized submission request names.
        If within the context of notes_cache_clearing_suppressor, the clear_cache flag is ignored.
        """
        self.merge_request_ensure()

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
        block_period = self.lab.config.grading_via_merge_request.maximum_reserve_time
        if block_period is not None and self.reviewer_current:
            (_reviewer, (_start_id, start_date)) = self.reviewer_current
            if datetime.datetime.now(datetime.timezone.utc) < start_date + block_period:
                self.logger.warn(
                    self.with_merge_request_url(
                        f"New submission(s) made in {self.group.name}"
                        f"in {self.lab.name} while {self.reviewer_current[0]}"
                        f" is reviewer (blocking push of {submissions[0].request_name}"
                        " to submission branch):",
                    )
                )
                return []

        for submission in submissions:
            self.logger.info(f"Syncing submission {submission.request_name}.")
            self.lab.repo.git.push(
                self.project.ssh_url_to_repo,
                util.git.refspec(
                    submission.repo_tag().commit,
                    util.git.local_branch(self.setup_data.source_branch),
                    force=True,
                ),
            )

            # Hack
            time.sleep(0.1)

            def body():
                # pylint: disable=cell-var-from-loop
                link = gitlab_.tools.url_tree(
                    self.group.project.get,
                    submission.request_name,
                    True,
                )
                yield util.general.join_lines(
                    [self.sync_message.print((submission.request_name, link))]
                )
                submission_message = util.git.tag_message(
                    submission.repo_remote_tag,
                    default_to_commit_message=False,
                )
                if submission_message:
                    yield util.markdown.quote(submission_message)

            self.merge_request.notes.create({"body": util.markdown.join_blocks(body())})

        self.set_labels(None)

        self.notes_clear()
        self.update_merge_request_description()

        return [submission.request_name for submission in submissions]
