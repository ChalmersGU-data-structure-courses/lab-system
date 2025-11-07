import logging
from typing import Any, TYPE_CHECKING

import util.general
import canvas.grading_manager
import lab_interfaces

if TYPE_CHECKING:
    import course as module_course
    import lab as module_lab


_logger = logging.getLogger(__name__)


class CanvasGradingLabUpdateListener[GroupId, Outcome](
    lab_interfaces.LabUpdateListener[GroupId]
):
    logger: logging.Logger
    lab: "module_lab.Lab[Any, GroupId, Outcome]"
    grading_manager: canvas.grading_manager.GradingManager

    def __init__(
        self,
        lab: "module_lab.Lab[Any, GroupId, Outcome]",
        logger: logging.Logger = _logger,
    ):
        self.logger = logger
        self.lab = lab

        assignment_name = self.lab.config.canvas_assignment_name
        assert assignment_name is not None
        self.grading_manager = canvas.grading_manager.GradingManager(
            self.course.canvas_course,
            assignment_name,
        )

    @property
    def course(self) -> "module_course.Course":
        return self.lab.course

    def groups_changed(self, ids: list[GroupId]) -> None:
        groups = [self.lab.groups[id] for id in ids]
        for group in groups:
            submission = group.submission_outcome()
            if submission:
                outcome: Outcome
                outcome = submission.outcome_acc(accumulative=True)
                grade = self.lab.config.outcomes.canvas_grade[outcome]

                def canvas_user_ids(group=group):
                    for gitlab_user in group.members:
                        canvas_user = self.course.canvas_user_by_gitlab_username.get(
                            gitlab_user.username
                        )
                        if canvas_user is None:
                            self.logger.warn(
                                util.general.join_lines(
                                    f"Failed to set Canvas grade: GitLab user {gitlab_user.username} in not on Canvas.",
                                    f"* GitLab project: {group.project.get.web_url}/-/project_members",
                                )
                            )
                        yield canvas_user.id

                self.logger.debug(
                    f"Updating Canvas grade of members of {group.name} to {grade}"
                )
                grading = canvas.client_rest.Grading(
                    grade=grade,
                    comment=submission.link,
                )
                self.grading_manager.update({id: grading for id in canvas_user_ids()})
