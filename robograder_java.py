import logging
from pathlib import Path
import shlex
import subprocess
import tempfile
import types

import check_symlinks
import course_basics
import general
import java_tools
import markdown
from this_dir import this_dir

# Root of the code repository.
code_root = this_dir.parent

logger = logging.getLogger(__name__)

class SubmissionHandlingExceptionForwarder(course_basics.SubmissionHandlingException):
    def __init__(self, e):
        self.e = e
        self.__str__ = e.__str__
        self.markdown = e.markdown

class SymlinkException(SubmissionHandlingExceptionForwarder):
    pass

class CompileException(course_basics.SubmissionHandlingException):
    def __init__(self, e):
        self.e = e

    def markdown(self):
        return general.join_lines([
            'There were compilation errors:'
        ]) + markdown.escape_code_block(self.e.compile_errors)

    def __str__(self):
        return self.e.compile_errors

class Compiler(course_basics.Compiler):
    # For now: ignoring bin.
    # TODO: use bin as target directory.
    def compile(self, src, bin):
        try:
            check_symlinks.check_self_contained(src)
            java_tools.compile_java_dir(src, detect_enc = True)
        except check_symlinks.SymlinkException as e:
            raise SymlinkException(e)
        except java_tools.CompileError as e:
            raise CompileException(e)

class RobograderException(course_basics.SubmissionHandlingException):
    pass

class FileConflict(RobograderException):
    def __init__(self, file):
        self.file = file

    def markdown(self):
        return general.join_lines([
            'I could not robograde your submission because the compiled file',
        ]) + markdown.escape_code_block(self.file) + general.join_lines([
            'conflicts with files I use for testing.'
        ])

class ExecutionError(RobograderException):
    def __init__(self, errors):
        self.errors = errors

    def markdown(self):
        return general.join_lines([
            'Oops, you broke the robograder!',
            '',
            'I encountered a problem while testing your submission.',
            'This could be a problem with myself (a robo-bug) or with your code '
            '(unexpected changes to class or methods signatures).',
            'In the latter case, you might elucidate the cause from the below error message.',
            'In the former case, please tell me designers!',
        ]) + markdown.escape_code_block(self.errors)

class Robograder:
    def setup(self, lab, src, bin = None):
        print('setting up')

        # For now.
        bin = src

        self.machine_speed = lab.course.config.robograder_machine_speed
        self.path_lib = code_root / 'Other' / 'robograding'
        self.path_robograder = lab.config.path_source / 'pregrade'
        self.classpath = [
            self.path_lib,
            self.path_robograder
        ]
        self.classpath_resolved = [dir.resolve() for dir in self.classpath]
        self.entrypoint = 'Robograder'

        logger.info('Compiling robograder {}'.format(shlex.quote(str(self.path_robograder))))
        java_tools.compile_java_dir(
            self.path_robograder,
            force_recompile = True,
            classpath = [bin.resolve()] + self.classpath_resolved
        )

    def run(self, src, bin = None):
        # For now.
        bin = src

        for file in src.iterdir():
            print(file)

        # Check for class name conflicts.
        for dir in self.classpath_resolved:
            with general.working_dir(dir):
                files = list(Path('.').rglob('*.class'))
            for file in files:
                if (bin / file).exists():
                    raise FileConflict(file)

        with tempfile.TemporaryDirectory() as temp_dir:
            # Create policy file.
            policy_file = Path(temp_dir) / 'policy'
            policy_file.write_text(java_tools.policy(
                (dir, [java_tools.permission_all])
                for dir in self.classpath_resolved
            ))

            cmd = list(java_tools.java_cmd(
                self.entrypoint,
                args = [str(self.machine_speed)],
                security_policy = policy_file.resolve(),
                classpath = [bin.resolve()] + self.classpath_resolved,
                options = java_tools.java_standard_options(),
            ))
            general.log_command(logger, cmd)
            process = subprocess.run(
                cmd,
                cwd = bin,
                stdout = subprocess.PIPE,
                stderr = subprocess.PIPE,
                encoding = 'utf-8'
            )
            if process.returncode != 0:
                raise ExecutionError(process.stderr)

            logger.debug('pregrading output of {}:\n'.format(self.entrypoint) + process.stdout)
            return process.stdout

class StudentCallableRobograder(course_basics.StudentCallableRobograder, Robograder):
    def __init__(self):
        super().__init__()
