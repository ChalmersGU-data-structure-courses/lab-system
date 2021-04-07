import hashlib
import itertools
import logging
from pathlib import Path
import types

import general
import google_tools.general
from google_tools.documents import Documents
from google_tools.drive import Drive

logger = logging.getLogger('exam.instantiate_template')

def get_seed(secret_salt, version):
    return hashlib.shake_256(bytes(str(version) + '$' + secret_salt, encoding = 'utf-8')).hexdigest(length = 8)

def generate(
    output_dir,
    token,
    exam_id = None,
    solution_id = None,
    questions = dict(),
    secret_salt = 'medium secret',
    student_versions = None,
    solution = False,
    output_types = Drive.mime_types_document.keys(),
    share_dir = None,
    share_url = None,
):
    '''
    Generate exams (or exam solutions) from the template documents with the given ids.

    The exams are stored in output_dir, which needs to exist.
    For element of students, a subfolder of that name will be created with files "exam.SUFFIX" (or "solution.SUFFIX" if solution is true) where SUFFIX is in the collection output_types.

    token is a Goolge OAuth2 token with scopes for drives and documents.

    questions is a collection of pairs of question keys and functions that take a single seed argument and return an object with optional methods
    * replacements(solution)
    * replacements_img(solution)
    returning iterables of key-value pairs.
    In the case of replacements, a key is a string XYZ representing textual occurrences of e.g. {{Q1:XYZ}} in the template and the values are strings that serve as replacements.
    In the case of replacements_img, the keys are image ids in the template and the values are paths to image files that serve as replacements.

    secret_salt should be a different value for each exam.

    Each value in student_versions is a dictionary from question keys to question versions (integers or strings).

    solution specified whether to generate exam instances or solution instances.

    output_types is a list (by suffix) of file types to generate.
    The generated documents are stored as output_path with suffix according to file type appended.

    share_dir and share_url are required if images are to be replaced.
    share_url is the url of a directory (with trailing slash) from which Google Docs will read an uploaded image.
    share_dir is the path to a local directory from which the files in share_url are populated.
    * 
    '''

    filename = 'solution' if solution else 'exam'
    id = solution_id if solution else exam_id

    for student, versions in student_versions.items():
        logger.log(logging.INFO, f'Generating {filename} for student {student} with versions {versions}')

        def f(question, generator):
            x = generator(get_seed(secret_salt, versions[question]))
            y = dict(
                (s, getattr(x, s, lambda solution: [])(solution))
                for s in ['replacements', 'replacements_img']
            )
            return (question, types.SimpleNamespace(**y))

        (output_dir / student).mkdir(exist_ok = True)
        google_tools.general.generate_from_template_document(
            dict(
                (suffix, general.add_suffix(output_dir / student / filename, '.' + suffix))
                for suffix in output_types
            ),
            f'{filename}-{student}',
            token,
            id,
            *google_tools.general.namespaced_replacements(itertools.starmap(f, questions)),
            share_dir = share_dir,
            share_url = share_url)
