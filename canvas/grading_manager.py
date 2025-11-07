import functools
import logging

import canvas.client_rest as module_canvas_client_rest


_logger = logging.getLogger(__name__)


class GradingManager:
    logger: logging.Logger
    course: module_canvas_client_rest.Course
    assignment: module_canvas_client_rest.Assignment

    @property
    def canvas(self) -> module_canvas_client_rest.Canvas:
        return self.course.canvas

    def find_assignment(self, name: str, use_cache: bool) -> int | None:
        for assignment in self.course.get_assignments(use_cache=use_cache):
            if assignment.name == name:
                return assignment.id
        return None

    def get_id(self, name_or_id: int | str) -> int:
        if isinstance(name_or_id, int):
            return name_or_id

        for use_cache in [True, False]:
            id = self.find_assignment(name_or_id, use_cache)
            if id is not None:
                return id

        raise RuntimeError(f"No Canvas assignment with name {name_or_id}")

    def __init__(
        self,
        course: module_canvas_client_rest.Course,
        name_or_id: int | str,
        logger: logging.Logger = _logger,
    ):
        self.logger = logger
        self.course = course
        self.assignment = module_canvas_client_rest.Assignment(
            self.course,
            self.get_id(name_or_id),
        )

    @functools.cached_property
    def grades(self) -> dict[int, module_canvas_client_rest.Grade]:
        return self.assignment.get_grades()

    def update(self, grades: dict[int, module_canvas_client_rest.Grading]):
        for user_id, grading in grades.items():
            if not user_id in self.grades:
                raise ValueError(
                    f"No Canvas submission for {self.course.user_str(user_id)}"
                )

            grade_old = self.grades[user_id]
            grade_new = grading.grade
            if not grade_new == grade_old:
                if not grade_old is None:
                    self.logger.warn(
                        f"Overriding grade for {self.course.user_str(user_id)}: "
                        f"{grade_old} -> {grade_new}"
                    )
                self.grades[user_id] = self.assignment.set_grade(user_id, grading)
