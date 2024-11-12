# Development model

Develop new features on a feature branch and create a merge request into main.

Fixes can be directly comitted to `main`.
Use a merge request instead when you want to have feedback.

If you are looking for issues to start with, search for the label [*good first issue*](https://github.com/ChalmersGU-data-structure-courses/lab-system/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22+).
Note that the codebase still has lots of TODOs that have not been converted to issues.

# Deployment

Each instances of the lab server uses its own deployment branch, for example `2024-lp2`.
The merge direction is from `main` into these deployment branches.
If a new feature or fix is needed on a deployment branch, but previous commits on main should be ignored, you can do one of the following:
* Merge the part of the history of `main` that is to be ignored into the deployment branch into using `git merge -s ours`.
* Cherry pick the needed commits directly to the deployment branch..

# Python code style

## Black

We use [Black](https://github.com/psf/black) to format our code:

```
black <Python files>
```

## isort

We use [isort](https://pycqa.github.io/isort/) to format import blocks:

```
isort --profile black <Python files>
```

## Before committing

Make sure your code is formatted using the above tools.
For example, you can install a pre-commit hook.
