import logging
import shlex
import tempfile

import check_symlinks
from course_basics import SubmissionHandlingException
import general
import java
import markdown
import robograder
from this_dir import this_dir

# Root of the code repository.
code_root = this_dir.parent

logger = logging.getLogger(__name__)

def with_base(instance, base):
    class ExtraBase(instance.__class__, base):
        pass

    instance.__class__ = ExtraBase

#class SymlinkException(SymlinkException, SubmissionHandlingException):
#    pass
#
#class CompileException(CompileError, SubmissionHandlingException):
#    def __init__(self, e):
#        self.e = e
#
#    def markdown(self):
#        return markdown.escape_code_block(self.e.compile_errors)
#
#    def __str__(self):
#        return self.e.compile_errors

def compile(src, bin):
    # For now.
    # TODO: use bin as target directory.
    bin = src

    try:
        check_symlinks.check_self_contained(src)
        java.compile_java_dir(src, detect_enc = True)
    except check_symlinks.SymlinkException as e:
        raise with_base(e, SubmissionHandlingException.__class__)#SymlinkException(e)
    except java.CompileError as e:
        raise with_base(e, SubmissionHandlingException.__class__) ##CompileException(e)

class RobograderException(SubmissionHandlingException):
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
            'This could be a problem with myself (a robo-bug) or with your code (unexpected changes to class or methods signatures).',
            'In the latter case, you might elucidate the cause from the below error message.',
            'In the former case, please tell me designers!',
        ]) + markdown.escape_code_block(self.errors)

class Robograder:
    def __init__(self, path_lab_source, machine_speed):
        self.path_lab_source = path_lab_source
        self.machine_speed = machine_speed

        self.path_lib = code_root / 'Other' / 'robograding'
        self.path_robograder = path_lab_source / 'pregrade'

        self.classpath = [
            self.path_lib,
            self.path_robograder
        ]
        self.classpath_resolved = [dir.resolve() for dir in self.classpath]
        self.entrypoint = 'Robograder'

    def setup(self, src, bin):
        # For now.
        bin = src

        logger.info('Compiling robograder {}'.format(shlex.quote(str(self.path_robograder))))
        java.compile_java_dir(
            self.path_robograder,
            force_recompile = True,
            classpath = [bin.resolve()] + self.classpath_resolved
        )

    def run(self, src, bin):
        # For now.
        bin = src

        # Check for class name conflicts.
        for dir in classpath:
            with working_dir(dir):
                files = list(Path('.').rglob('*.class'))
            for file in files:
                if (bin / file).exists():
                    raise robograder.FileConflict(file)

        with tempfile.TemporaryDirectory() as temp_dir:
            # Create policy file.
            policy_file = Path(temp_dir) / 'policy'
            policy_file.write_text(java.policy((dir.resolve(), [java.permission_all]) for dir in classpath))

            cmd = list(java.java_cmd(
                self.entrypoint,
                args = [str(self.machine_speed)],
                security_policy = policy_file.resolve(),
                classpath = [bin.resolve()] + self.classpath_resolved,
                options = java.java_standard_options(),
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
                raise robograder.ExecutionError(process.stderr)

            logger.debug('pregrading output of {}:\n'.format(entrypoint) + process.stdout)
            return process.stdout
