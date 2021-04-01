# Special import for git python.
import os
os.environ['GIT_PYTHON_TRACE'] = '1'
import git

import collections
import dateutil.parser as date_parser
import functools
import gitlab
import gspread
import logging
import operator
from pathlib import Path, PurePosixPath

import canvas
from general import *

logger = logging.getLogger('course')

#===============================================================================
# Git tools

def boolean(x):
    return 'true' if x else 'false'

with_refs = lambda s: 'refs/{}'.format(s)
with_heads = lambda s: 'heads/{}'.format(s)
with_tags = lambda s: 'tags/{}'.format(s)
with_remotes = lambda s: 'remotes/{}'.format(s)
with_remote_tags = lambda s: 'remote-tags/{}'.format(s)

abs_head = compose(with_heads, with_refs)
abs_tag = compose(with_tags, with_refs)
abs_remote = compose(with_remotes, with_refs)
abs_remote_tag = compose(with_remote_tags, with_refs)

def without_refs(s):
    xs = s.split('/', 1)
    return xs[1] if len(xs) == 2 and xs[0] == 'refs' else s

def without_heads_or_tags(s):
    xs = s.split('/', 1)
    return xs[1] if len(xs) == 2 and xs[0] in ['heads', 'tags'] else s

as_relative_ref = compose(without_refs, without_heads_or_tags)

resolve_ref = lambda repo, ref: git.refs.reference.Reference(repo, ref).commit
        
# Bug: Does not escape characters in 'remote'.
def add_remote(repo, remote, url, fetch_refspecs = [], push_refspecs = [], prune = None, no_tags = False, exist_ok = False, overwrite = False):
    with repo.config_writer() as c:
        section = 'remote "{}"'.format(remote)
        if c.has_section(section):
            if overwrite:
                c.remove_section(section)
            else:
                assert exist_ok, "section {} exists".format(section)
        c.add_section(section)
        c.add_value(section, 'url', url)
        for refspec in fetch_refspecs:
            c.add_value(section, 'fetch', refspec)
        for refspec in push_refspecs:
            c.add_value(section, 'push', refspec)
        if prune != None:
            c.add_value(section, 'prune', boolean(prune))
        if no_tags:
            c.add_value(section, 'tagopt', '--no-tags')

def onesided_merge(repo, commit, new_parent):
    return git.Commit.create_from_tree(
        repo,
        commit.tree,
        'merge commit',
        [commit, new_parent],
        head = False,
        author_date = commit.authored_datetime,
        commit_date = commit.committed_datetime,
    )

# Only creates a new commit if necessary.
def tag_onesided_merge(repo, tag, commit, new_parent):
    if not repo.is_ancestor(new_parent, commit):
        commit = onesided_merge(repo, commit, new_parent)
    return repo.create_tag(tag, commit)

#===============================================================================
# Other tools

def read_private_token(x):
    if isinstance(x, Path):
        x = x.read_text()
    return x

def project_path(project):
    return PurePosixPath(project.path_with_namespace)

def protect_master(project):
    project.branches.get('master').protect(developers_can_push = True, developers_can_merge = True)
    project.save()

def protect_tags(project, tags):
    for x in project.protectedtags.list():
        x.delete()
    for pattern in tags:
        project.protectedtags.create({'name': pattern, 'create_access_level': gitlab.DEVELOPER_ACCESS})
    project.save()

#===============================================================================
# Gitlab course and local repository management

class Course:
    def __init__(self, config, canvas_use_cache = True):
        self.canvas = canvas.Canvas(config.canvas_url, auth_token = config.canvas_auth_token)
        self.canvas_course = canvas.Course(self.canvas, config.canvas_course_id, use_cache = canvas_use_cache)
        self.canvas_group_set = canvas.GroupSet(self.canvas_course, config.canvas_group_set, use_cache = canvas_use_cache)

        self.config = config
        self.gl = gitlab.Gitlab(config.base_url, private_token = read_private_token(config.private_token))
        self.gl.auth()
        #self.gl.enable_debug()

        self.path = config.course_path
        self.tas_path = self.path / config.teachers_path

    def get_url(self, path):
        return self.config.base_url + str(path)

    def project_path(self, project):
        if not hasattr(project, 'path_with_namespace'):
            project = self.project(project.id, lazy = False)
        return PurePosixPath(project.path_with_namespace)

    def group(self, id, lazy = True):
        return self.gl.groups.get(id if isinstance(id, int) else str(id), lazy = lazy)

    def project(self, id, lazy = True):
        return self.gl.projects.get(id if isinstance(id, int) else str(id), lazy = lazy)

    def lab_group_path(self, n):
        return self.path / self.config.lab_group_print(n)

    @functools.cached_property
    def course_group_lazy(self):
        return self.group(self.path, lazy = True)

    @functools.cached_property
    def course_group(self):
        return self.group(self.path, lazy = False)

    @functools.cached_property
    def lab_groups(self):
        return dict(sorted(list(
            (m, self.gl.groups.get(subgroup.id, lazy = True))
            for subgroup in self.course_group_lazy.subgroups.list(all = True)
            for m in [self.config.lab_group_parse(subgroup.path)]
            if m != None
        ), key = operator.itemgetter(0)))

    @functools.cache
    def lab_group(self, n):
        return self.gl.groups.get(self.lab_groups[n].id)

    def members_from_access(group, levels):
        return dict((user.id, user) for user in group.members.list(all = True) if user.access_level in levels)

    @functools.cached_property
    def teachers(self):
        return Course.members_from_access(self.course_group_lazy, [gitlab.OWNER_ACCESS])

    @functools.cache
    def students(self, n):
        return Course.members_from_access(self.lab_groups[n], [gitlab.DEVELOPER_ACCESS, gitlab.MAINTAINER_ACCESS])

    # Expects a map from ids to users (can be lazy).
    def mention(users):
        return ' '.join(sorted(['@' + user.username for user in users.values()], key = str.casefold))

    @functools.cached_property
    def google_client(self):
        return gspread.oauth()

    GradingColumns = collections.namedtuple('GradingColumns', ['query', 'grader', 'score'])

    class SheetParseException(Exception):
        pass

    def parse_grading_columns(self, row):
        i = 0

        def consume_header(value):
            nonlocal i
            if not (i != len(row) and row[i] == value):
                raise Course.SheetParseException(f'expected header in column {i + 1}: {value}')
            r = i
            i += 1
            return r

        consume_header(self.config.grading_sheet_header_group)

        r = list()
        while i != len(row):
            if self.config.grading_sheet_header_query_parse(row[i]) == None:
                i += 1
                continue

            r.append(Course.GradingColumns(
                query = consume_header(self.config.grading_sheet_header_query_print(len(r))),
                grader = consume_header(self.config.grading_sheet_header_grader),
                score = consume_header(self.config.grading_sheet_header_score),
            ))

        return r

    def parse_group_rows(self, column):
        r = dict()
        for i in range(1, len(column)):
            if column[i] != '':
                n = int(column[i])
                if n in r:
                    raise Course.SheetParseException(f'Duplicate group {n}')
                r[n] = i
        return r

    GradingSheet = collections.namedtuple('GradingSheet', ['group_rows', 'grading_columns', 'rows'])

    def parse_grading_sheet(self, worksheet):
        rows = worksheet.get_all_values(value_render_option = 'FORMULA')
        return Course.GradingSheet(
            group_rows = self.parse_group_rows([row[0] for row in rows]),
            grading_columns = self.parse_grading_columns(rows[0]),
            rows = rows,
        )

    # TODO: No idea how Google Sheets expects data to be escaped.
    def sheet_value_link(url, label):
        return '=HYPERLINK("{}", "{}")'.format(url, label)

    def print_issue(self, project, issue):
        print_error('* author: {}'.format(issue.author['name']))
        print_error('* title: {}'.format(issue.title))
        print_error('* URL: {}'.format(self.get_url(self.project_path(project) / '-' / 'issues' / str(issue.iid))))

    def parse_issues(self, project):
        grading_responses = dict()
        test_responses = dict()
        for issue in project.issues.list(all = True):
            if issue.author['id'] in self.teachers:
                x = self.config.grading_issue_parse(issue.title)
                if x:
                    (tag, grading) = x
                    grading_responses[tag] = (issue, grading)
                    continue

                x = self.config.testing_issue_parse(issue.title)
                if x:
                    tag = x
                    test_responses[tag] = (issue, ())
                    continue

                print_error(f'Unknown issue in project {self.project_path(project)}:')
                self.print_issue(project, issue)
        return (grading_responses, test_responses)

    def parse_tags(self, project):
        grading_queries = list()
        test_queries = list()
        for tag in project.tags.list(all = True):
            # Warning: The committed date is set by the students.
            tag.date = date_parser.parse(tag.commit['committed_date'])
            if re.fullmatch(self.config.submission_regex, tag.name):
                grading_queries.append(tag)
                continue

            if re.fullmatch(self.config.test_regex, tag.name):
                test_queries.append(tag)
                continue

            print_error(f'Unknown tag {tag.name} in project {self.project_path(project)}:')

        grading_queries.sort(key = operator.attrgetter('date'))
        test_queries.sort(key = operator.attrgetter('date'))
        return (grading_queries, test_queries)

    def parse_gradings_and_tests(self, project):
        (grading_responses, test_responses) = self.parse_issues(project)
        (grading_queries, test_queries) = self.parse_tags(project)

        def match(queries, responses, desc):
            r = [(query, responses.pop(query.name, None)) for query in queries]
            for tag, (issue, _) in responses.items():
                print_error(f'Unmatched {desc} response:')
                self.print_issue(project, issue)
            return r

        gradings = match(grading_queries, grading_responses, 'grading')
        tests = match(test_queries, test_responses, 'test')
        return (gradings, tests)

    def response_map(x):
        return dict((query.name, response) for query, response in x)

    # In chronological order.
    def handled_queries(x):
        return [y for (y, z) in x if z != None]

    # In reverse chronological order, last unhandled query first.
    def unhandled_queries(x):
        for i in reversed(range(len(x))):
            if x[i][1] != None:
                break
            yield x[i][0]

    # Only last unhandled query.
    def unhandled_query(x):
        y = list(Course.unhandled_queries(x))
        return y[0] if y else None

    def last_handled_query(x):
        for i in reversed(range(len(x))):
            if x[i][1] != None:
                return x[i][0]
        return None

    # Handled plus last unhandled query, if any.
    def relevant_queries(x):
        yield from Course.handled_queries(x)
        if y := Course.unhandled_query(x):
            yield y

    def tree_link(self, project_path, ref):
        return '{}{}/-/tree/{}'.format(
            self.config.base_url,
            project_path,
            ref,
        )

    def compare_link(self, project_path, diff_name):
        return '{}{}/-/compare/{}?w=1'.format(
            self.config.base_url,
            project_path,
            diff_name,
        )

    def print_user(self, id):
        x = gl.users.get(id)
        print(x)

if __name__ == "__main__":
    logging.basicConfig()
    logger.setLevel(logging.DEBUG)

    import gitlab_config
    course = Course(gitlab_config)
