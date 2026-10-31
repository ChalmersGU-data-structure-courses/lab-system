# Working in this repository

## Setup and verification
- Use Python 3.12+ and run commands from the repository root. Install with `python -m pip install -e .`.
- There is no `lab_system` import package: setuptools installs top-level modules (`course`, `lab`, etc.) alongside explicitly listed packages in `pyproject.toml`. Update those lists when adding installable modules/packages.
- Format changed Python files with `isort <files>` then `black <files>`; `pyproject.toml` supplies the Black profile and two blank lines after imports. These tools are not installed by the project's dependencies.
- No automated test runner or CI workflow is configured. Do not blindly run test discovery: `test.py`, `grading_sheet/test.py`, and `graphql_/test.py` authenticate/contact live services at import time, and grading-sheet helpers can write remotely. Inspect scripts before running them; report which focused checks you actually performed.

## Configuration and execution
- `lab_interfaces.py` defines the configuration dataclasses and their semantics; prefer it and the CLI implementation over stale README/template examples.
- Each course directory must contain `config.py` exporting **`course`**, a `CourseConfig` instance (not `config` or `course_config`). Use `template/config.py` as a starting point; it contains unresolved `ACTION` placeholders.
- Credentials are loaded separately via `CourseAuth.from_secrets`; use the ignored root `secrets.toml` based on `template/secrets.toml`, or CLI `--auth <path>`.
- Actual CLI: `python run_event_loop.py --help`; operational invocation: `python run_event_loop.py --dir <course-dir> run`. Repeat `--dir` for multiple courses. This is not a dry run: it processes labs and can update remote projects, webhooks, memberships, and reports.
- `event_loop.run` handles course setup and initial lab processing itself; do not precede it with a separate `initial_run`. `--disable-webhooks` and `--disable-canvas-sync` disable only those features, not all remote writes.
- `prelude.py` is currently hardwired to `dat710.config` and constructs that course at module scope. Do not import/run it as a generic smoke test.

## Where behavior lives
- `course.py` coordinates course-wide integrations; `lab.py` manages lab/collection repositories; `group_project.py` models student projects and tag requests. `RequestAndResponses` is passed to request handlers in `handlers/`; `testers/` runs student submissions, not tests of this repository.
- Submissions are Git tags; processing records responses/reports in GitLab and collection-repository tags. Grading merge requests are implemented in `grading_via_merge_request.py`; README's issue-based grading section is deprecated.
- Podman testers load a lab's `tests.py` defining `tests` and overlay its `test/` directory on submissions. They require the external `podman` executable and configured images; Java grading also requires a JDK.

## Data and deployment boundaries
- Never commit credentials or student/TA personal data. `CONTRIBUTING.md` requires sensitive course configuration in separate ignored files, including on deployment branches. Canvas data is cached in ignored `cache/`; stale reads may require `use_cache=False`.
- Deployment branches receive merges **from `main`**, not the reverse; see `CONTRIBUTING.md` for the development/deployment model.
- Historical `_2020_lp2/`, `_2020_lp2_orig/`, `_2021_lp3/`, `old/`, and `chalmers_pdb/new_rpcc_client.py` are excluded from Black/isort; avoid sweeping formatting changes there.
