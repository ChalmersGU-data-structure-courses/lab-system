from collections.abc import Iterable

import lab as lab_
import grading_sheet
import util.general
import google_tools.sheets
import gitlab_.tools


class GradingSheetLabUpdateListener[LabId, GroupId, Outcome](
    lab_.LabUpdateListener[GroupId]
):
    lab: lab_.Lab[LabId, GroupId]
    spreadsheet: grading_sheet.GradingSpreadsheet[LabId]
    sheet: grading_sheet.GradingSheet[GroupId, Outcome]

    ids: set[GroupId]
    needed_num_queries: int

    def __init__(
        self,
        lab: lab_.Lab[LabId, GroupId],
        grading_spreadsheet: grading_sheet.GradingSpreadsheet[GroupId, Outcome],
        deadline=None,
    ):
        self.lab = lab
        self.spreadsheet = grading_spreadsheet
        self.sheet = self.spreadsheet.grading_sheets[self.lab.id]
        self.deadline = deadline

        self.id = set()
        self.needed_num_queries = 0

    def group_changed(self, id: GroupId) -> None:
        self.ids.add(id)

    def __enter__(self):
        pass

    def __exit__(self, type_, value, traceback):
        if type_ is not None:
            return

        self.ids = set()

    def include_group(self, id: GroupId) -> bool:
        """
        We include a group in the grading sheet if it is a student group with a submission.
        Extra groups to include can be configured in the grading sheet config using:
        * include_groups_with_no_submission
        """
        group = self.lab.groups[id]
        if not group.is_known or group.is_solution:
            return False

        return (
            list(group.submissions_relevant(self.deadline))
            or self.sheet.config.include_groups_with_no_submission
            or group.non_empty()
        )

    def group_link(self, id: GroupId) -> str | None:
        if self.lab.student_connector.gdpr_link_problematic():
            return None

        return self.lab.groups[id].project.get.web_url

    def update(self, ids: Iterable[GroupId]) -> None:
        """
        Update the grading sheet.

        Arguments:
        * ids: groups to update.
        """
        ids = {id for id in ids if self.include_group(id)}
        groups = [self.lab.groups[id] for id in ids]

        # Refresh grading sheet cache.
        self.sheet.clear_cache()

        # Setup groups.
        self.sheet.setup_groups(groups=ids, group_link=self.group_link)

        # Ensure grading sheet has sufficient query group columns.
        query_counts = (
            util.general.ilen(group.submissions_relevant(self.deadline))
            for group in groups
        )
        num_queries = max(query_counts, default=0)
        self.sheet.ensure_num_queries(num_queries)

        # Update the grading sheet.
        request_buffer = self.spreadsheet.create_request_buffer()
        for group in groups:
            for query, submission in enumerate(
                group.submissions_relevant(self.deadline)
            ):
                if submission.outcome is None:
                    grader = None
                    outcome = None
                else:
                    grader = google_tools.sheets.cell_value(
                        submission.grader_informal_name
                    )
                    outcome = google_tools.sheets.cell_link_with_fields(
                        self.lab.course.config.outcome.as_cell.print(
                            submission.outcome
                        ),
                        submission.link,
                    )

                self.sheet.write_query(
                    request_buffer,
                    group.id,
                    query,
                    self.sheet.Query(
                        submission=google_tools.sheets.cell_link_with_fields(
                            submission.request_name,
                            gitlab_.tools.url_tag_name(
                                group.project.get,
                                submission.request_name,
                            ),
                        ),
                        grader=grader,
                        score=outcome,
                    ),
                )
        request_buffer.flush()
