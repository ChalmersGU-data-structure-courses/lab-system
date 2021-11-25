import collections
import dominate
import logging
from pathlib import Path
import types

import general
import git_tools
import gitlab_tools

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

Config = collections.namedtuple(
    'Config',
    ['course', 'lab', 'deadline', 'logger'],
)
Config.__doc__ = '''
    Configuration and data sources for a live submissions table.
    * course: The relevant course instance (course.Course).
    * lab: The relevant lab instance (lab.Lab).
    * deadline:
        The deadline to which to restrict submissions to.
        An instance of datetime.datetime.
        None if all submissions are to be taken into account.
    '''

def build_config(lab, deadline = None, logger = logger):
    '''Smart constructor for an instance of Config.'''
    return Config(
        course = lab.course,
        lab = lab,
        deadline = deadline,
        logger = logger,
    )


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

    def __init__(self, config):
        '''
        Store the given configuration under self.config.
        Inline its fields as instance attributes.
        '''
        self.config = config
        for field in Config._fields:
            setattr(self, field, config._asdict()[field])

        self.sortable = False

    def format_header_cell(self, cell):
        '''
        Fill in content for the given table header cell.
        The argument is of type dominate.tags.td.
        You may use context managers to define its elements and attributes:
            with cell:
                dominate.util.text('Column header')
        '''
        raise NotImplementedError()

    def get_value(self, group_id):
        '''
        Return the column value for a given group_id.
        The default implementation returns the instance of GroupProject for group_id
        in the lab this object has been initialized with.
        '''
        return self.lab.student_group(group_id)


class StandardColumnValue(ColumnValue):
    '''A simple column value implementation using just a string-convertible value and a sort key.'''

    def __init__(self, value, key):
        '''
        Arguments:
        * value: A string-convertible value.
        * key: An optional sort key (defaulting to the given value).
        '''
        self.value = value
        self.key = key if key != None else value

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
    def __init__(self, config):
        super().__init__(config)
        self.sortable = True

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

    def get_value(self, group_id):
        group = super().get_value(group_id)
        submission = group.submission_current(deadline = self.deadline)
        return DateColumn.Value(submission.date)


class GroupColumn(Column):
    def __init__(self, lab):
        super().__init__(lab)
        self.sortable = True

    def format_header_cell(self, cell):
        with cell:
            dominate.tags.attr(style = 'text-align: center;')
            dominate.util.text('Group')

    def get_value(self, group_id):
        group_config = self.lab.course.config.group
        return StandardColumnValue(
            group_config.id.print(group_id),
            group_config.sort_key(group_id),
        )


class MembersColumn(Column):
    def __init__(self, config):
        super().__init__(config)

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
            if canvas_user != None:
                dominate.util.text(': ')
                if canvas_user.enrollments:
                    format_url(canvas_user.name, canvas_user.enrollments[0].html_url)
                else:
                    self.logger.warn(general.join_lines([
                        f'Canvas course student {canvas_user.name} (id {canvas_user.id}) is missing an enrollment.',
                        'Please inform the script designer that this case is possible.',
                    ]))
                    dominate.util.text(canvas_user.name)

        def format_cell(self, cell):
            with cell:
                for member in self.members:
                    with dominate.tags.p():
                        self.fill_in_member(*member)

    def get_value(self, group_id):
        group = super().get_value(group_id)
        members = [
            (member, self.course.canvas_user_by_gitlab_username.get(member.username))
            for member in group.members
        ]
        members.sort(key = lambda x: str.casefold(x[0].username))
        return MembersColumn.Value(members, self.logger)


# TODO: implement deadlines in lab config.
class QueryNumberColumn(Column):
    def __init__(self, config):
        super().__init__(config)
        self.sortable = True

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

    def get_value(self, group_id):
        group = super().get_value(group_id)
        submissions_with_outcome = group.submissions_with_outcome(deadline = self.deadline)
        return QueryNumberColumn.Value(general.ilen(submissions_with_outcome))


class MessageColumn(Column):
    def __init__(self, config):
        super().__init__(config)
        self.sortable = True

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
                if self.message != None:
                    dominate.tags.pre(self.message)

    def get_value(self, group_id):
        group = super().get_value(group_id)
        submission_current = group.submission_current(deadline = self.deadline)
        message = git_tools.tag_message(
            submission_current.repo_remote_tag,
            default_to_commit_message = True
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
    def __init__(self, config):
        super().__init__(config)
        self.sortable = False

    def format_header_cell(self, cell):
        float_left_and_right(cell, 'Submission', ' vs:')

    class Value(ColumnValue):
        def __init__(self, linked_name, linked_open_grading_issue):
            self.linked_name = linked_name
            self.linked_open_grading_issue = linked_open_grading_issue

        def format_cell(self, cell):
            with cell:
                with dominate.tags.p():
                    format_url(*self.linked_name)
                with dominate.tags.p():
                    format_url(*self.linked_open_grading_issue)

    def get_value(self, group_id):
        group = super().get_value(group_id)
        submission = group.submission_current(deadline = self.deadline)

        response_key = self.lab.submission_handler.review_response_key
        if response_key == None:
            linked_open_grading_issue = None
        else:
            def f():
                try:
                    return self.lab.grading_template_issue.description
                except AttributeError:
                    return ''

            linked_open_grading_issue = ('open issue', gitlab_tools.url_issues_new(
                group.project.get,
                title = self.lab.submission_handler.response_titles[response_key].print({
                    'tag': submission.request_name,
                    'outcome': self.course.config.grading_response_default_outcome,
                }),
                description = group.append_mentions(f()),
            ))

        return SubmissionFilesColumn.Value(
            (submission.request_name, gitlab_tools.url_tree(group.project.get, submission.request_name)),
            linked_open_grading_issue,
        )


class SubmissionDiffColumnValue(ColumnValue):
    def __init__(self, linked_name, linked_grader = None, is_same = False):
        self.linked_name = linked_name
        self.linked_grader = linked_grader
        self.is_same = is_same

    def has_content(self):
        return self.linked_name != None

    def format_cell(self, cell):
        if self.has_content():
            add_class(cell, 'extension-column')
            with cell:
                with dominate.tags.p():
                    format_url(*self.linked_name)
                    if self.is_same:
                        dominate.tags.attr(_class = 'grayed-out')
                if self.is_same:
                    with dominate.tags.p():
                        dominate.util.text('identical')
                if self.linked_grader != None:
                    with dominate.tags.p():
                        dominate.util.text('graded by ')
                        format_url(*self.linked_grader)

class SubmissionDiffPreviousColumn(Column):
    def __init__(self, config):
        super().__init__(config)
        self.sortable = False

    def format_header_cell(self, cell):
        add_class(cell, 'extension-column')
        with cell:
            dominate.util.text('previous..')

    def get_value(self, group_id):
        group = super().get_value(group_id)
        submissions_with_outcome = list(group.submissions_with_outcome(deadline = self.deadline))
        if not submissions_with_outcome:
            return SubmissionDiffColumnValue(None)

        submission_current = group.submission_current(deadline = self.deadline)
        submission_previous = submissions_with_outcome[-1]
        tag_after = submission_current.repo_tag_after_create(
            submission_previous.request_name,
            submission_previous.repo_remote_commit
        )
        return SubmissionDiffColumnValue(
            (submission_previous.request_name + '..', gitlab_tools.url_compare(
                self.lab.grading_project.get,
                submission_previous.repo_tag(),
                tag_after.name,
            )),
            (submission_previous.informal_grader_name, submission_previous.outcome_issue.web_url),
            is_same = False, # TODO: implement
        )

class SubmissionDiffOfficialColumn(Column):
    def __init__(self, config, branch):
        super().__init__(config)
        self.branch = branch
        self.sortable = False

    def format_header_cell(self, cell):
        add_class(cell, 'extension-column')
        with cell:
            dominate.util.text(self.branch.name)

    def get_value(self, group_id):
        group = super().get_value(group_id)
        submission_current = group.submission_current(deadline = self.deadline)
        tag_after = submission_current.repo_tag_after_create(
            self.branch.name,
            self.branch,
        )
        return SubmissionDiffColumnValue(
            (self.branch.name + '..', gitlab_tools.url_compare(
                self.lab.grading_project.get,
                self.branch.name,
                tag_after.name,
            )),
            is_same = False, # TODO: implement
        )

class SubmissionDiffProblemColumn(SubmissionDiffOfficialColumn):
    def __init__(self, config):
        super().__init__(config, config.lab.head_problem)

class SubmissionDiffSolutionColumn(SubmissionDiffOfficialColumn):
    def __init__(self, config):
        super().__init__(config, config.lab.head_solution)


standard_columns = {
    'date': DateColumn,
    'query-number': QueryNumberColumn,
    'group': GroupColumn,
    'members': MembersColumn,
    'submission': SubmissionFilesColumn,
    'submission-after-previous':SubmissionDiffPreviousColumn,
    'submission-after-problem': SubmissionDiffProblemColumn,
    'submission-after-solution': SubmissionDiffSolutionColumn,
    'message': MessageColumn,
}

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

class LiveSubmissionsTable:
    def __init__(self, lab, logger = logging.getLogger(__name__)):
        self.lab = lab
        self.course = lab.course
        self.config = lab.course.config
        self.logger = logger

    def build(
        self,
        out,
        deadline = None,
        columns = standard_columns,
        sort_order = ['query-number', 'group', 'date'],
    ):
        logger.info('building live submissions table...')
        config = build_config(self.lab, deadline, logger)

        # Compute the list of group ids with live submissions.
        def f():
            for group_id in self.course.groups:
                group = self.lab.student_group(group_id)
                if group.submission_current(deadline = deadline) != None:
                    yield group_id
        group_ids = list(f())

        # Compute the columns (with column values) for these submissions.
        def f():
            for (column_name, column_type) in columns.items():
                r = types.SimpleNamespace()
                r.column = column_type(config)
                r.values = dict((group_id, r.column.get_value(group_id)) for group_id in group_ids)
                if any(value.has_content() for value in r.values.values()):
                    if r.column.sortable:
                        r.canonical_sort_keys = general.canonical_keys(
                            group_ids,
                            lambda group_id: r.values[group_id].sort_key()
                        )
                    yield (column_name, r)
        column_data = dict(f())

        # Pre-sort the list of group ids with live submissions according to the given sort order.
        sort_order = list(filter(lambda column_name: column_name in column_data, sort_order))
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
                href = 'https://du11hjcvx0uqb.cloudfront.net/dist/brandable_css/no_variables/bundles/lato_extended-f5a83bde37.css'
            )
            embed_css(path_data_default_css)
            embed_css(path_data_sort_css)
            embed_js(path_data_sort_js)

        with doc.body:
            with dominate.tags.table(id = 'results'):
                with dominate.tags.thead():
                    for (name, data) in column_data.items():
                        cell = dominate.tags.th()
                        add_class(cell, name)
                        if data.column.sortable:
                            add_class(cell, 'sortable')
                        data.column.format_header_cell(cell)
                with dominate.tags.tbody():
                    for group_id in group_ids:
                        with dominate.tags.tr():
                            for (name, data) in column_data.items():
                                cell = dominate.tags.td()
                                cell.is_pretty = False
                                add_class(cell, name)
                                if data.column.sortable:
                                    cell['data-sort-key'] = str(data.canonical_sort_keys[group_id])
                                data.values[group_id].format_cell(cell)

        out.write_text(doc.render(pretty = True))
        logger.info('building live submissions table: done')
