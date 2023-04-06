# TODOs

* Generate live submissions table as static site on Chalmers GitLab Pages.

* Do per group caching of remote_tags.

* Cache resolved commits in group_project.

* Fix configure_student_project method:
  make it use the request handlers of the lab config.

* Write standard request handlers.

* Retrieve Chalmers GitLab username from CID as local part of email address via LDAP.
  Add filesystem cache for this.

* Manage invitations/adding/removal of group/project members for membership that changes over the course.

* Cache created webhooks on Chalmers GitLab on local filesystem.

* High-level support for adding groups while labs are running.

* Support deletion of groups while labs are running.

* Compute web_url attribute of lazy GitLab project objects.

* Run ssh -MNT git@git.chalmers.se in a way where we wait for the master control socket has been established.
  Make the ssh call part of the script.

* Check whether javac source is smart enough to update also source dependencies if their class file is out-of-date.
  Update robograder compilation accordingly.

* Add use_cache flag to more commands.

* Improve check if hotfix has already been applied in group_project.hotfix.
  We can just look in the ancestor commits for a commit with the same metadata what would be created by applying the hotfix.
  (Currently, we try to compare files.)

* Add option to hotfix method that notifies the students in the lab group.
  For example, we could mention their usernames in a comment to the hotfix commit.
  Even better: could associate this comment with specific files in the hotfix commit.
  Could take an dictionary of messages as argument indexed by files changed in the hotfix.
  Think more about this.
  Could suppress message (or add alternative message) if file-based merge was not needed.

* Add layered caching for retrieving all users from Chalmers GitLab.
  On refresh, only need to retrieve new users.
  Can use pagination?

* Allow for more flexible hierarchies on Chalmers GitLab.
  It should be possible for some labs to use personal projects and for other labs to use group-based projects.
  Move from group membership to per-lab membership to simplify things?

* Allow for test output/report to be saved either in the global grading repository or in the student project grade repository.
  In the latter case, reference test reports in submission synchronization comments.

* Add event for synchronizing group membership from Canvas.
  Then no separate invitation script is necessary.
  By default, this affects exactly the current lab.
  Can make this layered events where the deeper layer refreshes course data on Canvas (people info).
  Or course data refresh could be triggered by encountering unknown students in a group.

* Make use of context managers for validity of cache entries more often.
  See GradingViaMergeRequest.notes_suppress_cache_clear.

* Represent student grading repositories locally using the grading repository?
  May be wasteful to use a different local repository for each group.
  Also harder to parallelize.

* Figure out how to do random sampling of webhooks for student grading projects.
  Currently, we first get all student grading projects, which is too expensive.
  In the long term, we could investigate a context manager that catches GitLab errors for missing projects and creates them on-demand.

* Investigate if we can benefit from [object pooling when forking](https://docs.gitlab.com/ee/development/git_object_deduplication.html)
  - When forking from a non-private repository, a pool is created even when the forked repository is private.
  - Commits made to the source repository are availale (after housekeeping to update the pool repository) also in the forked repository -/commit/<hash>.
  - Pushing such a commit to the forked repository still results in the redundant objects being sent (which are then deleted after housekeeping).
  - Switching the source repository to private prevents the pool from being updated (triggered by housekeeping).
  - Switching the source repository back to non-private allows housekeeping to update the pool once again.
  - Forks created while the source repository was private do not partake in the pool.
  - Merge requests can be made between sibling forks.
  - It is unclear how the project storage statistics works in the presence of pooling.
  - The resource information seen when pushing (e.g. remote: MAX: 1000000, CURRENT: 124) seems to count only the local repository, excluding the pool.

* Make use of project activity history to find out when a submission tag was created.

* Use GraphQL for faster information retrievel
  - Canvas
  - Chalmers GitLab
  Caveats (GitLab):
  - nested pagination
  - some features not available (e.g. resource label events)

* Find out how the web interface of project settings on GitLab manages to change settings we cannot change using the API.

* Keep a record of group membership changes.
  That way, we can detect if a student uses the membership mirror to glance at another group's solution.

* Find out how to use GU LDAP.

## Grading sheet

* Support the "Notes" field in the grading sheet.
  Automatically add and remove notes for empty groups.

* Update grading sheet correctly if grading issues are deleted.

* Implement group-specific incremental updates of grading sheet.
  Could be dangerous if row structure has been altered.
  So maybe not a good idea.

## Live submissions table

* Perhaps merge problem and solution comparison column in live submissions table.

* Display default sorting in live submissions table.

* Allow hiding of columns in live submissions table (user interface).

## Robograder

* Update robograder for autocomplete lab to not test with negative weights.

* Construct only one instance of the Robograder (if it esists) and pass it to the lab handlers.

## Proot

* Find the cause of the following bug.
  When running the command line
    proot -r /root -w /jail/main -b '/bin:/bin!' -b '/lib64:/lib64!' -b '/lib:/lib!' -b '/usr/bin:/usr/bin!' -b '/usr/lib64:/usr/lib64!' -b '/usr/lib:/usr/lib!' -b '/home/noname:/jail/main!'
  the directory /bin is copied as /bin *and* /jail/bin.

## Grading via merge request

* Investigate why students often don't get added to grading merge requests on their submission (TDA283).
