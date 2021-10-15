# Python scripts for course administration

This directory contains (among others) scripts to help with the following tasks:

* handling student lab group work via Chalmers GitLab,
* handling individualized online exams.

The second point is hopefully obsolete now, so this documentation focusses only on the first point.

If some parts of a script require fine-tuning for a specific course (e.g. because it contains multiple sub-courses running different labs), create a new branch for that course and make the necessary edits there.

## Requirements and access configuration

### Python

We require Python version at least 3.9.

Unless mentioned otherwise, the working directory is the folder `Lab-grading`.

Install the required packages via this command:

```
pip install -r requirements.txt
```

Create an untracked copy of `gitlab_config_personal.py.template` and remove the suffix.
We will fill in the configuration values below.

### Canvas

We require a Canvas access token.

* Log into Canvas and go to [settings](https://chalmers.instructure.com/profile/settings) (the links here are for Chalmers Canvas).
* Under **Approved Integrations** create an access token and store it under `canvas_auth_token` in `gitlab_config_personal.py`.
* Also store the access token in a file `auth_token` (this is only relevant for old scripts that do not use `gitlab_config_personal.py`).

### Chalmers GitLab

We require a Chalmers GitLab access token.

* Log into [Chalmers GitLab](https://git.chalmers.se/) by signing in with your **Chalmers Login** (we are not using login via username or email).
* Go to [Access Tokens](https://git.chalmers.se/-/profile/personal_access_tokens) in your user settings.
* Create an access token with scope `api` and store it under `private_token` in `gitlab_config_personal.py`.

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
* Download the JSON file to `google_tools/credentials.json`.
  If you choose a different location to save this file, update the configuration option `google_credentials_path` in `gitlab_config_personal.py`.

All Google resources that the scripts should be able to work on need to be shared with the service account created above.
The simplest way to do that is to share the Google Drive folder of the course with the service account.

### Git

A git installation is required.

### Java

If the robograder is activated for a lab, a recent version of Java is needed to generate reports for student submissions.
Because the students may use syntactic features added in recent versions of Java, we recommend to use the most recent version (at least 14).
We recommend to use the HotSpot implementation (by Oracle) to make sure that exception messages are compatible with what most students will see on their machine.

## Speeding up remote git access

The lab scripts will frequently interact with the repositories on Chalmers GitLab.
Under the hood, it does so by calling SSH and asking it to execute certain remote commands.

The Chalmers network limits the number of SSH connection attempts from outside to 10 per minute.
If you are running the lab scripts from outside the network, this rate limiting will make it impossible to handle all lab groups in a time efficient manner.
Even inside the network, it it not efficient to establish a new SSH connection for working with each of the many repositories in the Chalmers GitLab group.

For this reason, we recommend using connection sharing.
Add the following to your SSH configuration file (default: `.ssh/config`):

```
Hostname git.chalmers.se
ControlPath /tmp/%r@%h:%p
```

Before running the lab scripts, execute the following command and leave it running until you are finished:

```ssh -MNT git@github.com```

This will establish a single master connection that each individual remote git repository interaction will then run over.
The options mean the following:

* **M**: let this connection be the control master,
* **N**: do not execute remote command
* **T**: don't allocate terminal.

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
You need to create the three top-level groups and invite all graders to the group called *graders*.
The remaining hierarchy will be created by the lab scripts.

```
graders              # Who should be allowed to grade?
                     # Members of this group will have access to all lab groups and grading repositories.
                     # TODO: write a script function that adds or, if not possible,
                     #       sends invitation emails to all teachers in the Canvas course.

labs
  ├── 1
  │   ├──  official  # Official problem and solution repository.
  │   │              # Contains a branch 'problem' with the initial lab problem.
  │   │              # All lab group repositories are initially clones of the 'problem' branch.
  │   │              # Also contains a branch 'solution' with the official lab solution.
  │   │              # Can be created by the lab script from a given lab directory in the code repository.
  │   │              # Used by the lab script to fork the individual lab group projects.
  │   │
  │   └──  grading   # Grading repository, maintained by the lab scripts.
  │                  # Fetches the official problem and solution branches and submissions from individual lab groups.
  │                  # Contains merge commits needed to represent three-way diffs on the GitLab UI.
  │                  # The individual submissions are available as tags of the form lab-group-XX/submissionYYY.
  │                  #
  │                  # If a grader wants to work seriously with submission files, they should clone this repository.
  │                  # Example use cases:
  │                  # - cd lab2-grading
  │                  # - git checkout lab_group_13/submission1   to switch to a group's submission
  │                  # - git diff problem                        changes compared to problem
  │                  # - git diff solution                       changes compared to solution
  │                  # - git diff lab_group_13/submission0       changes compared to last submission
  │                  # - git diff problem answers.txt            changes in just one file
  ├── 2
  ...

lab-groups
  ├── 0              # A student lab group.
  │   │              # There is a script that will invite students to their group on Chalmers GitLab
  │   │              # based on which assignment group they signed up for in Canvas.
  │   │
  │   ├── lab1       # For mid-course group membership changes, membership can also
  │   │              # be managed at the project level (only for the needed students).
  │   │              # Remove them from their lab group and manually add them to the projects they should have access to.
  │   │              # Example: A student may be part of lab1 and lab2 in group 13, but lab3 and lab4 in group 37.
  │   │              #          In that case, they should neither be part of group 13 nor of group 37.
  │   │
  │   ├── lab2
  │   ├── lab3
  │   └── lab4
  ├── 1
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

### Grading on Chalmers GitLab via issues

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

The lab scripts maintain a **submission table** of submissions in needs of grading on Canvas.
This table is in the form of an html file.
The upload location can be configured.
Its parent directory should exist and be unpublished.

The submission table includes information useful to graders:
* A link to the submission (the lab repository of the group at the commit of the submission tag).
* Diffs on Chalmers GitLab between a submission, the previous submission, the original problem, the official solution.
* The number of previous attempts.
  The previous grader and a link to their evaluation.
* A link to the robograder's evaluation of the submission.
  This is in form of an issue created by the robograder in the grading repository, only visible to graders.
  If a lab group has not run the robograder themselves, graders may find it useful to copy fragments of the robograder's evaluation into their own grading feedback.
* The submission message, if any.

We recommend including the submission table in the grading information module.
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
Thus, when the lab scripts upload a new submission table, the Canvas page will reflect the update.

### Robograder

Certain labs may support a robograder.
In that case, a student group may ask that the robograder test their work before they submit it.
They do this by creating a tag in their repository on Chalmers GitLab referencing the commit they want to have tested.

The tag name must have a specific form (by default, start with 'test', e.g. 'testPlz') and is case sensitive.
Once the lab scripts detect that a robograding has been requested, it runs the robograder.
Its output is made available to the student group via a new issue in the Chalmers GitLab repository.

## Configuration

The lab scripts are configured via the file `gitlab_config.py`.
To get started, create an untracked copy of `gitlab_config_personal.py.template` and remove the suffix.
Fill in and/or change the configuration values according to your needs.

The above template configuration file includes documentation for each parameter in the form of comments.
After reading the current document, you should be able to make sense of these comments.

## Running

TODO
