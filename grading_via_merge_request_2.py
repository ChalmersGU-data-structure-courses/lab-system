import functools

import gitlab_.tools
import util.print_parse

sync_message = util.print_parse.regex_many(
    "Synchronized submission branch with [{}]({}).",
    [r"[^\]]*", r"[^\)]*"],
)


def note_date(note):
    return gitlab_.tools.parse_date(note.created_at)


class Notes:
    def __init__(self, g):
        self.g = g
        self.notes = gitlab_.tools.list_all(g.merge_request.notes, sort="asc")
        self.note_dates = {
            note.id: gitlab_.tools.parse_date(note.created_at) for note in self.notes
        }

    def synced_submissions_generator(self):
        for note in self.notes:
            if note.author["id"] in self.g.course.lab_system_users:
                try:
                    line = note.body.splitlines()[0]
                    (request_name, _) = self.sync_message.parse(line)
                    yield (request_name, note)
                except ValueError:
                    pass

    @functools.cached_property
    def synced_submissions(self):
        return dict(self.synced_submissions_generator())

    def summary_table(self):
        def column_specs():
            yield markdown.ColumnSpec(
                title=markdown.link(
                    "Submission tag",
                    gitlab_.tools.url_tag_name(self.group.project.lazy),
                )
            )
            yield markdown.ColumnSpec(title="Synchronized")
            yield markdown.ColumnSpec(title="Outcome", align=markdown.Alignment.CENTER)
            yield markdown.ColumnSpec(title="Grader", align=markdown.Alignment.CENTER)

        def rows():
            for request_name, note in self.synced_submissions.items():
                has_outcome = self.outcome_with_link_and_grader(request_name)
                if has_outcome:
                    (outcome, link, grader) = has_outcome

                def col_request_name():
                    return markdown.link(
                        request_name,
                        gitlab_.tools.url_tree(self.group.project.lazy, request_name),
                    )

                def col_sync():
                    return markdown.link(
                        self.course.format_datetime(
                            gitlab_.tools.parse_date(note.created_at)
                        ),
                        gitlab_.tools.url_merge_request_note(self.merge_request, note),
                    )

                def col_outcome():
                    if has_outcome:
                        return markdown.link(
                            self.course.config.outcome.name.print(outcome), link
                        )

                def col_grader():
                    if has_outcome:
                        return markdown.link(
                            grader, gitlab_.tools.url_username(self.gl, grader)
                        )

                yield (col_request_name(), col_sync(), col_outcome(), col_grader())

        return markdown.table(column_specs(), rows())


class GradingViaMergeRequest:
    def __init__(self, group, logger=logging.getLogger(__name__)):
        self.group = group
        self.logger = logger

    @property
    def course(self):
        return self.group.course

    @property
    def gl(self):
        return self.group.gl

    @property
    def lab(self):
        return self.group.lab
