import contextlib
import functools
import logging
import time

import git
import gitlab.exceptions

import general
import git_tools
import gitlab_tools
import markdown
import path_tools


class GradingViaMergeRequest:
    label_waiting = ('waiting-for-grading', 'yellow')

    @classmethod
    def label_outcome(cls, outcome):
        return {
            0: ('incomplete', 'red'),
            1: ('pass', 'green'),
        }[outcome]

    def __init__(self, group, logger = logging.getLogger(__name__)):
        self.group = group
        self.logger = logger

        self.course = group.course
        self.lab = group.lab
        self.gl = self.course.gl

    @functools.cached_property
    def project(self):
        '''
        A project used exclusively for grading.
        Branches:
        * main: containing a readme linking to the merge request,
        * problem: lab problem stub,
        * submission: branch tracking submission tags in the student project,
        '''
        r = gitlab_tools.CachedProject(
            gl = self.gl,
            path = self.course.group(self.group.id).path / self.course.config.lab.full_id_grading.print(self.lab.id),
            name = '{} — Grading'.format(self.lab.name),
            logger = self.logger,
        )

        def create():
            project = gitlab_tools.CachedProject.create(r, self.course.group(self.group.id).get)
            try:
                for target in [self.course.config.branch.problem, 'submission']:
                    self.lab.repo.git.push(
                        project.ssh_url_to_repo,
                        git_tools.refspec(
                            git_tools.local_branch(self.course.config.branch.problem),
                            target,
                            force = True,
                        ),
                    )

                # Hack
                time.sleep(0.1)

                merge_request = project.mergerequests.create({
                    'source_branch': 'submission',
                    'target_branch': 'problem',
                    'title': 'Submission grading',
                })

                with path_tools.temp_dir() as dir:
                    repo = git.Repo.init(str(dir))
                    (dir / 'README.md').write_text(general.join_lines([
                        f'Your submission grading is happening in [this merge request](!{merge_request.iid}).'
                    ]))
                    repo.git.add('--all', '--force')
                    repo.git.commit('--allow-empty', message = 'Grading project description.')
                    repo.git.push(
                        project.ssh_url_to_repo,
                        git_tools.refspec(git_tools.head, self.course.config.branch.master, force = True),
                    )

                project.protectedbranches.delete(self.course.config.branch.problem)

                # Hack
                time.sleep(0.1)

                project.default_branch = self.course.config.branch.master
                project.description = f'Grading for [{self.lab.name_full}]({self.group.project.lazy.web_url})'
                project.lfs_enabled = False
                project.issues_enabled = False
                project.wiki_enabled = False
                project.packages_enabled = False
                project.jobs_enabled = False
                project.snippets_enabled = False
                project.container_registry_enabled = False
                project.service_desk_enabled = False
                project.shared_runners_enabled = False
                project.ci_forward_deployment_enabled = False
                project.ci_job_token_scope_enabled = False
                project.public_jobs = False
                project.remove_source_branch_after_merge = False
                project.auto_devops_enabled = False
                project.keep_latest_artifact = False
                project.requirements_enabled = False
                project.security_and_compliance_enabled = False
                project.request_access_enabled = False
                project.forking_access_level = 'disabled'
                project.analytics_access_level = 'disabled'
                project.operations_access_level = 'disabled'
                project.releases_access_level = 'disabled'
                project.pages_access_level = 'disabled'
                project.security_and_compliance_access_level = 'disabled'
                project.emails_disabled = False
                project.permissions = {'project_access': None, 'group_access': None}
                project.save()

                def configure_label(name, color):
                    project.labels.create({
                        'name': name,
                        'color': color,
                    })

                configure_label(*self.label_waiting)
                for outcome in self.course.config.outcomes:
                    configure_label(*self.label_outcome(outcome))
            except:  # noqa: E722
                r.delete()
                raise
        r.create = create

        return r

    @functools.cached_property
    def merge_request(self):
        (merge_request,) = gitlab_tools.list_all(self.project.lazy.mergerequests)
        return merge_request

    def update_submission(self, submission):
        #submission.request_name
        self.lab.repo.git.push(
            self.project.get.ssh_url_to_repo,
            git_tools.refspec(submission.repo_tag().commit, 'submission', force = True),
        )

        def body():
            link = gitlab_tools.url_tree(self.group.project.get, submission.request_name)
            yield general.join_lines([
                f'Synchronized submission branch with [{submission.request_name}]({link}).'
            ])
            submission_message = git_tools.tag_message(
                submission.repo_remote_tag,
                default_to_commit_message = False,
            )
            if submission_message:
                yield markdown.quote(submission_message)
        self.merge_request.notes.create({'body': markdown.join_blocks(body())})

        for outcome in self.course.config.outcomes:
            with contextlib.suppress(ValueError):
                self.merge_request.labels.remove(self.label_outcome(outcome)[0])
        self.merge_request.labels.append(self.label_waiting[0])
        self.merge_request.save()
