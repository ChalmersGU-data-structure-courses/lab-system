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

### Git

A git installation is required.

### Java

The robograder needs a recent version of Java to generate reports for student submissions.
Because the students may use syntactic features added in recent versions of Java, we recommend to use the most recent version (at least 14).
We recommend to use the HotSpot implementation (by Oracle) to make sure that exception messages are compatible with what most students will see on their machine.

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

### Configuration

TODO
