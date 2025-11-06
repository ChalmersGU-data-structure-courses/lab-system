from collections.abc import Iterable
from typing import Any, TYPE_CHECKING

import lab_interfaces
import grading_sheet.core
import util.general
import google_tools.general
import google_tools.sheets
import gitlab_.tools

if TYPE_CHECKING:
    import course as module_course
    import lab as module_lab


class GradingSheetLabUpdateListener[LabId, GroupId](
    lab_interfaces.LabUpdateListener[GroupId]
):
    lab: "module_lab.Lab[LabId, GroupId, Any]"
    spreadsheet: grading_sheet.core.GradingSpreadsheet[LabId]
    sheet: grading_sheet.core.GradingSheet[LabId, GroupId, Any]

    ids: set[GroupId]
    needed_num_queries: int

    def __init__(
        self,
        lab: "module_lab.Lab[LabId, GroupId, Any]",
        grading_spreadsheet: grading_sheet.core.GradingSpreadsheet[LabId],
        deadline=None,
    ):
        self.lab = lab
        self.spreadsheet = grading_spreadsheet
        self.sheet = self.spreadsheet.grading_sheets[self.lab.id]
        self.deadline = deadline

        self.id = set()
        self.needed_num_queries = 0

    @property
    def course(self) -> "module_course.Course":
        return self.lab.course

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
            bool(list(group.submissions_relevant(self.deadline)))
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
        self.sheet.data_clear()

        # Setup groups.
        self.sheet.setup_groups(groups=ids, group_link=self.group_link)

        # Ensure grading sheet has sufficient query group columns.
        query_counts = (
            util.general.ilen(group.submissions_relevant(self.deadline))
            for group in groups
        )
        num_queries = max(query_counts, default=0)
        self.sheet.ensure_num_queries(num_queries)

        def requests() -> Iterable[google_tools.general.Request]:
            # Update the grading sheet.
            for group in groups:
                for query, submission in enumerate(
                    group.submissions_relevant(self.deadline)
                ):
                    q = self.sheet.query(group.id, query)
                    yield from q.requests_write_submission(
                        submission.request_name,
                        gitlab_.tools.url_tag_name(
                            group.project.get,
                            submission.request_name,
                        ),
                    )
                    if submission.outcome is not None:
                        yield from q.requests_write_grader(
                            submission.grader_informal_name
                        )
                        yield from q.requests_write_outcome(
                            self.lab.config.outcomes.as_cell.print(submission.outcome),
                            submission.link,
                        )

        self.spreadsheet.client_update_many(list(requests()))
