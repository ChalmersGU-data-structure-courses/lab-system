import functools
import logging
from pathlib import Path
import shlex

import os

from general import *
import java

logger = logging.getLogger("robograde")

class RobogradeException(Exception):
    pass

class RobogradeFileConflict(RobogradeException):
    def __init__(self, file):
        self.file = file

class RobogradeExecutionError(RobogradeException):
    def __init__(self, errors):
        self.errors = errors

def robograde(dir, robograde_dirs, entrypoint, machine_speed = 1):
    logger.log(logging.INFO, 'Robograding: {}'.format(shlex.quote(str(dir))))

    # Check for class name conflicts.
    for robograde_dir in robograde_dirs:
        with working_dir(robograde_dir):
            files = list(Path('.').rglob('*.class'))
        for file in files:
            if (dir / file).exists():
                raise RobogradeFileConflict(file)

    with tempfile.TemporaryDirectory() as temp_dir:
        # Create policy file.
        policy_file = Path(temp_dir) / 'policy'
        policy_file.write_text(java.policy((robograde_dir.resolve(), [java.permission_all]) for robograde_dir in robograde_dirs))

        cmd = list(java.java_cmd(
            entrypoint,
            args = [str(machine_speed)],
            security_policy = policy_file.resolve(),
            classpath = [dir.resolve()] + [d.resolve() for d in robograde_dirs],
            options = java.java_standard_options(),
        ))
        log_command(logger, cmd)
        process = subprocess.run(cmd, cwd = dir, stdout = subprocess.PIPE, stderr = subprocess.PIPE, encoding = 'utf-8')
        if process.returncode != 0:
            raise RobogradeExecutionError(process.stderr)

        logger.log(logging.DEBUG, 'pregrading output of {}:\n'.format(entrypoint) + process.stdout)
        return process.stdout
