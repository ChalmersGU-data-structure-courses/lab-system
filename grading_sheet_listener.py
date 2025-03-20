from collections.abc import Iterable
from typing import Callable

import lab
import grading_sheet
import util.general
import google_tools.sheets
import gitlab_.tools


class GradingSheetLabUpdateListener[GroupIdentifier, Outcome](
    lab.LabUpdateListener[GroupIdentifier]
):
    grading_spreadsheet: grading_sheet.GradingSpreadsheet[GroupIdentifier, Outcome]
    lab: lab.Lab[GroupIdentifier]

    grading_sheet: grading_sheet.GradingSheet[GroupIdentifier, Outcome]

    ids: set[GroupIdentifier]
    needed_num_queries: int

    def __init__(
        self,
        lab: lab.Lab[GroupIdentifier],
        grading_spreadsheet: grading_sheet.GradingSpreadsheet[GroupIdentifier, Outcome],
        deadline=None,
    ):
        self.lab = lab
        self.grading_sheet = grading_sheet
        self.deadline = deadline

        self.id = set()
        self.needed_num_queries = 0

    def group_changed(self, id: GroupIdentifier) -> None:
        self.ids.add(id)

    def __enter__(self):
        pass

    def __exit__(self, type_, value, traceback):
        if type_ is not None:
            return

        self.ids = set()

    def include_group(self, id: GroupIdentifier) -> bool:
        """
        We include a group in the grading sheet if it is a student group with a submission.
        Extra groups to include can be configured in the grading sheet config using:
        * include_groups_with_no_submission
        """
        group = lab.groups[id]
        if not group.is_known or group.is_solution:
            return False

        return (
            list(group.submissions_relevant(self.deadline))
            or self.grading_sheet.config.include_groups_with_no_submission
            or group.non_empty()
        )

    def group_link(self, id: GroupIdentifier) -> str:
        if self.lab.student_connector.gdpr_link_problematic():
            return None

        return self.labs.groups[id].project.get.web_url

    def update(self, ids: Iterable[GroupIdentifier]) -> None:
        """
        Update the grading sheet.

        Arguments:
        * ids: groups to update.
        """
        ids = [id for id in ids if self.include_group_in_grading_sheet(id)]
        groups = [self.labs.groups[id] for id in ids]

        # Refresh grading sheet cache.
        self.grading_sheet.clear_cache()

        # Ensure grading sheet has rows for all required groups.
        self.grading_sheet.setup_groups(
            groups=ids,
            group_link=self.grading_sheet_group_link,
        )

        # Ensure grading sheet has sufficient query group columns.
        it = (
            util.general.ilen(group.submissions_relevant(self.deadline))
            for group in groups
        )
        self.grading_sheet.ensure_num_queries(max(it, default=0))

        request_buffer = self.grading_spreadsheet.create_request_buffer()
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

                self.grading_sheet.write_query(
                    request_buffer,
                    group.id,
                    query,
                    grading_sheet.Query(
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
