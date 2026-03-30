import contextlib
import functools
import logging
import random
from pathlib import Path, PurePosixPath
from typing import Any, Callable

import util.path

import canvas.client_rest
import course as module_course
import lab as module_lab
import lab_interfaces
import live_submissions_table


@contextlib.contextmanager
def staging_manager(path: Path):
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def canvas_upload(
    path: Path,
    build: Callable[[Path], None],
    canvas_client: canvas.client_rest.Canvas,
    canvas_path: PurePosixPath,
    logger: logging.Logger,
    logging_name: str,
    path_staging: Path | None = None,
):
    if path_staging is None:
        path_staging = util.path.add_suffix(path, ".staging")

    logger.info(f"Updating {logging_name}")
    with staging_manager(path_staging):
        build(path_staging)
        if util.path.file_content_eq(path_staging, path, missing_ok_b=True):
            logger.debug(
                f"{logging_name.capitalize()} has not changed, "
                "skipping upload to Canvas."
            )
            return

        logger.info(f"Posting {logging_name} to Canvas")
        folder_path = canvas_path.parent
        folder = canvas_client.get_folder_by_path(folder_path)
        if folder is None:
            raise ValueError(f"No folder {folder_path} on Canvas.")
        # self.course.canvas_course.post_file(
        #     self.file_live_submissions_table_staging,
        #     folder.id,
        #     target.name,
        # )
        # Workaround for https://github.com/instructure/canvas-lms/issues/2309:
        with util.path.temp_file() as path_tmp:
            data = path_staging.read_text()
            data = data + "<!-- " + str(random.randbytes(16)) + " -->"
            path_tmp.write_text(data)
            canvas_client.post_file(path_tmp, folder.id, canvas_path.name)
        path_staging.replace(path)


class LiveSubmissionsTableLabUpdateListener[LabId, GroupId](
    lab_interfaces.LabUpdateListener[GroupId]
):
    lab: module_lab.Lab[LabId, GroupId, Any]
    logger: logging.Logger
    table: live_submissions_table.LiveSubmissionsTable

    @property
    def course(self):
        return self.lab.course

    @functools.cached_property
    def path(self) -> Path:
        return self.lab.dir / "live-submissions-table.html"

    @property
    def canvas_path(self) -> PurePosixPath:
        return self.course.config.canvas_grading_path / (self.lab.full_id + ".html")

    def __init__(self, lab: module_lab.Lab, deadline=None):
        """
        Setup the live submissions table.
        Takes an optional deadline parameter for limiting submissions to include.
        If not set, we use self.deadline.
        Request handlers should be set up before calling this method.
        """
        self.lab = lab
        self.logger = self.lab.logger

        if deadline is None:
            deadline = self.lab.deadline
        self.table = live_submissions_table.LiveSubmissionsTable(
            self.lab,
            config=live_submissions_table.Config(deadline=deadline),
            column_types=self.lab.submission_handler.grading_columns,
        )

    def update(self):
        """
        Updates the live submissions table on Canvas.
        Before calling this method, all group rows in the
        live submissions table need to have been updated.
        """
        canvas_upload(
            path=self.path,
            build=self.table.build,
            canvas_client=self.course.canvas_course,
            canvas_path=self.canvas_path,
            logger=self.logger,
            logging_name="live submissions table",
        )

    def groups_changed_prepare(self, ids, only_meta):
        self.table.update_rows(group_ids=ids)
        # with util.path.temp_dir() as dir:
        #     shutil.copyfile(self.path_staging, 'index.html')
        #     tree = util.git.create_tree_from_dir(dir)
        #     try:
        #         parents = [self.lab.repo.heads[self.head_table].commit]
        #     except IndexError:
        #         parents = []
        #     commit = git.Commit.create_from_tree(
        #         self.repo,
        #         tree,
        #         'Update live submissions table.',
        #         parents,
        #     )
        #     self.repo.create_head(self.head_table, commit, force = True)
        #     self.repo_updated = True
        #     self.repo_push()

    def groups_changed(self, ids, only_meta) -> None:
        if self.course.config.live_submissions_table_split and ids:
            self.update()


class UnifiedLiveSubmissionsTableLabUpdateListener[LabId](
    lab_interfaces.LabUpdateListener
):
    lab: module_course.Course[LabId]
    logger: logging.Logger
    table: live_submissions_table.UnifiedLiveSubmissionsTable

    @functools.cached_property
    def path(self) -> Path:
        return self.course.dir / "unified-live-submissions-table.html"

    @property
    def canvas_path(self) -> PurePosixPath:
        return (
            self.course.config.canvas_grading_path
            / self.course.config.live_submissions_table_unified
        )

    def __init__(self, course: module_course.Course[LabId]):
        """
        Setup the unified live submissions table.
        Request handlers should be set up before calling this method.
        """
        assert course.config.live_submissions_table_split is not None

        self.course = course
        self.logger = self.course.logger

        def tables():
            for lab in self.course.labs.values():
                for listener in lab.update_manager.listeners:
                    if isinstance(listener, LiveSubmissionsTableLabUpdateListener):
                        yield listener.table

        self.table = live_submissions_table.UnifiedLiveSubmissionsTable(
            self.course,
            tables(),
        )

    def update(self):
        canvas_upload(
            path=self.path,
            build=self.table.build,
            canvas_client=self.course.canvas_course,
            canvas_path=self.canvas_path,
            logger=self.logger,
            logging_name="unified live submissions table",
        )

    def groups_changed(self, ids, only_meta):
        if ids and self.table.updated:
            self.update()
