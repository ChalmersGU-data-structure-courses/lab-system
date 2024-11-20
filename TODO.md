# TODOs

* Generate live submissions table as static site on Chalmers GitLab Pages.

* Do per group caching of remote_tags.

* Cache resolved commits in group_project.

* Fix configure_student_project method:
  make it use the request handlers of the lab config.

* Write standard request handlers.

* Retrieve Chalmers GitLab username from CID as local part of email address via LDAP.
  Add filesystem cache for this.

* Cache created webhooks on Chalmers GitLab on local filesystem.

* Support deletion of groups while labs are running.

* Compute web_url attribute of lazy GitLab project objects.

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

* Allow for test output/report to be saved either in the collection repository or in the student project grade repository.
  In the latter case, reference test reports in submission synchronization comments.

* Make use of context managers for validity of cache entries more often.
  See GradingViaMergeRequest.notes_suppress_cache_clear.

* Figure out how to do random sampling of webhooks for student grading projects.
  Currently, we first get all student grading projects, which is too expensive.
  In the long term, we could investigate a context manager that catches GitLab errors for missing projects and creates them on-demand.

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

* Allow hiding of columns in live submissions table (user interface).

## Robograder

* Update robograder for autocomplete lab to not test with negative weights.

* Construct only one instance of the Robograder (if it esists) and pass it to the lab handlers.
