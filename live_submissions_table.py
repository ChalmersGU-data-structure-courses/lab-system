import collections
import logging
from pathlib import Path
import types

import dominate

import general
import git_tools
import gitlab_tools
import grading_via_merge_request


logger = logging.getLogger(__name__)

def add_class(element, class_name):
    '''
    Add a class name to an element.
    The element should be an instance of dominate.dom_tag.
    '''
    x = element.attributes.get('class', '')
    element.set_attribute('class', x + ' ' + class_name if x else class_name)

def format_url(text, url):
    '''
    Creates a value of dominate.tags.a from a pair of two strings.
    The first string is the text to display, the second the URL.
    Configure it to open the link a new tab/window.
    '''
    return dominate.tags.a(text, href = url, target = '_blank')

path_data = Path(__file__).parent / 'live-submissions-table'
path_data_default_css = path_data / 'default.css'
path_data_sort_js = path_data / 'sort.js'
path_data_sort_css = path_data / 'sort.css'

def embed_raw(path):
    return dominate.util.raw('\n' + path.read_text())

def embed_css(path):
    return dominate.tags.style(embed_raw(path))

def embed_js(path):
    return dominate.tags.script(embed_raw(path))

# Always have the following columns:
# * date
# * query number
# * group
# * members
# * submission, also vs:
#   - previous
#   - problem
#   - solution
# * message
#
# Optional columns:
# * compilation problems
# * testing output comparison
# * robograding

# For each column, we need the following information:
# * Should this be a sortable column?
#   If so, what should the comparison function be?
# * When should a cell in this column be considered empty?
# * A function that generates the cell content for a given group

class ColumnValue:
    '''
    The column value associated to a group.
    This is relative to a column whose get_value method has produced this instance.
    '''
    def sort_key(self):
        '''
        Return the sort key.
        Only called for sortable columns.
        '''
        raise NotImplementedError()

    def has_content(self):
        '''
        Return a boolean indicating if this cell has displayable content.
        If all cells in a column have no displayable content,
        then the live submissions table will omit the column.
        The default implementation returns True.
        '''
        return True

    def format_cell(self, cell):
        '''
        Fill in content for the given table cell.
        The argument is of type dominate.tags.td.
        You may use context managers to define its elements and attributes:
            with cell:
                dominate.tags.p('a paragraph')
                dominate.tags.p('another paragraph')
        '''
        raise NotImplementedError()

class Column:
    '''
    Required attributes:
    * sortable:
        A boolean indicating if this column is sortable.
        If so, then column values produced by get_value need to have sort_key implemented.
        Set to False by default.
    '''
    sortable = False

    def __init__(self, table):
        '''
        Store the given configuration under self.config.
        Inline its fields as instance attributes.
        '''
        self.table = table

    @property
    def course(self):
        return self.table.course

    @property
    def lab(self):
        return self.table.lab

    @property
    def config(self):
        return self.table.config

    @property
    def logger(self):
        return self.table.logger

    def format_header_cell(self, cell):
        '''
        Fill in content for the given table header cell.
        The argument is of type dominate.tags.td.
        You may use context managers to define its elements and attributes:
            with cell:
                dominate.util.text('Column header')
        '''
        raise NotImplementedError()

    def get_value(self, group):
        '''
        Return the column value (instance of ColumnValue) for
        a given group project (instance of group_GroupProject).
        '''
        raise NotImplementedError()

class CallbackColumnValue(ColumnValue):
    '''
    A column value implementation using a callback function for format_cell.
    Values for sort_key and has_content are given at construction.
    '''
    def __init__(self, sort_key = None, has_content = True, callback = None):
        if sort_key is not None:
            self.sort_key = lambda: sort_key
        self.has_content = lambda: has_content
        self.format_cell = callback if callback is not None else lambda cell: None

class StandardColumnValue(ColumnValue):
    '''A simple column value implementation using just a string-convertible value and a sort key.'''

    def __init__(self, value, key):
        '''
        Arguments:
        * value: A string-convertible value.
        * key: An optional sort key (defaulting to the given value).
        '''
        self.value = value
        self.key = key if key is not None else value

    def sort_key(self):
        '''Returns the specified sort key, or in its absences the value.'''
        return self.key

    def has_content(self):
        '''Checks if the specified value converts to a non-empty string.'''
        return bool(str(self.value))

    def format_cell(self, cell):
        '''Formats the cell with text content (centered) according to the specified value.'''
        with cell:
            dominate.util.text(str(self.value))
            dominate.tags.attr(style = 'text-align: center;')

# TODO: implement deadlines in lab config.
class DateColumn(Column):
    sortable = True

    def format_header_cell(self, cell):
        with cell:
            dominate.util.text('Date')
            dominate.tags.attr(style = 'text-align: center;')

    class Value(ColumnValue):
        def __init__(self, date, late = False):
            self.date = date
            self.late = late

        def sort_key(self):
            return self.date

        def has_content(self):
            return True

        def format_cell(self, cell):
            if self.late:
                add_class(cell, 'problematic')
            with cell:
                with dominate.tags.span():
                    dominate.util.text(self.date.strftime('%b %d, %H:%M'))
                    dominate.tags.attr(title = self.date.strftime('%z (%Z)'))
                    dominate.tags.attr(style = 'text-align: center;')

    def get_value(self, group):
        submission = group.submission_current(deadline = self.config.deadline)
        return DateColumn.Value(submission.date)

class GroupColumn(Column):
    sortable = True

    def format_header_cell(self, cell):
        with cell:
            dominate.tags.attr(style = 'text-align: center;')
            dominate.util.text('Group')

    def get_value(self, group):
        group_config = self.lab.course.config.group
        return StandardColumnValue(
            group_config.id.print(group.id),
            group_config.sort_key(group.id),
        )

class MembersColumn(Column):
    def format_header_cell(self, cell):
        with cell:
            dominate.tags.attr(style = 'text-align: center;')
            dominate.util.text('Members on record')

    class Value(ColumnValue):
        def __init__(self, members, logger):
            '''
            Members is a list of pairs (gitlab_username, canvas_user) where:
            * gitlab_user is a user on Chalmers GitLab (as per gitlab-python),
            * canvas_user is the corresponding user on Canvas (as in the canvas module).
              Can be None if no such user is found.
            '''
            self.members = members
            self.logger = logger

        def has_content(self):
            return bool(self.members)

        def fill_in_member(self, gitlab_user, canvas_user):
            dominate.util.text(gitlab_tools.format_username(gitlab_user))
            if canvas_user is not None:
                dominate.util.text(': ')
                if canvas_user.enrollments:
                    format_url(canvas_user.name, canvas_user.enrollments[0].html_url)
                else:
                    self.logger.warning(general.join_lines([
                        f'Canvas course student {canvas_user.name} (id {canvas_user.id}) is missing an enrollment.',
                        'Please inform the script designer that this case is possible.',
                    ]))
                    dominate.util.text(canvas_user.name)

        def format_cell(self, cell):
            with cell:
                for member in self.members:
                    with dominate.tags.p():
                        self.fill_in_member(*member)

    def get_value(self, group):
        members = [
            (member, self.course.canvas_user_by_gitlab_username.get(member.username))
            for member in group.members
        ]
        members.sort(key = lambda x: str.casefold(x[0].username))
        return MembersColumn.Value(members, self.logger)

class QueryNumberColumn(Column):
    sortable = True

    def format_header_cell(self, cell):
        with cell:
            dominate.tags.attr(style = 'text-align: center;')
            dominate.util.text('#')

    class Value(ColumnValue):
        def __init__(self, number):
            self.number = number

        def sort_key(self):
            return self.number

        def format_cell(self, cell):
            with cell:
                # TODO: make parametrizable in configuration
                dominate.util.text(f'#{self.number + 1}')
                dominate.tags.attr(style = 'text-align: center;')

    def get_value(self, group):
        submissions_with_outcome = group.submissions_with_outcome(deadline = self.config.deadline)
        return QueryNumberColumn.Value(general.ilen(submissions_with_outcome))

class MessageColumn(Column):
    sortable = True

    def format_header_cell(self, cell):
        with cell:
            dominate.util.text('Submission message')

    class Value(ColumnValue):
        def __init__(self, message):
            self.message = message

        def sort_key(self):
            return self.message

        def has_content(self):
            return bool(self.message)

        def format_cell(self, cell):
            with cell:
                if self.message is not None:
                    dominate.tags.pre(self.message)

    def get_value(self, group):
        submission_current = group.submission_current(deadline = self.config.deadline)
        message = git_tools.tag_message(
            submission_current.repo_remote_tag,
            default_to_commit_message = True,
        )
        return MessageColumn.Value(message)

def float_left_and_right(cell, left, right):
    with cell:
        dominate.tags.div(
            left + right,
            style = 'white-space: pre; max-height: 0; visibility: hidden;',
        )
        dominate.util.text(left)
        dominate.tags.span(
            right,
            style = 'float: right; white-space: pre;',
        )

class SubmissionFilesColumn(Column):
    def format_header_cell(self, cell):
        float_left_and_right(cell, 'Submission', ' vs:')

    class Value(ColumnValue):
        def __init__(self, linked_name, linked_grading_response):
            self.linked_name = linked_name
            self.linked_grading_response = linked_grading_response

        def format_cell(self, cell):
            with cell:
                a = format_url(*self.linked_name)
                add_class(a, 'block')
                a = format_url(*self.linked_grading_response)
                add_class(a, 'block')

    def get_value(self, group):
        submission = group.submission_current(deadline = self.config.deadline)

        response_key = self.lab.submission_handler.review_response_key
        if response_key is None:
            linked_grading_response = None
        else:
            def f():
                try:
                    return self.lab.review_template_issue.description
                except AttributeError:
                    return ''

            if self.lab.config.grading_via_merge_request:
                linked_grading_response = (
                    'review merge request',
                    group.grading_via_merge_request.merge_request.web_url,
                )
            else:
                linked_grading_response = ('open issue', gitlab_tools.url_issues_new(
                    group.project.get,
                    title = self.lab.submission_handler.response_titles[response_key].print({
                        'tag': submission.request_name,
                        'outcome': self.course.config.grading_response_default_outcome,
                    }),
                    description = group.append_mentions(f()),
                ))

        return SubmissionFilesColumn.Value(
            (submission.request_name, gitlab_tools.url_tree(group.project.get, submission.request_name)),
            linked_grading_response,
        )

class SubmissionDiffColumnValue(ColumnValue):
    def __init__(self, linked_name, linked_grader = None, is_same = False):
        self.linked_name = linked_name
        self.linked_grader = linked_grader
        self.is_same = is_same

    def has_content(self):
        return self.linked_name is not None

    def format_cell(self, cell):
        add_class(cell, 'extension-column')
        if self.has_content():
            with cell:
                with dominate.tags.p():
                    format_url(*self.linked_name)
                    if self.is_same:
                        dominate.tags.attr(_class = 'grayed-out')
                if self.is_same:
                    with dominate.tags.p():
                        dominate.util.text('identical')
                if self.linked_grader is not None:
                    with dominate.tags.p():
                        dominate.util.text('graded by ')
                        format_url(*self.linked_grader)

class SubmissionDiffPreviousColumn(Column):
    def format_header_cell(self, cell):
        add_class(cell, 'extension-column')
        with cell:
            dominate.util.text('previous..')

    def get_value(self, group):
        submissions_with_outcome = list(group.submissions_with_outcome(deadline = self.config.deadline))
        if not submissions_with_outcome:
            return SubmissionDiffColumnValue(None)

        submission_current = group.submission_current(deadline = self.config.deadline)
        submission_previous = submissions_with_outcome[-1]
        return SubmissionDiffColumnValue(
            (submission_previous.request_name + '..', gitlab_tools.url_compare(
                self.lab.grading_project.get,
                submission_previous.repo_tag(),
                submission_current.repo_tag(),
            )),
            (submission_previous.informal_grader_name, submission_previous.outcome_issue.web_url),
            is_same = False,  # TODO: implement
        )

class SubmissionDiffOfficialColumn(Column):
    def __init__(self, config, branch):
        super().__init__(config)
        self.branch = branch

    def format_header_cell(self, cell):
        add_class(cell, 'extension-column')
        with cell:
            dominate.util.text(self.branch.name)

    def get_value(self, group):
        submission_current = group.submission_current(deadline = self.config.deadline)
        return SubmissionDiffColumnValue(
            (self.branch.name + '..', gitlab_tools.url_compare(
                self.lab.grading_project.get,
                self.branch.name,
                submission_current.repo_tag(),
            )),
            is_same = False,  # TODO: implement
        )

class SubmissionDiffProblemColumn(SubmissionDiffOfficialColumn):
    def __init__(self, config):
        super().__init__(config, config.lab.head_problem)

class SubmissionDiffSolutionColumn(SubmissionDiffOfficialColumn):
    def __init__(self, config):
        super().__init__(config, config.lab.head_solution)

standard_columns_before = {
    'date': DateColumn,
    'query-number': QueryNumberColumn,
    'group': GroupColumn,
    'members': MembersColumn,
    'submission': SubmissionFilesColumn,
    'submission-after-previous': SubmissionDiffPreviousColumn,
    'submission-after-problem': SubmissionDiffProblemColumn,
    'submission-after-solution': SubmissionDiffSolutionColumn,
}

standard_columns_after = {
    'message': MessageColumn,
}

def with_standard_columns(columns = dict()):
    return dict([
        *standard_columns_before.items(),
        *columns.items(),
        *standard_columns_after.items(),
    ])

standard_columns = with_standard_columns()

# class TestOutputDiffColumnValue(ColumnValue):
#     def __init__(self, name = None, link = None, similarity = 0):
#         '''
#         Arguments:
#         * Name: The name of the submission to compare against.
#         * Link: The link to the diff on Chalmers GitLab.
#         * similarity:
#             A number in [0, 1] indicating how similar the submission is
#             compared against to the source the diff is comparing against.
#             A value of 1 means identical.
#             A value of 0 means fully different.
#             Identical diffs may have their link omitted in the formatted cell.
#             This is because GitLab is not able to show empty diffs.
#         '''
#         self.name = name
#         self.link = link
#         self.different = different

#     def format_cell(self, cell):
#         with cell:
#             with dominate.tags.a():
#                 text(self.name)
#                 dominate.tags.attr(href = self.link)
#                 if self.similarity == 1:
#                     dominate.tags.attr(_class = 'grayed-out')


Config = collections.namedtuple(
    'Config',
    ['deadline', 'sort_order'],
    defaults = [None, ['query-number', 'group', 'date']],
)
Config.__doc__ = '''
    Configuration for a live submissions table.
    * deadline:
        The deadline to which to restrict submissions to.
        An instance of datetime.datetime.
        None if all submissions are to be taken into account.
    * sort_order:
        A list of column names.
        Determines the initial sort order.
        This is according to the lexicographic ordering
        of the column values specified by the given list.
        Unknown column names are currently ignored,
        but this feature should not be relied upon.
    '''

class LiveSubmissionsTable:
    def __init__(
        self,
        lab,
        config,
        column_types = standard_columns,
        logger = logging.getLogger(__name__),
    ):
        self.lab = lab
        self.course = lab.course
        self.config = config
        self.logger = logger

        self.columns = {
            column_name: column_type(self)
            for (column_name, column_type) in column_types.items()
        }
        self.group_rows = dict()
        self.need_push = False

    def update_row(self, group_id):
        '''
        Update the row in this live submissions table for a given group id.
        If the group has no current submission, the row is deleted.
        This method can update the local grading repository, so a push is
        required afterwards before building or uploading the live submissions table.
        '''
        group = self.lab.student_group(group_id)
        logger.info(f'updating row for {group.name} in live submissions table')
        if group.submission_current(deadline = self.config.deadline):
            self.group_rows[group.id] = {
                column_name: column.get_value(group)
                for (column_name, column) in self.columns.items()
            }
        else:
            self.group_rows.pop(group.id, None)

    def update_rows(self, group_ids = None):
        '''
        Update rows in this live submissions table for given group ids.
        If the argument group_ids is not given, all rows are updated.
        '''
        group_ids = self.lab.normalize_group_ids(group_ids)
        for group_id in group_ids:
            self.update_row(group_id)

    def build(self, file, group_ids = None):
        '''
        Build the live submissions table.

        Before calling this method, all required group rows need to have been updated.
        As this can update the local grading repository, a push is required
        before building or uploading the live submissions table.

        Arguments:
        * file:
            The filename the output HTML file should be written to.
            The generated HTML file is self-contained and only contains absolute links.
        * group_ids:
            An optional iterable of group ids to produce rows for.
            Currently, only group with a current submission
            for the specified deadline are supported.
            (Each supplied column type is responsible for this.)
        '''
        logger.info('building live submissions table...')

        # Compute the list of group ids with live submissions.
        if group_ids:
            group_ids = list(group_ids)
        else:
            group_ids = list(self.lab.groups_with_live_submissions(deadline = self.config.deadline))
        logger.debug(f'building live submissions table for the following groups: {group_ids}')

        # Make sure all needed group rows are built.
        for group_id in group_ids:
            if not group_id in self.group_rows:
                group = self.lab.student_group(group_id)
                raise ValueError(f'live submissions table misses row for {group.name}')

        # Compute the columns (with column values) for these submissions.
        # We omit empty columns.
        def f():
            for (name, column) in self.columns.items():
                r = types.SimpleNamespace()
                r.values = dict(
                    (group_id, column.get_value(self.lab.student_group(group_id)))
                    for group_id in group_ids
                )
                if any(value.has_content() for value in r.values.values()):
                    if column.sortable:
                        r.canonical_sort_keys = general.canonical_keys(
                            group_ids,
                            lambda group_id: r.values[group_id].sort_key()
                        )
                    yield (name, r)
        column_data = dict(f())

        # Pre-sort the list of group ids with live submissions according to the given sort order.
        sort_order = list(filter(
            lambda column_name: column_name in column_data,
            self.config.sort_order,
        ))
        group_ids.sort(key = lambda group_id: tuple(
            column_data[name].values[group_id].sort_key()
            for name in sort_order
        ))

        # Build the HTML document.
        doc = dominate.document()
        doc.title = f'Grading requests: {self.lab.name_full}'
        with doc.head:
            dominate.tags.meta(charset = 'utf-8')
            # Make it fit into the Canvas style by using the same fonts (font source?).
            dominate.tags.link(
                rel = 'preconnect',
                href = 'https://fonts.gstatic.com/',
                crossorigin = 'anonymous',
            )
            dominate.tags.link(
                rel = 'stylesheet',
                media = 'screen',
                href = (
                    'https://du11hjcvx0uqb.cloudfront.net'
                    '/dist/brandable_css/no_variables/bundles/lato_extended-f5a83bde37.css'
                ),
            )
            embed_css(path_data_default_css)
            embed_css(path_data_sort_css)
            embed_js(path_data_sort_js)

        with doc.body:
            with dominate.tags.table(id = 'results'):
                with dominate.tags.thead():
                    for name in column_data.keys():
                        column = self.columns[name]
                        cell = dominate.tags.th()
                        add_class(cell, name)
                        if column.sortable:
                            add_class(cell, 'sortable')
                            # want to write: is_prefix([name], sort_order)
                            if [name] == sort_order[:1]:
                                add_class(cell, 'sortable-order-asc')
                        column.format_header_cell(cell)
                with dominate.tags.tbody():
                    for group_id in group_ids:
                        logger.debug(f'processing {self.lab.student_group(group_id).name}')
                        with dominate.tags.tr():
                            for (name, data) in column_data.items():
                                column = self.columns[name]
                                cell = dominate.tags.td()
                                cell.is_pretty = False
                                add_class(cell, name)
                                if column.sortable:
                                    cell['data-sort-key'] = str(data.canonical_sort_keys[group_id])
                                data.values[group_id].format_cell(cell)

        file.write_text(doc.render(pretty = True))
        logger.info('building live submissions table: done')
