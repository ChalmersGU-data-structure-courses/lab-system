import csv
import random

def allocate_versions(n, num_versions, r):
    '''
    Randomly generate a list of n versions [0, num_versions). 
    r is an instance of random.Random.
    Make sure that every version occurs approximately equally often.
    '''

    versions = [num_versions * i // n for i in range(n)]
    r.shuffle(versions)
    return versions

def allocate(students, num_versions, seed = None):
    '''
    Randomly assign sequential ids to students and allocate question versions to students.
    student is a collections of students.
    num_versions is a dictionary sending questions to the total number of versions.
    Assigns a random sequential id, formatted as sortable strings with leading zeroes, to every student and returns a dictionary mapping ids to pairs of students and a dictionary from questions to versions in the range specified by the total number of versions for that question.
    '''

    r = random.Random(seed)
    students_shuffled = list(students)
    r.shuffle(students_shuffled)

    versions = dict(
        (question, allocate_versions(len(students), num_versions, r))
        for question, num_versions in num_versions.items()
    )
    return dict(
        (id, (student, dict(
            (question, versions[question][id])
            for question in num_versions
        )))
        for (id, student) in enumerate(students_shuffled)
    )

def read(path):
    with path.open() as file:
        reader = csv.DictReader(file)
        def f(row):
            id = int(row.pop('id'))
            student = row.pop('student')
            row.pop('name', None)
            return (id, (student, dict((question, int(version)) for question, version in row.items())))
        return dict(map(f, reader))

def write(path, student_versions, lookup_name = None):
    '''
    Only works well if there is at least one student.
    '''
    questions = next(iter(student_versions.values()), dict())[1].keys()

    def fieldnames():
        yield 'id'
        yield 'student'
        if lookup_name:
            yield 'name'
        yield from list(questions)

    def row_values(id, v):
        (student, versions) = v
        yield ('id', id)
        yield ('student', student)
        if lookup_name:
            yield ('name', lookup_name(student))
        yield from versions.items()

    with path.open('w') as file:
        writer = csv.DictWriter(file, fieldnames = list(fieldnames()))
        writer.writeheader()
        for x in student_versions.items():
            writer.writerow(dict(row_values(*x)))
