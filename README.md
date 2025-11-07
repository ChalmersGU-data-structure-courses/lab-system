# Python scripts for course administration

This directory contains scripts to help with running student labs on Canvas and GitLab instances.

## Requirements and access configuration

### Python

We require Python version at least 3.12.

Unless mentioned otherwise, the working directory is the folder of this file.

Install the required packages via this command:
```
pip install -e .
```

Create an untracked copy of `template/secrets.toml` in the working directory.
This file stores personal configuration such as access keys.
We will fill in the configuration values below.

### Canvas

We require a Canvas access token.

* Log into Canvas and go to [settings](https://chalmers.instructure.com/profile/settings) (the links here are for Chalmers Canvas).
* Under **Approved Integrations** create an access token and store it under `[canvas] auth_token` in `secrets.toml`.
* The user providing the access token needs to be enrolled in the course's Canvas as "Examiner".

### Chalmers GitLab

We require a Chalmers GitLab access token.

* Log into [Chalmers GitLab](https://git.chalmers.se/) by signing in with your **Chalmers Login** (we are not using login via username or email).
* Go to [Access Tokens](https://git.chalmers.se/-/profile/personal_access_tokens) in your user settings.
* Create an access token with scope `api` and store it under `[gitlab] private_token` in `secrets.toml`.

We also require that SSH can connect without interactive authentication to Chalmers GitLab.
For this, go to [SSH Keys](https://git.chalmers.se/-/profile/keys) in your user settings and upload your public SSH key.

### Google

We do integration with Google Sheets etc., we use a Google Cloud project with service account.

* Go to [Google Cloud Platform](https://console.cloud.google.com/) and create a project.
  Alternatively, join an existing project like this and skip to the last step.
* Under **APIs & Services**, click on **enables APIs and services** and enable the following APIs:
  - Google Drive API
  - Google Sheets API
  - Google Docs API
* Under **IAM & Admin** and **Service Accounts**, create a service account.
  Note that email address of the account.
  You will need this to share Google Cloud resources with it.
* On the newly created service account, select **Manage keys** and create a new key in the default JSON format.
* Open the JSON file and copy its values to the section `[google.credentials]` in `secrets.toml`.

All Google resources that the scripts should be able to work on need to be shared with the service account created above.
The simplest way to do that is to share the Google Drive folder of the course with the service account.

### Git

A git installation is required.

### Java

If the robograder is activated for a lab, a recent version of Java is needed to generate reports for student submissions.
Because the students may use syntactic features added in recent versions of Java, we recommend to use the most recent version (at least 14).
We recommend to use the HotSpot implementation (by Oracle) to make sure that exception messages are compatible with what most students will see on their machine.

## Sped up remote git access

The lab scripts frequently interact with the repositories on Chalmers GitLab.
Under the hood, it does so by calling SSH and asking it to execute certain remote commands.

The Chalmers network limits the number of SSH connection attempts from outside to 10 per minute.
If you are running the lab scripts from outside the network, this rate limiting will make it impossible to handle all lab groups in a time efficient manner.
Even inside the network, it it not efficient to establish a new SSH connection for working with each of the many repositories in the Chalmers GitLab group.

For this reason, the lab system uses connection sharing under the hood.
This corresponds to using the following SSH configuration options:

```
Host git.chalmers.se
ControlPath /tmp/%r@%h:%p
```

and running the following command in the background:

```
ssh -MNT git@github.com
```

This will establish a single master connection that each individual remote git repository interaction then runs over.
The options mean the following:

* **M**: let this connection be the control master,
* **N**: do not execute remote command,
* **T**: do not allocate a terminal.

Sometimes, the Python monitoring library (`watchdog`) we use to watch for changes of the master connection bugs out.
This does not seem to impacted the running of the system so far.
(TODO: investigate.)

## A note on Canvas caching

The scripts will locally cache read accesses to the Canvas course (e.g. student data, group membership) that are not expected to change frequently.
The default location for this is `cache`.
Delete this after the course is over to comply with GDPR.

Many script functions take an argument `use_cache`, which often defaults to `True`.
If you find that information handled by the script is no longer up to date, you can:

* perform the `use_cache = False`, which will refresh the values stored in the cache,
* or delete the cache directory, leading to it being lazily regenerated.

## Features

### Chalmers GitLab group structure

The following is an overview of the group structure on Chalmers GitLab.
The location and path name of the graders and lab group is configurable.
There are functions in the `Course` and `Lab` classes to create the groups below.
Alternatively, you can create them yourself.

```
graders                 # Who should be allowed to grade?
                        # You need to add this group as a group member to the group for this course instance.
                        # It suffices to add it with developer rights.
                        # Every member will then have access to all subgroups and projects of this course instance on GitLab.
                        # The lab system has functionality for automatically adding teachers and TAs on Canvas to this group.

example-lab
  ├── primary           # Primary project containing the problem branch (or branches if lab has multiple versions, e.g. for different languages).
  │                     # The lab system forks all student projects from this project.
  │                     # So make sure that it is to your liking before that happens.
  │                     # The main branch should point to the problem branch that should be the default.
  │                     # If students want to work with another problem, they need to do one of the following:
  │                     # * reset (and force push) the main branch to that problem,
  │                     # * create their own branch from the desired problem.
  │
  ├── collection        # Collection repository, written to by the lab scripts.
  │                     # Fetches from the primary project and solution and student projects.
  │                     # The individual submissions are available as tags of the form group-XX/submissionYYY/tag.
  |                     # This repository contains all the data produced by the lab system when processing submissions.
  |                     # This includes robograding and test reports (if configured), for example under group-XX/submissionYYY/test_report.
  |
  ├── solution          # Official solution project (only if the lab has a solution).
  │                     # This counts as a student project for many purposes.
  │                     # It must have official solution submissions (for all lab versions).
  │                     # These are made in the same way as in a student project.
  │                     # Student submissions are diffed against the submissions in this project.
  |                     # Submission testers may use these to produce gold outputs.
  |
  ├── student-project   # Example student project.
  |                     # If this is an individual lab, the respective student should be a developer member.
  |                     # If this is a group lab, the all students in the group should be developer members.
  |                     # The lab system has Canvas sync functionality for syncing these memberships from Canvas.
  |                     # For group labs, it is usually desirable to activate this only for the current lab.
  |                     # That way, project membership for older labs is unaffected if students move between groups on Canvas.
  |                     # Also, you can move students between projects manually only possible if sync is disabled.
  |                     # Otherwise, the lab system would revert your changes the next time the sync happens.
  ...
```

Repositories in a GitLab group are also called *projects* by GitLab.

### Submission on Chalmers GitLab via tags

We use Chalmers GitLab for submission and grading.

To submit, a group creates a **tag** in their repository that references a specific commit.
They can do this in two ways:
* They create the tag locally in their Git repository and then push it to Chalmers GitLab.
* They go the project overview page on Chamers GitLab, click on the "**+**" button, and select **New tag**.

The tag name must have a specific form (by default, start with `submission`, e.g. `submission2`) and is case sensitive.
The (optional) tag message serves as submission message.

The tag is *protected*: it cannot be changed or deleted once it has been created (the same applies to the commit it references).
Thus, the tag serves as proof of submission.

*Note*: Some groups confuse tags with commit and create a commit with the intended tag name as commit message.
TODO: automatically detect these cases and omit warnings.

If the lab uses multiple problems (e.g. for different languages), the lab system relies on the commit graph to figure out which problem a submission relates to.

### Grading on Chalmers GitLab via merge requests

Once the lab system has processed a submission, it will create a *grading merge request* in the student project.
This will show the changes made in the submission over the lab problem.

The students will be notified on creation of the merge request.
This serves as confirmation that the lab system has recognized their submission.

The status of the grading is recorded in the merge request.
Its description contains a summary table of all past submission attempts.
A label record the status of the current submission.
The special label waiting-for-grading is used for submissions that await grading.

The lab system only recognizes label changes made by graders.
However, it can be confusing for people viewing the merge request when the students change the labels.
For that reason, the merge system can detect this situation and will then annotate the merge request description with a prominent warning.

### Grading on Chalmers GitLab via issues (outdated)

**Deprecated: consider using grading merge requests instead.**

We use **issues** on Chalmers GitLab to grade submissions.

Suppose a grader has gone over a submission in a project of a group (as identified by a tag as above).
They then go to the project page and create an issue (go to **Issues** and click on **New issue**) to record their evaluation.

The title of the issue needs to follow a certain pattern, by default:
> Grading for submission-whatever: complete/incomplete

The body is free form and should be used to give detailed feedback to the students.
The graders are encouraged to use Markdown formatting to format lists and code blocks.
If students did not subscribe to notification emails from Chalmers GitLab for new issues in their project, their usernames should be included in the issue body (e.g. *@student0 @student1*) to force notifications emails.

Students may engage in discussions with their grader via the discussion thread of their grading issue, for example to request clarification.
This possibility should be highlighted to the students.
Student engangement should benefit from having a two-way grading communication channel.
The graders should be reminded to have notifications from Chalmers GitLab enabled (the default notification settings will work).

Grading issues, recognized only by members of the *graders* group, serve as the official database of grading outcomes.
It follows that you may change a grading by editing the corresponding grading issue.

The lab scripts will output warnings if it detects grader-created issues whose title does not follow the standard pattern.
Common mistakes include typos and incorrect capitalization when referencing the (case-sensitive) tag.

### Collection repository

The lab system writes to a *collection project* on Chalmers GitLab.

This contains:
* branches for the lab problems (e.g. `problem` or `java`/`python`).
* all submissions from all groups, under tags `group-XX/submissionYYY/tag`,
* the official solution submissions (e.g., `solution/submission-python`),
* all robograding/robotesting output (e.g., `group-XX/submissionYYY/test_report`).

The lab system uses this project to provide diff views on Chalmers GitLab linked to in the live submissions table (e.g., between a student submission and an official solution).

If grader need to work with the files in student submissions, they can simply clone this repository.
They can then use the usual git commands, for example:
* checking out a group's submission: `git checkout group-13/submissionSecond/tag`
* checking what they did: `git diff problem`
* showing the changes relative to the previous submission: `git diff group-13/submissionFirst/tag`
* comparing to the official solution: `git diff solution`
* checking out the compilation and robograding report (if available): `git checkout group-13/submissionSecond/report`

### Grading sheets on Google Cloud

We use Google Sheets to synchronize the grading and keep track of grading outcomes.
Their purpose is two-fold:
* The lab scripts maintains grading outcomes and links to grading issues in the grading sheet.
  This gives an overview of the grading progress.
  It also allows graders to easily find their own previous grading issues (e.g. to copy text fragments) and see how other graders are working.
* Before grading a (bunch of) submission(s), graders should be encouraged to write down their name in the grading sheet for the submissions they intend to grade.
  This helps avoid grading conflicts.
  Once it detects that a grader has created a grading issue on Chalmers GitLab, it fill record the grading outcome and link to the grading issue in the sheet.
  (In particular, the grader does *not* have to do this.)

The grading sheet is **not** the official database of which groups have passed which labs.
It merely reflects the grading issues on Chalmers GitLab.
It is purely informational.
It can also be used to collect notes and comments.

It is convenient to use a single Sheet document with one worksheet for each lab.
It is initially created by the course-responsible.
You may do so by copying [this template](https://docs.google.com/spreadsheets/d/1phOUdj_IynVKPiEU6KtNqI3hOXwNgIycc-bLwgChmUs).
It includes conditional formatting that helps you easily identify groups in need of grading and groups that have passed.
Delete unneeded rows and column groups.
Duplicate the included worksheet as needed (e.g., *Lab 1*, *Lab 2*, etc.).

### Canvas integration

We recommend creating an unpublished module (viewable only by teachers) on Canvas with grading-related information.
Here, you can record grading instructions and put the link to the grading sheet.

The lab scripts maintain a **live submissions table** of submissions in needs of grading on Canvas.
This table is in the form of an html file.
The upload location can be configured.
Its parent directory should exist and be unpublished.

The live submissions table includes information useful to graders:
* A link to the submission (the lab repository of the group at the commit of the submission tag).
* Diffs on Chalmers GitLab between a submission, the previous submission, the original problem, the official solution.
* The number of previous attempts.
  The previous grader and a link to their evaluation.
* A link to the robograder's evaluation of the submission.
  This is in form of an issue created by the robograder in the collection repository, only visible to graders.
  If a lab group has not run the robograder themselves, graders may find it useful to copy fragments of the robograder's evaluation into their own grading feedback.
* The submission message, if any.

We recommend including the live submissions table in the grading information module.
It can be embedded as follows.
Create an empty page in the grading information module with appropriate title (e.g. *Lab 3: submissions awaiting grading*).
Create an empty placeholder html file in the above upload location and note its file id.
Go to the html editor for the Canvas page and paste a snippet for an iframe including the file:
```
<iframe src="https://canvas.gu.se/courses/<course id>/files/<file id>/download" width="100%" height="3000px"></iframe>
```
(It does not seem possible to set the height to the natural height of the embedded html file.
If the defined height does not suffice, an annoying scroll wheel for the iframe will appear.)

*Note*: Files overwritten by upload to the same location will not retain the old id.
However, Canvas automatically updates links to overwritten course files with the new id.
Thus, when the lab scripts upload a new submissions table, the Canvas page will reflect the update.

### Robograder and robotester

Certain labs may support a robograder or robotester.
In that case, a student group may ask that the robograder test their work before they submit it.
They do this by creating a tag in their repository on Chalmers GitLab referencing the commit they want to have tested.

The tag name must have a specific form (by default, start with 'test', e.g. 'testPlz') and is case sensitive.
Once the lab scripts detect that a robograding has been requested, it runs the robograder.
Its output is made available to the student group via a new issue in the Chalmers GitLab repository.

## Configuration

The lab scripts take as argument a configuration module.
A template for this module can be found in `gitlab_config.py.template`.
It includes documentation for each configuration parameter in the form of comments.
You should be able to follow these explanations after having read this document.

Most options have default values that are generally suitable.
Fill in and/or change them according to your needs.
Note that this is a Python file, so you may use logic to dynamically generate configuration values.

By default, personal configuration (as opposed to simply course-specific configuration) such as access keys and local directories is imported from the separate module `gitlab_config_personal.py`.
We have filled out the access key options above.
Fill out the remaining options according to their documentation.

## Performing tasks

We describe here common workflows occuring throughout a course.
We will do so at the level of an interactive Python environment.

If a particular workflow needs to executed repeatedly, it can be time-saving to save it as a Python file, for example `do_this_and_that.py`.
You can execute it using `python3 do_this_and_that.py`.
(If `python` defaults to version 3 on your system, you may also write `python` instead of `python3`.)
If you give it a header
```
#!/bin/python3
```
and executable permission, you may execute directly, e.g. `./do_this_and_that.py` in a shell.
You can also execute it in interactive mode using `python3 -i do_this_and_that.py`.

The classes relevant to our workflows are `Course` defined in `course.py` and `Lab` defined in `lab.py`.
You must import these modules before you can use these classes, e.g.
```
from course import Course
```

All functions of `Course` and `Lab` objects discussed below come with their own documentation.
This is the so-called docstring of the respective method in `course.py` and `lab.py`.
You may look it up to for example get a full explanation of possible parameters.

### Logging

The `Course` and `Lab` classes support logging.
You may pass a customized logger as constructor arguments, otherwise a default logger is used.

To globally setup logging via standard error, we do the following:
```
import logging
logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)

```
Use log level `logging.DEBUG` for more detailed log messages.
Use `logging.WARNING` if you only want to see messages for unexpected events.

### Basic setup

We initialize the course object by passing it a course configuration module derived from `gitlab_config.py.template` as described under Configuration.
We may also pass it a local directory used by some course operations to store data locally.
For example, each local git repository used by a Lab instance to manage remote repositories on GitLab Chalmers will be created as a subdirectory named according to their full id.
An example is:
```
import <your course config> as config
course = Course(config, dir = <local course directory>)
```
The dictionary `course.lab` allows you to access Lab instances according to their id, for example `course.lab[3]` for the lab with id 3.

In summary, a basic setup may look like this:
```
import logging
logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)

from course import Course
import <your course config> as config
course = Course(config, dir = <local course directory>)

```
You may wish to save this as a Python file `<my course>.py`.
To operate on the course in the future, you can then start an interpreter with `python -i <my course>.py` with the object `course` preloaded.

The Python interpreter supports autocompletion.
To get help on (e.g., course or lab) function `f`, run `help(f)`.

### Adding graders on GitLab

To add or invite teachers from Canvas to the GitLab graders group, run:
```
course.add_teachers_to_gitlab()
```
Every examiner, teacher, and teaching assistant on Canvas counts as a teacher in this context.
You can run this method repeatedly to add teachers who arrive on Canvas later.
The lab system now calls this method automatically when it syncs with Canvas.

### Creating labs on GitLab

Suppose we want to create on GitLab the lab with id 3.
Let us select this lab as a variable:
```
lab = course.labs[3]
```

Let us first assume that you are deploying a lab with default locations for problems and solutions.
In that case, you can deploy it to GitLab using the following all-in-one method:
```
lab.deploy_via_lab_sources_and_canvas()
```

See the rest of this section for what running this method entails.
If you need fine-tuning, you can always run each step by itself.
If you mess up, you can freshen the plate using `lab.remove(force=True)`.

---

We start by running:
```
lab.gitlab_group.create()
```
This will create the group for the lab.
Next, we run:
```
lab.primary_project.create()
lab.collection_project.create()
```
This creates the primary and collection projects, but leaves them empty.

Now you set up the primary project.
You can clone it from GitLab and push the problem branch (or branches).
Set the main branch to the default problem branch and make it the default branch.

To automate this, you can use:
```
lab.primary_project_problem_branch_create(<path to sources>, 'Initial version.')
```
The second argument will be used as commit message.

For multiple problem branches, use `lab.primary_project_problem_branches_create`.
For example:
```
lab.primary_project_problem_branches_create({
  'java': (<path to sources>, 'Initial Java version.'),
  'python': (<path to sources>, 'Initial Python version.'),
}, default='java')
```

The lab system will in any case attempt to fix problems with protected branches in forked student projects.
Infrequently, this goes wrong because of some unknown GitLab bug triggered by a race between forking and project configuration.
This can be fixed by calling
```
lab.configure_student_project(project)
```
or manually fixing the protected status.

Double-check that the official project has the correct content.
The student projects will be derived from it.

Initialize the local collection repository using
```
lab.repo_init()
```
This pulls from the official project.
You may add an argument `bare = True` to make it a so-called bare git repository.
This is useful for automated task that don't need a repository with an actual working directory.

If you have official solutions, You may now want ask the to create the solutions project:
```
lab.create_group('solution')
```
and upload the official solutions as tags.
You can do all of that in one step using:
```
lab.solution_create_and_populate()
```
If your solutions are in non-standard locations, you can use `lab.group['solution'].upload_solution`.

### Mirroring group category on GitLab

Suppose you have configured the group set for a lab (or designated it as an individual lab).
Then you may create the corresponding student projects on GitLab by calling:
```
lab.groups_create_desired()
```
You can call this method repeatedly.
Unless you use non-default arguments, it will ignore existing groups.

Suppose now that students have signed up for groups or were divided into them by teachers (or the lab is individual).
Then you can add or invite students (depending on whether we recognize an account on Chalmers GitLab for them) as follows:
```
lab.sync_students_to_gitlab()
```
You may wish to call this command repeatedly over the beginning part of your course.
If students have changed group membership after the last invocation, they will be removed from their old group and added to the new one.

### Hotfixing labs

If you notice in mistake in the lab problem, but students may have already begun working on it, you can perform a *hotfix*.
Push fix commits to the problem branches in the primary project as desired.
Make sure the local repository is up to date by calling:
```
lab.repo_fetch()
```
Then hotfix the student projects using
```
lab.update_groups_problem()
lab.merge_groups_problem_into_main()
```
See the documentation of these methods for arguments you can tweak.
For example, it is possible to notify the students about this.
The lab system will only be able to hotfix groups where no merge conflicts arise.
For other groups, you have to merge your fixes into their work branch manually.
Note also that not all students are working on the main branch.
You can use `group.merge_problem_into_branch` for group-specific merges.

## Running the event loop

See `./run_event_loop -h` for now.

You may want to run this as a systemd service.
See `template/lab-system.service`.
