# TODOs

* Generate live submissions table as static site on Chalmers GitLab Pages.

* Do per group caching of remote_tags.

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

## Proot

* Find the cause of the following bug.
  When running the command line
    proot -r /root -w /jail/main -b '/bin:/bin!' -b '/lib64:/lib64!' -b '/lib:/lib!' -b '/usr/bin:/usr/bin!' -b '/usr/lib64:/usr/lib64!' -b '/usr/lib:/usr/lib!' -b '/home/noname:/jail/main!'
  the directory /bin is copied as /bin *and* /jail/bin.

