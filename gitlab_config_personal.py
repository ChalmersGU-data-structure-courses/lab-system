from pathlib import Path

# GitLab private token.
# Can be given as a string or as a path to a file containing it.
private_token = '7ixHy-SPhB97-SNiKBz9'

# Here is the local directory structure:
# dir_labs
# | lab #0  # Local repository for lab #0. 
# ...

# Path to local directory with labs.
# This should be an absolute path.
# Otherwise, it will be interpreted relative to the current directory.
dir_labs = Path('~/DIT181').expanduser()

# Git URL to a repository
#repo_url
