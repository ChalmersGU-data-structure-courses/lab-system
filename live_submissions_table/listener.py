import contextlib
import functools
import logging
import random

import util.path

import lab
import lab_interfaces
import live_submissions_table


class LiveSubmissionsTableLabUpdateListener[LabId, GroupId](
    lab_interfaces.LabUpdateListener[GroupId]
):
    lab: lab.Lab[LabId, GroupId]
    logger: logging.Logger
    table: live_submissions_table.LiveSubmissionsTable

    @property
    def course(self):
        return self.lab.course

    @functools.cached_property
    def path(self):
        return self.lab.dir / "live-submissions-table.html"

    @functools.cached_property
    def path_staging(self):
        return util.path.add_suffix(self.path, ".staging")

    def __init__(self, lab_: lab.Lab, deadline=None):
        """
        Setup the live submissions table.
        Takes an optional deadline parameter for limiting submissions to include.
        If not set, we use self.deadline.
        Request handlers should be set up before calling this method.
        """
        self.lab = lab_
        self.logger = self.lab.logger

        if deadline is None:
            deadline = self.lab.deadline
        self.table = live_submissions_table.LiveSubmissionsTable(
            self,
            config=live_submissions_table.Config(deadline=deadline),
            column_types=self.lab.submission_handler.grading_columns,
        )

    @contextlib.contextmanager
    def staging_manager(self):
        try:
            yield
        finally:
            self.path_staging.unlink(missing_ok=True)

    def update(self):
        """
        Updates the live submissions table on Canvas.
        Before calling this method, all group rows in the
        live submissions table need to have been updated.
        """
        self.logger.info("Updating live submissions table")
        with self.staging_manager():
            self.table.build(self.path_staging, group_ids=self.lab.groups.keys())
            if util.path.file_content_eq(
                self.path_staging,
                self.path,
                missing_ok_b=True,
            ):
                self.logger.debug(
                    "Live submissions table has not changed,"
                    " skipping upload to Canvas."
                )
                self.path_staging.unlink()
            else:
                self.logger.info("Posting live submissions table to Canvas")
                target = self.lab.config.live_submissions_table_canvas_path
                folder = self.course.canvas_course.get_folder_by_path(target.parent)
                # self.course.canvas_course.post_file(
                #     self.file_live_submissions_table_staging,
                #     folder.id,
                #     target.name,
                # )
                # Workaround for https://github.com/instructure/canvas-lms/issues/2309:
                with util.path.temp_file() as path:
                    data = self.path_staging.read_text()
                    data = data + "<!-- " + str(random.randbytes(16)) + " -->"
                    path.write_text(data)
                    self.course.canvas_course.post_file(path, folder.id, target.name)
                self.path_staging.replace(self.path)

    def groups_changed_preparation(self, ids: list[GroupId]) -> None:
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

    def groups_changed(self, ids: list[GroupId]) -> None:
        if ids:
            self.update()
