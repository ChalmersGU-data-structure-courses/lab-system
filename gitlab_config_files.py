from pathlib import Path

# Here is the local directory structure:
# dir_labs
# | lab #0  # Local repository for lab #0. 
#           # Branches:
#             * lab_problem
#             * lab_solution
#             * branch_from_tag(n, tag)
#             ...
# ...

# Path to local directory with labs.
# This should be an absolute path.
# Otherwise, it will be interpreted relative to the current directory.
dir_labs = Path('~/DIT181').expanduser()
