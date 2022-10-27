import csv

header_personnummer = 'Personal identity number'
header_gitlab_username = 'Chalmers GitLab username'
header_name = 'Name'
header_grade = 'Grade'
header_examination_date = 'Examination date'


def report_headers(course):
    def f():
        yield header_personnummer
        yield header_gitlab_username
        yield header_name
        for lab in course.labs.values():
            yield lab.name
        yield header_grade
        yield header_examination_date
    return list(f())

def read_report_skeleton(course, path):
    '''
    Argument path is interpreted relative to course.dir
    '''
    with (course.dir / path).open() as file:
        # Restrict headers.
        reader = csv.DictReader(file, fieldnames = [header_personnummer, header_name], dialect = csv.excel_tab)
        # Ignore header row.
        it = iter(reader)
        next(it)
        return list(it)

def write_report(course, path, entries):
    '''
    Argument path is interpreted relative to course.dir
    '''
    with (course.dir / path).open('w') as file:
        writer = csv.DictWriter(file, report_headers(course), dialect = csv.excel_tab)
        writer.writeheader()
        for entry in entries:
            writer.writerow(entry)

def prepare_requested_entries(course, requested_entries, by_gitlab_username, examination_date = ''):
    '''
    Takes a list of skeleton entries (containing at least a value for header_personnummer)
    and returns a corresponding list of entries filled from by_gitlab_username.

    Arguments:
    * course: Instance of Course.
    * requested_entries:
        The given list of skeleton entries.
        Each entry is a map with a value for header_personnummer.
        If it contains a value for header_name, this is passed along in the result.
    * by_gitlab_username:
        As returned by Course.grading_report_with_summary.
        This method mutates this map by popping used entries.
    * examination_date:
        Value to use for the key header_examination_date.
    '''
    def f(entry):
        personnummer = entry[header_personnummer].replace('-', '')
        canvas_user = course.canvas_course.user_by_sis_id(personnummer)
        if canvas_user is None:
            raise ValueError(f'No Canvas user found for personnumber {personnummer}')

        gitlab_user = course.gitlab_user_by_canvas_id(canvas_user.id)
        if gitlab_user is None:
            raise ValueError(f'No Chalmers GitLab user found Canvas user {canvas_user.name}')

        value = by_gitlab_username.pop(gitlab_user.username, dict())
        name = entry.get(header_name)
        if name is None:
            name = canvas_user.sortable_name
        return {
            header_personnummer: entry[header_personnummer],
            header_gitlab_username: gitlab_user.username,
            header_name: entry[header_name]
        } | course.grading_report_format_value(value) | {
            header_examination_date: examination_date,
        }

    return list(map(f, requested_entries))

def prepare_remaining_entries(course, by_gitlab_username):
    '''
    Returns a list of entries for the given grading report (with summary).
    Typically used on the map remaining after processing the requested entries with prepare_requested_entries.

    Arguments:
    * course: Instance of Course.
    * by_gitlab_username:
        As returned by Course.grading_report_with_summary (and potentially modified by prepare_requested_entries).
    '''
    def f(x):
        (gitlab_username, value) = x
        canvas_user = course.canvas_user_by_gitlab_username.get(gitlab_username)

        return {
            header_personnummer: canvas_user.sis_id if canvas_user else '',
            header_gitlab_username: gitlab_username,
            header_name: canvas_user.sortable_name if canvas_user else '',
        } | course.grading_report_format_value(value) | {
            header_examination_date: '',
        }

    return list(map(f, by_gitlab_username.items()))

def report_course(course, xs, path_extra):
    '''
    Prepare the assignment protocol for this course.

    Arguments:
    * course: Instance of Course.
    * xs:
        List of pairs (requests, filled_out) of paths, interpreted relative to course.dir.
        The first path is an input file:
        a tab-separated CSV file containing requests (at least a column for header_personnummer).
        The second path is an output file:
        a tab-separated CSV file containing the filled out requests.
    * path_extra:
        Path to an output file:
        a tab-separated CSV file containing lab grades for students not appearing in the input files requests.
    '''
    # Make sure all requests are processed.
    for lab in course.labs.values():
        lab.setup_request_handlers()
        lab.parse_response_issues()
        lab.repo_fetch_all()
        lab.parse_request_tags(False)
        lab.process_requests()

    by_gitlab_username = course.grading_report_with_summary()

    for (path_requests, path_filled_out) in xs:
        requested_entries = read_report_skeleton(course, course.dir / path_requests)
        filled_out_entries = prepare_requested_entries(
            course,
            requested_entries,
            by_gitlab_username,
            examination_date = '2022-03-19'
        )
        write_report(course, path_filled_out, filled_out_entries)

    extra_entries = prepare_remaining_entries(course, by_gitlab_username)
    write_report(course, path_extra, extra_entries)

# Example invocation:
from current_course_prelude import c
report_course(c, [('report_empty.csv', 'report_filled_out.csv')], 'report_extra.csv')