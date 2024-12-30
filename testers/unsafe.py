#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
import logging
from pathlib import Path

import testers.general
import testers.podman


logger = logging.getLogger(__name__)


class LabTester(testers.general.LabTester):
    """
    A class for unsafe tests, designed to be compatible with testers.podman.LabTester.

    The lab directory contains a file 'tests.py'.
    This is a self-contained Python script specifying
        tests : Dict[str, Test].

    Additionally, the lab may contain a subdirectory 'test'.
    Its content is overlaid on top of each submission to be tested.
    """

    TestSpec = testers.podman.Test
    needs_writable_sub_dir = True

    def run_test(
        self,
        dir_out: Path,
        dir_src: Path,
        name: str,
        test: testers.podman.Test,
        dir_bin: Path | None = None,
    ):
        """
        See testers.general.LabTester.run_test.
        We produce the files according to testers.general.LabTester.record.
        """
        logger.debug(f"Running test {name}.")
        self.record_process(
            dir_out=dir_out,
            args=test.command_line,
            input=test.input,
            timeout=test.timeout,
            cwd=dir_src,
            env=testers.general.test_env(test),
        )


if __name__ == "__main__":
    testers.general.cli(LabTester)
