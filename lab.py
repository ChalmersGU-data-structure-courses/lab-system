# Special import for git python.
import os
os.environ['GIT_PYTHON_TRACE'] = '1'
import git

import collections
import dominate
import git
#import gspread
import functools
import logging
import operator
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import webbrowser

import check_symlinks
from course import *
from general import *
import get_feedback_helpers
import java
import robograde

logger = logging.getLogger('lab')

class Lab:
    def __init__(self, course, lab, bare = False):
        # General config
        self.course = course
        self.config = self.course.config
        self.lab = lab
        self.rel_path = self.config.lab_print(lab)
        self.lab_name = self.config.lab_name_print(lab)

        # GitLab config
        self.gl = self.course.gl
        self.path = self.course.path / self.rel_path
        self.problem_path = self.path / self.config.lab_problem
        self.solution_path = self.path / self.config.lab_solution
        self.grading_path = self.path / self.config.lab_grading

        # GitLab local repo config
        self.bare = bare
        self.dir = self.config.dir_labs / self.rel_path
        self.init_repo()

        # Code repo config
        self.code_repo_dir = self.config.code_repo_lab_dir / self.rel_path

        # Other
        self.has_robograder = self.lab in self.config.robograders

    def lab_group_project_path(self, n):
        return self.course.lab_group_path(n) / self.config.lab_print(self.lab)

    def lab_group_project(self, n, lazy = True):
        return self.course.project(self.lab_group_project_path(n), lazy = lazy)

    def problem_project(self, lazy = True):
        return self.course.project(self.problem_path, lazy = lazy)

    def solution_project(self, lazy = True):
        return self.course.project(self.solution_path, lazy = lazy)

    def grading_project(self, lazy = True):
        return self.course.project(self.grading_path, lazy = lazy)

    def print_submission_status(self):
        for n in self.course.lab_groups:
            project = self.lab_group_project(n, lazy = False)
            (gradings, tests) = self.course.parse_gradings_and_tests(project, self.teachers)
            for tag in Course.unhandled_queries(gradings):
                print_error(f'Unhandled grading query {tag.name} in project {project.path_with_namespace}')
            for tag in Course.unhandled_queries(tests):
                print_error(f'Unhandled test query {tag.name} in project {project.path_with_namespace}')
            print()

    def parse_grading_tag(self, s):
        x = s.split('/', 1)
        if len(x) == 2:
            n = self.config.lab_group_parse(x[0])
            if n != None:
                return (n, x[1])
        return None

    @functools.cached_property
    def gradings_and_tests(self):
        return dict((n, self.course.parse_gradings_and_tests(self.lab_group_project(n))) for n in self.course.lab_groups)

    @functools.cached_property
    def grading_tests(self):
        project = self.grading_project(lazy = False)
        r = collections.defaultdict(dict)
        for issue in project.issues.list(all = True):
            if issue.author['id'] in self.course.teachers:
                x = self.config.testing_issue_parse(issue.title)
                if x:
                    n, tag = self.parse_grading_tag(x)
                    r[n][tag] = issue
                    continue

                print_error(f'Unknown issue in grading project {project.path_with_namespace}:')
                self.course.print_issue(project, issue)
        return r

    def mark_tests_as_preliminary(self):
        for n in self.course.lab_groups:
            _, tests = self.gradings_and_tests[n]
            responses = Course.response_map(tests)
            for tag in Course.handled_queries(tests):
                issue = responses[tag.name][0]
                issue.title = self.config.testing_issue_print(tag.name, preliminary = True)
                issue.save()
        clear_cached_property(self, 'gradings_and_tests')

    @functools.cached_property
    def grading_sheet(self):
        (spreadsheet_key, worksheet) = self.config.lab_grading_sheets[self.lab]
        s = course.google_client.open_by_key(spreadsheet_key)
        return s.get_worksheet(worksheet) if isinstance(worksheet, int) else s.get_worksheet_by_id(worksheet)

    @functools.cached_property
    def grading_sheet_parsed(self):
        return self.course.parse_grading_sheet(self.grading_sheet)

    def update_grading_sheet(self):
        logger.log(logging.INFO, 'Updating grading sheet for {}...'.format(self.lab_name))

        cells = list()
        for n in self.course.lab_groups:
            row_index = self.grading_sheet_parsed.group_rows[n]
            row = self.grading_sheet_parsed.rows[row_index]

            def update_cell(column_index, value, **kwargs):
                if row[column_index] != value:
                    cells.append(gspread.models.Cell(1 + row_index, 1 + column_index, value = value))

            gradings, _ = self.gradings_and_tests[n]
            responses = Course.response_map(gradings)
            relevant = list(Course.relevant_queries(gradings))
            for m in range(len(relevant)):
                query = relevant[m]
                response = responses[query.name]
                grading_columns = self.grading_sheet_parsed.grading_columns[m]
                query_formatted = Course.sheet_value_link(self.course.tree_link(self.lab_group_project_path(n), query.name), query.name)

                if response:
                    issue, score = response
                    grader = self.config.gitlab_teacher_to_name.get(issue.author['name'], '???')
                    grader_with_link = Course.sheet_value_link(issue.web_url, grader)
                    consistent = all([
                        row[grading_columns.query] in ['', query.name, query_formatted],
                        row[grading_columns.grader] in ['', grader, grader_with_link],
                        row[grading_columns.score] in ['', score],
                    ])
                    if consistent:
                        update_cell(grading_columns.query, query_formatted)
                        update_cell(grading_columns.grader, grader_with_link)
                        update_cell(grading_columns.score, score)
                    else:
                        logger.log(logging.WARNING, 'Found inconsistency in response to {} of {}.'.format(
                            self.config.grading_sheet_header_query_print(m),
                            self.config.lab_group_name_print(n)
                        ))
                else:
                    if row[grading_columns.grader] == '' and row[grading_columns.score] == '':
                        update_cell(grading_columns.query, query_formatted)
                    else:
                        logger.log(logging.WARNING, 'Found grading for {} of {} without corresponding issue.'.format(
                            self.config.grading_sheet_header_query_print(m),
                            self.config.lab_group_name_print(n)
                        ))

        if cells:
            for cell in cells:
                logger.log(logging.DEBUG, 'Updating: {}'.format(str(cell)))

            clear_cached_property(self, 'grading_sheet_parsed')
            self.grading_sheet.update_cells(cells, value_input_option = 'USER_ENTERED')
        else:
            logger.log(logging.INFO, 'No cells to update.')

        logger.log(logging.INFO, 'Finished updating grading sheet.')

    def create_aux_projects(self):
        try:
            group_lab = self.course.group(self.path, lazy = False)
        except gitlab.GitlabGetError as e:
            if not e.response_code == 404:
                raise e

            group_lab = self.gl.groups.create({
                'name': self.lab_name,
                'path': self.rel_path,
                'parent_id': self.course.course_group.id,
            })

        for path in [self.config.lab_problem, self.config.lab_solution, self.config.lab_grading]:
            self.gl.projects.create({
                'path': str(path),
                'namespace_id': group_lab.id
            })

    def protect_student_master_branches(self):
        for n in self.course.lab_groups:
            print(f'protecting master for group {n}...')
            protect_master(self.lab_group_project(n))

    def protect_student_tags(self):
        for n in self.course.lab_groups:
            print(f'protecting tags for group {n}...')
            protect_tags(self.lab_group_project(n), self.config.protected_tags)

    def delete_spam(self):
        for n in self.course.lab_groups:
            self.course.project(self.course.lab_group_path(n) / 'problem').delete()

    def fix_project_names(self):
        for n in self.course.lab_groups:
            p = self.course.project(self.course.lab_group_path(n) / 'problem', lazy = False)
            p.path = 'lab4'
            p.save()

    def fix_project_branches(self):
        for n in self.course.lab_groups:
            p = self.lab_group_project(n)
            p.branches.get('problem').delete()

    def fork_lab_project(self):
        p = self.problem_project(lazy = False)
        print(p.forks)

        for n in self.course.lab_groups:
            group = self.course.lab_group(n)
            print('forking {} to {}...'.format(p.name, group.name))
            try:
                # doesn't work!
                q = p.forks.create({
                    'name': self.lab_name,
                    'namespace': group.id,
                })
                #q.delete_fork_relation() for some reason, doesn't work here
                print('forked {} to {}'.format(p.name, group.name))
            except gitlab.exceptions.GitlabCreateError:
                print('skipping already created project for group {}'.format(group.name))
                continue

            # For some reason, the project is not found here.
            #print('protecting tags...')
            #protect_tags(self.lab_group_project(n), self.config.protected_tags)
            #print('protecting master...')
            #protect_master(self.lab_group_project(n))
            print('fork done')

    def delete_fork_relation(self):
        for n in self.course.lab_groups:
            self.lab_group_project(n).delete_fork_relation()

    # Tags fetched will be prefixed by remote.
    def add_remote(self, remote, project, fetch_branches = True, fetch_tags = False, push_refspecs = [], **kwargs):
        def fetch_refspecs():
            if fetch_branches:
                yield '+refs/heads/*:refs/remotes/{}/*'.format(remote)
            if fetch_branches == 'copy':
                yield '+refs/heads/*:refs/heads/*'.format(remote)
            if fetch_tags:
                yield '+refs/tags/*:refs/remote-tags/{}/*'.format(remote)

        add_remote(
            self.repo,
            remote,
            project.ssh_url_to_repo,
            list(fetch_refspecs()),
            list(push_refspecs),
            **kwargs
        )

    def add_aux_remotes(self):
        remotes = [
            (self.config.lab_problem, True, [
                '+refs/heads/master:refs/heads/problem',
            ]),
            (self.config.lab_solution, 'copy' if self.bare else True, [
                '+refs/heads/problem:refs/heads/problem',
                '+refs/heads/solution:refs/heads/solution',
            ]),
            (self.config.lab_grading, False, [
                '+refs/tags/*:refs/tags/*',
                '+refs/heads/problem:refs/heads/problem',
                '+refs/heads/solution:refs/heads/solution',
            ]),
        ]

        for remote, fetch_branches, push_refspecs in remotes:
            self.add_remote(
                remote,
                self.course.project(self.path / remote, lazy = False),
                fetch_branches = fetch_branches,
                push_refspecs = push_refspecs,
            )

    def add_lab_group_remotes(self, **kwargs):
        for n in self.course.lab_groups:
            self.add_remote(
                self.config.lab_group_print(n),
                self.lab_group_project(n, lazy = False),
                fetch_tags = True,
                prune = True,
                no_tags = True,
                **kwargs,
            )

    def init_repo(self):
        if self.dir.exists():
            self.repo = git.Repo(self.dir)
        else:
            self.repo = git.Repo.init(self.dir, bare = self.bare)
            self.add_aux_remotes()
            self.add_lab_group_remotes()
            self.repo.remote('problem').fetch()
            self.repo.remote('solution').fetch()

            #self.repo.create_head('problem').set_tracking_branch(solution.refs.)
            #self.repo.create_head('solution').set_tracking_branch(solution.refs.solution)
 
    def fetch_lab_groups(self):
        for n in self.course.lab_groups:
            remote = self.config.lab_group_print(n)
            self.repo.remote(remote).fetch()

    def clear_grading_tags(self):
        self.repo.delete_tag([tag for tag in self.repo.tags if self.parse_grading_tag(tag.name) or tag.name.startswith('merge/')])

    def commit_from_gitlab_tag(self, tag):
        return git.Commit(self.repo, bytes.fromhex(tag.commit['id']))

    Diffs = collections.namedtuple('Diffs', [
        'current_vs_problem',
        'current_vs_solution',
        'current_vs_previous',
    ])

    def diff_target(start, end):
        return 'merge/{}/then/{}'.format(as_relative_ref(start), as_relative_ref(end))

    def diff_name(start, end):
        return '{}...{}'.format(start, Lab.diff_target(start, end))

    def add_grading_tags_for_lab_group(self, n, gradings):
        remote = self.config.lab_group_print(n)
        with_remote = lambda s: '{}/{}'.format(remote, s)

        def create_diff(start, end):
            tag_onesided_merge(self.repo, Lab.diff_target(start, end), resolve_ref(self.repo, end), resolve_ref(self.repo, start))

        # create the submission tags and merge tags
        for tag, _ in gradings:
            submission = with_remote(tag.name)
            self.repo.create_tag(submission, self.commit_from_gitlab_tag(tag))
            create_diff(abs_head('problem'), abs_tag(submission))
            create_diff(abs_head('solution'), abs_tag(submission))

        for i, j in [(i, j) for i in range(len(gradings)) for j in range(len(gradings)) if i < j]:
            tag_from, _ = gradings[i]
            tag_to, _ = gradings[j]
            create_diff(abs_tag(with_remote(tag_from.name)), abs_tag(with_remote(tag_to.name)))

    def add_grading_tags(self):
        for n in self.course.lab_groups:
            gradings, _ = self.gradings_and_tests[n]
            self.add_grading_tags_for_lab_group(n, gradings)

    def fetch_lab_groups(self):
        logger.log(logging.INFO, 'Fetching lab groups...')
        for n in self.course.lab_groups:
            self.repo.remote(self.config.lab_group_print(n)).fetch()
        logger.log(logging.INFO, 'Fetched lab.')

    def push_grading(self):
        logger.log(logging.INFO, 'Pushing grading repository...')
        self.repo.remote(self.config.lab_grading).push(prune = True)
        logger.log(logging.INFO, 'Pushed grading repository.')

    def update_grading_repo(self):
        logger.log(logging.INFO, 'Updating grading repository...')
        self.fetch_lab_groups()
        self.clear_grading_tags()
        self.add_grading_tags()
        self.push_grading()
        logger.log(logging.INFO, 'Updated grading repository.')

    def hotfix_lab_group_master(self, hotfix_name, n):
        remote = self.config.lab_group_print(n)
        with_remote = lambda s: '{}/{}'.format(remote, s)

        problem = resolve_ref(self.repo, abs_head('problem'))
        hotfix = resolve_ref(self.repo, abs_head(hotfix_name))
        if problem == hotfix:
            logger.log(logging.WARNING, 'Hotfixing: hotfix is identical to problem.')
            return

        master = abs_remote(with_remote('master'))
        index = git.IndexFile.from_tree(self.repo, problem, master, hotfix, i = '-i')
        merge = index.write_tree()
        diff = merge.diff(master)
        if not diff:
            logger.log(logging.WARNING, 'Hotfixing: already applied for {}.'.format(self.config.lab_group_name_print(n)))
            return
        for x in diff:
            logger.log(logging.INFO, str(x))

        commit = git.Commit.create_from_tree(
            self.repo,
            merge,
            hotfix.message,
            parent_commits = [resolve_ref(self.repo, master)],
            head = False,
            author = hotfix.author,
            committer = hotfix.committer,
            author_date = hotfix.authored_datetime,
            commit_date = hotfix.committed_datetime,
        )

        remote = self.repo.remote(remote)
        refspec = commit.hexsha + ':' + abs_head('master')
        return remote.push(refspec = refspec)

    def hotfix_lab_groups_master(self, hotfix_name):
        for n in self.course.lab_groups:
            self.hotfix_lab_group_master(hotfix_name, n)

    def mention_students_in_last_gradings(self):
        for n in self.course.lab_groups:
            gradings, _ = lab.gradings_and_tests[n]
            responses = Course.response_map(gradings)
            if last := Course.last_handled_query(gradings):
                (issue, grade) = responses[last.name]
                mention = Course.mention(self.course.students(n))
                if not (issue.closed_at or mention in issue.description):
                    print('{}: {}, {}'.format(n, issue.web_url, Course.mention(self.course.students(n))))
                    issue.description = '{}\n\n{}\n'.format(issue.description, mention)
                    issue.save()
        clear_cached_property(self, 'gradings_and_tests')

    def submission_checkout(self, dir, ref):
        cmd = ['tar', '-x']
        with working_dir(dir):
            log_command(logger, cmd, True)
            tar = subprocess.Popen(cmd, stdin = subprocess.PIPE)
        self.repo.archive(tar.stdin, ref)
        tar.stdin.close()
        wait_and_check(tar, cmd)

    def submission_check_symlinks(self, dir):
        check_symlinks.check_self_contained(dir)

    def submission_compile(self, dir):
        java.compile_java_dir(dir, detect_enc = True)

    def submission_robograde(self, dir):
        return robograde.robograde(dir, [self.config.code_repo_robograding_dir, self.code_repo_dir / 'pregrade'], 'Robograder', machine_speed = self.config.robograder_machine_speed)

    def robograde_tag(self, n, tag, in_student_repo = False):
        remote = self.config.lab_group_print(n)
        with_remote = lambda s: '{}/{}'.format(remote, s)
        logger.log(logging.INFO, 'Robograding {}...'.format(with_remote(tag)))

        with tempfile.TemporaryDirectory() as dir:
            dir = Path(dir)
            self.submission_checkout(dir, abs_remote_tag(with_remote(tag)))

            response = None

            # TODO: Escape embedded error for Markdown.
            def record_error(description, error, is_code):
                nonlocal response
                code = '```' if is_code else ''
                response = '{}\n{}\n{}\n{}\n'.format(description, code, error.strip(), code)

            try:
                self.submission_check_symlinks(dir)
                self.submission_compile(dir)
                response = self.submission_robograde(dir)
            except check_symlinks.SymlinkException as e:
                record_error('There is a problem with symbolic links in your submission.', e.text, True)
            except java.CompileError as e:
                record_error('I could not compile your Java files:', e.compile_errors, True)
            except robograde.RobogradeFileConflict as e:
                response = 'I could not test your submission because the compiled file\n```\n{}\n```\nconflicts with files I use for testing.'.format(e.file)
            except robograde.RobogradeException as e:
                record_error('Oops, you broke me!\n\nI encountered a problem while testing your submission.\nThis could be a problem with myself (a robo-bug) or with your code (unexpected changes to class or methods signatures). If it is the latter, you might be able to elucidate the cause from the below error message and fix it. If not, tell my designers!', e.errors, True)

            if in_student_repo:
                response = '{}\n{}\n'.format(response, Course.mention(self.course.students(n)))

            p = self.lab_group_project(n) if in_student_repo else self.grading_project()
            logger.log(logging.INFO, response)
            p.issues.create({
                'title': self.config.testing_issue_print(tag if in_student_repo else with_remote(tag)),
                'description': response,
            })

        logger.log(logging.INFO, 'Robograded {}.'.format(with_remote(tag)))

    def robograde_submissions(self):
        logger.log(logging.INFO, 'Robograding submissions...')
        for n in self.course.lab_groups:
            gradings, _ = self.gradings_and_tests[n]
            if unhandled := Course.unhandled_query(gradings):
                if not unhandled.name in self.grading_tests[n]:
                    self.robograde_tag(n, unhandled.name, False)
        clear_cached_property(self, 'grading_tests')
        logger.log(logging.INFO, 'Robograded submissions.')

    def print_unhandled_tests(self):
        print('Unhandled test requests:')
        for n in self.course.lab_groups:
            _, tests = self.gradings_and_tests[n]
            if test := Course.unhandled_query(tests):
                print('* {}: {}'.format(self.config.lab_group_name_print(n), test.name))
        print()

    def print_handled_tests(self):
        print('Handled test requests:')
        for n in self.course.lab_groups:
            _, tests = self.gradings_and_tests[n]
            responses = Course.response_map(tests)
            for test in Course.handled_queries(tests):
                print('* {}: {}, {}, {}'.format(
                    self.config.lab_group_name_print(n),
                    test.name,
                    responses[test.name][0].web_url,
                    Course.mention(self.course.students(n))
                ))
        print()

    def robograde_tests(self):
        for n in self.course.lab_groups:
            _, tests = self.gradings_and_tests[n]
            if test := Course.unhandled_query(tests):
                self.robograde_tag(n, test.name, True)
        clear_cached_property(self, 'gradings_and_tests')

    def build_index(self, preview = True):
        logger.log(logging.INFO, 'Building current submissions index...')
        from dominate.tags import a, button, div, link, meta, p, pre, script, span, style, table, tbody, td, th, thead, tr
        from dominate.util import raw, text

        doc = dominate.document()
        doc.title = 'Grading requests: {}'.format(self.lab_name)
        with doc.head:
            meta(charset = 'utf-8')
            # Make it fit into the Canvas style.
            # Don't know how to give crossorigin tag with no value.
            #link(rel = 'preconnect', href = 'https://fonts.gstatic.com/')
            raw('<link rel="preconnect" href="https://fonts.gstatic.com/" crossorigin>')
            link(rel = 'stylesheet', media = 'screen', href = 'https://du11hjcvx0uqb.cloudfront.net/br/dist/brandable_css/no_variables/bundles/lato_extended-a29d3d859f.css')
            style("""
body {
  font-family: 'Lato Extended',Lato,Helvetica Neue,Helvetica,Arial,sans-serif;
}
.controls {
  margin-top: 5px;
  margin-bottom: 5px;
}
#results {
  border-collapse: collapse;
  border: 1px black solid;
}
#results th, #results td {
  border-top: 1px black solid;
  border-bottom: 1px black solid;
  border-left: 1px black solid;
  padding: 6px;
  vertical-align: top;
}
#results p {
  margin: 0px;
}
#results pre {
  font-size: smaller;
  margin: 0px;
  white-space: pre-wrap;
}
#results .files {
  border-collapse: collapse
}
#results .files td {
  border: 0px;
  padding: 0px;
  vertical-align: top;
  white-space: nowrap;
}
.same {
  opacity: 0.5;
}
.error {
  color: #af0000;
}
.hidden {
  display: none;
}
.to-load {
  background-color: #eeeeee;
}
""")
#             with script(type = 'text/javascript'):
#                 raw("""

#   function listSet(classList, _class, value) {
#     classList[value ? 'add' : 'remove'](_class);
#   }

#   function getVisibility(row) {
#     return !row.firstElementChild.classList.contains('to-load');
#   }

#   function setVisibility(row, visibility) {
#     first = true;
#     for (cell of row.getElementsByTagName('TD')) {
#       listSet(cell.classList, 'to-load', !visibility);
#       if (!first)
#         listSet(cell.firstElementChild.classList, 'hidden', !visibility);
#       first = false;
#     }
#   }

#   function setVisibilityAll(visibility) {
#     for (row of document.getElementById('results').getElementsByTagName('TBODY')[0].getElementsByTagName('TR'))
#       setVisibility(row, visibility);
#   }

#   function handleClick(element, event) {
#     if (event.eventPhase === Event.AT_TARGET) {
#       while (element.nodeName !== 'TD')
#         element = element.parentElement;
#       row = element.parentElement
#       if (getVisibility(row)) {
#         if (element.previousElementSibling === null)
#           setVisibility(row, false);
#       } else
#         setVisibility(row, true);
#     }
#   }
# """)

        # js_params = {
        #     'onclick': 'handleClick(this, event);'
        # }

        def cell(*args, **kwargs):
            return div(*args, **kwargs)
            #return div(*args, **kwargs, **js_params)

        rows = list()
        for n in self.course.lab_groups:
            gradings, _ = self.gradings_and_tests[n]
            responses = Course.response_map(gradings)
            current = Course.unhandled_query(gradings)
            if not current:
                continue

            remote = self.config.lab_group_print(n)
            with_remote = lambda s: '{}/{}'.format(remote, s)

            previous = Course.last_handled_query(gradings)

            row = SimpleNamespace()
            rows.append(row)

            # Sort by submission date
            row.key = current.date

            # Submission date
            row.date = cell(current.date.strftime('%b %d, %H:%M'))

            # Submission number
            row.number = cell(len(Course.handled_queries(gradings)) + 1)

            # Group number
            row.group = cell(str(n))

            # Group members
            row.members = Course.mention(self.course.students(n))

            test_response = self.grading_tests[n].get(current.name)
            
            # Current submission
            row.files = cell(
                p(a(current.name, href = self.course.tree_link(self.lab_group_project_path(n), current.name))),
            )

            # Current submission with robograding
            #row.files = cell(
            #    p(a(current.name, href = self.course.tree_link(self.lab_group_project_path(n), current.name))),
            #    p('hidden ', a('robograding', href = test_response.web_url)),
            #)

            previous_issue = responses[previous.name][0] if previous else None
            row.files_vs_previous = cell(
                p(a('{}...'.format(previous.name), href = self.course.compare_link(self.grading_path, Lab.diff_name(with_remote(previous.name), with_remote(current.name))))),
                p('graded by ', a(self.config.gitlab_teacher_to_name.get(previous_issue.author['name']), href = previous_issue.web_url)),
            ) if previous else None
            row.files_vs_problem = cell(a('problem...', href = self.course.compare_link(self.grading_path, Lab.diff_name('problem', with_remote(current.name)))))
            row.files_vs_solution = cell(a('solution...', href = self.course.compare_link(self.grading_path, Lab.diff_name('solution', with_remote(current.name)))))

            # Robograding
            row.robograding = cell(a('robograding', href = test_response.web_url)
            ) if test_response else None

            # Comments
            row.message = cell(pre(current.message))

        #if not len(row_dict) < 10:
        #    doc.body['onload'] = 'setVisibilityAll(false);'

        # with doc.body.add(div(Class = 'controls')):
        #     button('Show all', onclick = 'setVisibilityAll(true);')
        #     text(' / ')
        #     button('Hide all', onclick = 'setVisibilityAll(false);')

        def build_index_files_entry(rel_base_dir, folder_name):
            return ('Vs. {}'.format(folder_name), lambda group: build_index_files(group, rel_base_dir(group), folder_name))

        T = collections.namedtuple('KeyData', ['title', 'style'], defaults = [None])

        # This took me more than 2 hours.
        def with_after(title, title_after):
            return T(th(div(title + title_after, style = 'white-space: pre; max-height: 0; visibility: hidden;'), title, span(title_after, style = 'float: right; white-space: pre;')))

        def following(title):
            return T(title, style = 'border-left-color: lightgrey;')

        keys = collections.OrderedDict({
            'date': T('Date', style = 'text-align: center;'),
            'number': T('#', style = 'text-align: center;'),
            'group': T('Group', style = 'text-align: center;'),
            'members': T('Members (to mention)'),
            'files': with_after('Submission', ' vs:'),
            'files_vs_previous': following('previous'),
            'files_vs_problem': following('problem'),
            'files_vs_solution': following('solution'),
            'robograding': T('Robograding'),
            'message': T('Message'),
        })

        # Sort by key.
        rows.sort(key = operator.attrgetter('key'))

        # Remove empty columns.
        for key in list(keys):
            non_empty = False
            for row in rows:
                non_empty |= getattr(row, key) != None
            if not non_empty:
                del keys[key]
            else:
                for row in rows:
                    if getattr(row, key) == None:
                        setattr(row, key, cell())

        def handle(key_data, el):
            if key_data.style:
                el.set_attribute('style', key_data.style)

        results_table = doc.body.add(table(id = 'results'))
        header_row = results_table.add(thead()).add(tr())
        for key, key_data in keys.items():
            handle(key_data, header_row.add(th(key_data.title) if isinstance(key_data.title, str) else key_data.title))
        results_table_body = results_table.add(tbody())
        for row in rows:
            table_row = results_table_body.add(tr())
            for key, key_data in keys.items():
                handle(key_data, table_row.add(td(getattr(row, key))))
#                handle(key_data, table_row.add(td(getattr(row, key), **js_params)))

        with tempfile.TemporaryDirectory() as dir:
            file = Path(dir) / 'index.html'
            file.write_text(doc.render(pretty = False))
            folder_id = self.course.canvas.get_list(self.course.canvas_course.endpoint + ['folders', 'by_path', self.config.canvas_grading_path])[-1].id
            self.course.canvas_course.post_file(file, folder_id, '{}-to-be-graded.html'.format(self.rel_path), locked = True)
        logger.log(logging.INFO, 'Built current submissions index.')

    def update_submissions_and_gradings(self):
        self.update_grading_repo()
        if self.has_robograder:
            self.robograde_submissions()
        self.build_index()
        self.update_grading_sheet()

    def compile_robograder(self):
        with tempfile.TemporaryDirectory() as dir:
            dir = Path(dir)
            self.submission_checkout(dir, abs_head('problem'))
            java.compile_java_dir(self.code_repo_dir / 'pregrade', force_recompile = True, classpath = [self.config.code_repo_robograding_dir, self.code_repo_dir / 'pregrade', dir])

    #def initialize_repo():
    #    mkdir_fresh(self.dir)
    #    repo = git.Repo.clone_from(self.dir)

    def extract_names(self, n, tag):
        remote = self.config.lab_group_print(n)
        with_remote = lambda s: '{}/{}'.format(remote, s)
        with tempfile.TemporaryDirectory() as dir:
            dir = Path(dir)
            self.submission_checkout(dir, abs_remote_tag(with_remote(tag)))
            answers_file = dir / 'answers.txt'
            answers = read_text_detect_encoding(answers_file)
            answers = '\n'.join(map(str.strip, answers.splitlines()))
            (header, info) = get_feedback_helpers.parse_answers_list(answers)[0]
            assert re.fullmatch('DIT181\\s+Datastrukturer\\s+och\\s+algoritmer,\\s+LP3\\s+2021', header[0])
            info_lines = info.splitlines()
            i = 0
            while not info_lines[i] == 'Group members:':
                i = i + 1
            for s in info_lines[i + 1:]:
                if (re.fullmatch(get_feedback_helpers.pattern_question_begin, s + '\n')):
                    break
                while True:
                    s_orig = s
                    s = s.strip()
                    s = s.removeprefix('-')
                    if s and s[0] == '[' and s[-1] == ']':
                        s = s[1:-1]
                    if s == s_orig:
                        break
                if not s:
                    continue
                if s == '...':
                    continue
                yield s

    def get_canvas_group_users(self, n):
        g = self.course.canvas_group_set
        g_id = g.name_to_id[self.config.lab_group_name_print(n)]
        return g.group_users[g_id]

    @staticmethod
    def name_parts(name):
        return list(map(str.lower, re.findall(r'\w+', name)))

    def name_matches(self, name, n = None):
        if n != None:
            user_ids = self.get_canvas_group_users(n)

        for user in self.course.canvas_course.user_details.values():
            if set(set(Lab.name_parts(name))).issubset(set(Lab.name_parts(user.name))):
                if n == None or user.id in user_ids:
                    yield (user.name, user.id)

    # Bad complexity.
    def parse_name(self, name, n):
        corrected = self.config.name_corrections.get(name)
        if corrected != None:
            name = corrected

        matches = list(self.name_matches(name))

        # If there is more than one match, filter by group.
        # A common reason is a student just specifying their first name.
        if len(matches) > 1 and n != None:
            matches = list(self.name_matches(name, n))

        if len(matches) == 0 and name in self.config.outside_canvas:
            return name

        assert len(matches) == 1, f'Non-unique users matching {name}: {matches}'
        return from_singleton(matches)[1]

    # def confirm_names(self, n, names):
    #     g = self.course.canvas_group_set
    #     g_id = g.name_to_id[config.lab_group_name_print(n)]
    #     users = g.details[g_id]
    #     print(names

    # Returns a map from Canvas ids (and names of student not registered) to grade of last lab grading, if existing.
    def student_grades(self):
        def f(n):
            gradings, _ = self.gradings_and_tests[n]
            responses = Course.response_map(gradings)
            tag = Course.last_handled_query(gradings)
            if tag:
                provided_ids = set(self.parse_name(name, n) for name in self.extract_names(n, tag.name))
                group_user_ids = set(self.get_canvas_group_users(n))

                if provided_outside_group := provided_ids - group_user_ids - set(self.config.outside_canvas):
                    logger.log(logging.WARNING, 'Users listed in answers file are not in {}: {}'.format(self.config.lab_group_name_print(n), self.course.canvas_course.users_str(provided_outside_group)))

                if group_not_provided := group_user_ids - provided_ids:
                    logger.log(logging.WARNING, 'Group users in {} are not listed in answers file: {}'.format(self.config.lab_group_name_print(n), self.course.canvas_course.users_str(group_not_provided)))

                #print(n, tag.name)

                # Trust the student reportings over group membership.
                # Group membership might have changed.
                yield from ((id, responses[tag.name][1]) for id in provided_ids)

        return dict(x for n in self.course.lab_groups for x in f(n))

def labs(gitlab_config):
    course = Course(gitlab_config)
    return (course, dict((k, Lab(course, k, bare = True)) for k in gitlab_config.lab_grading_sheets))

if __name__ == "__main__":
    logging.basicConfig()
    logging.getLogger().setLevel(logging.WARNING)

    import gitlab_config
    course = Course(gitlab_config)

    #lab = Lab(course, 2)

    lab1 = Lab(course, 1, bare = True)
    lab2 = Lab(course, 2, bare = True)
    lab3 = Lab(course, 3, bare = True)
    lab4 = Lab(course, 4, bare = True)
    #lab4 = Lab(course, 4)
    #lab.update_grading_repo()
    #lab.robograde_submissions()
    #lab.build_index()
    #lab.update_grading_sheet()


#p = lab.get_lab_group_project(10)

#p = gl.projects.get('sattler/test')
#i = p.issues.list(all = True)[0]

#lab = Lab(course, 1)
#lab.print_submission_status(lab_groups, teachers)

#project = gl.projects.get('courses/dit181/lab_group_0/lab1')
#(gradings, tests) = course.parse_gradings_and_tests(project)
#unhandled_gradings = list(Course.unhandled_queries(gradings))
#unhandled_tests = list(Course.unhandled_queries(tests))

#course.parse_grading_issue(teachers, p)

#lab.add_aux_remotes(overwrite = True)
#lab.add_lab_group_remotes(overwrite = True)

#lab.clear_grading_tags()
#lab.add_grading_tags()

#lab.add_grading_tags(0, gradings)

#lab.mention_students_in_last_gradings()

#n = 30
#tag = 'spam'
#lab.robograde_tag(n, tag, False)

#lab.submission_checkout(dir, ref)
#lab.submission_check_symlinks(dir)
#lab.submission_compile(dir)
#o = lab.submission_robograde(dir)


#https://git.chalmers.se/courses/dit181/lab_group_19/lab2/-/issues/2
