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

Create an untracked copy of `gitlab_config_personal.py.template` with the suffix removed.
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
If you are running the lab script from outside the network, this rate limiting will make it impossible to handle all lab groups in a time efficient manner.
Even inside the network, it it not efficient to establish a new SSH connection for working with each of the many repositories in the Chalmers GitLab group.

For this reason, we recommend using connection sharing.
Add the following to your SSH configuration file (default: `.ssh/config`):

```
Hostname git.chalmers.se
ControlPath /tmp/%r@%h:%p
```

Before running the lab script, execute the following command and leave it running until you are finished:

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

### Features

TODO

## GitLab group structure

The following is an overview of the group structure on Chalmers GitLab.
You only need to create the three top-level groups.
The remaining hierarchy will be created by scripts.


```
teachers             # Who should be allowed to grade?
                     # Members of this group will have access to all lab groups and grading repositories.
					 # There is a script function that adds or, if not possible,
					 # sends invitation emails to all teachers in the Canvas course.

labs
  ├── 1
  │   ├──  official  # Official problem and solution repository.
  │   │              # Contains a branch 'problem' with the initial lab problem.
  │   │              # All lab group repositories are initially clones of the 'problem' branch.
  │   │              # Also contains a branch 'solution' with the official lab solution.
  │   │
  │   └──  grading   # Grading repository, maintained by the lab script.
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
  ├── 0              # A student group.
  │   │              # There is a script that will invite students to their group on Chalmers GitLab
  │   │              # based on which assignment group they signed up for in Canvas.
  │   │
  │   ├── lab1       # For mid-course group membership changes, membership can also
  │   │              # be managed at the project level (only for the needed students).
  │   │              # Remove them from their lab group and manually add them to the projects they should have access to.
  │   │              # Example: lab1 and lab2 in lab-group-13, but lab3 and lab4 in lab-group-37.
  │   │
  │   ├── lab2
  │   ├── lab3
  │   └── lab4
  ├── 1
  ...
```

### Configuration

TODO
