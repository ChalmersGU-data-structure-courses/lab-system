import contextlib
from enum import Enum, auto
import functools
import git
import logging
from pathlib import PurePosixPath, Path
import subprocess
import tempfile

import general

logger = logging.getLogger(__name__)

# References

refs = PurePosixPath('refs')
heads = PurePosixPath('heads')
tags = PurePosixPath('tags')
remotes = PurePosixPath('remotes')
remote_tags = PurePosixPath('remote_tags')

wildcard = '*'
head = 'HEAD'
master = 'master'

def remove_prefix(path, prefix, **kwargs):
    return PurePosixPath(**general.remove_prefix(path.parts, prefix.parts), **kwargs)

def local_ref(is_tag, reference):
    return refs / (tags if is_tag else heads) / reference

local_branch = functools.partial(local_ref, False)
local_tag = functools.partial(local_ref, True)

def qualify(remote, reference):
    return PurePosixPath(remote) / reference

def remote_ref(is_tag, remote, reference):
    return refs / (remote_tags if is_tag else remotes) / qualify(remote, reference)

def local_or_remote_ref(is_tag, remote, reference):
    '''If remote is None, then we assume that the reference is local.'''
    if remote == None:
        return local_ref(is_tag, reference)
    return remote_ref(is_tag, remote, reference)

remote_branch = functools.partial(remote_ref, False)
remote_tag = functools.partial(remote_ref, True)

class Namespacing(Enum):
    local = auto()
    qualified = auto()
    remote = auto()

def namespaced_ref(is_tag, namespacing, remote, reference):
    if namespacing == Namespacing.qualified:
        reference = qualify(remote, reference)
    return local_or_remote_ref(is_tag, remote if namespacing == Namespacing.remote else None, reference)

namespaced_branch = functools.partial(namespaced_ref, False)
namespaced_tag = functools.partial(namespaced_ref, True)

resolve_ref = lambda repo, ref: git.refs.reference.Reference(repo, ref).commit

# Refspecs

def refspec(src = None, dst = None, force = False):
    def ref_str(ref):
        return str(ref) if ref else ''

    return f'{"+" if force else ""}{ref_str(src)}:{ref_str(dst)}'

# Other stuff

def boolean(x):
    return str(bool(x)).lower()

class OverwriteException(IOError):
    pass

def add_remote(
    repo,
    remote,
    url,
    fetch_refspecs = [],
    push_refspecs = [],
    prune = None,
    no_tags = False,
    exist_ok = False,
    overwrite = False
):
    '''
    Add a remote to a git repository.
    Bug: does not escape characters in 'remote' argument.
    '''

    with repo.config_writer() as c:
        section = 'remote "{}"'.format(remote)
        if c.has_section(section):
            if overwrite:
                c.remove_section(section)
            elif not exist_ok:
                raise OverwriteException(f'remote {remote} already exists')
        c.add_section(section)
        c.add_value(section, 'url', url)
        for refspec in fetch_refspecs:
            c.add_value(section, 'fetch', refspec)
        for refspec in push_refspecs:
            c.add_value(section, 'push', refspec)
        if prune != None:
            c.add_value(section, 'prune', boolean(prune))
        if no_tags:
            c.add_value(section, 'tagopt', '--no-tags')

# Tags fetched will be prefixed by remote.
def add_tracking_remote(
    repo,
    remote,
    url,
    fetch_branches = [],
    fetch_tags = [],
    push_branches = [],
    push_tags = [],
    force = True,
    **kwargs
):
    '''
    Add a tracking remote to a git repository.
    This sets up fetch tracking of branches and tags according to the given parameters.
    Specified fetched references are lists of pairs where:
    * the first component specifies the namespacing:
      - Namespacing.local: let local references mirror the remote ones,
      - Namespacing.qualified: put remote references in their corresponding local namespace,
                               but qualify them by their remote,
      - Namespacing.remote: put remote references in their own 'refs' namespace
                            ('remotes' for branches and 'remote-tags' for tags).
    * the second component gives the reference.
    For example, to fetch or pull all branches, use wildcard as reference.
    '''

    fetch_refspecs = [refspec(
        namespaced(remote, Namespacing.local, ref),
        namespaced(remote, namespacing, ref),
        force = force,
    ) for (namespaced, namespaced_refs) in [
        (namespaced_branch, fetch_branches),
        (namespaced_tag, fetch_tags),
    ] for (namespacing, ref) in namespaced_refs]

    push_refspecs = [refspec(local(ref), local(ref), force = force) for (local, refs) in [
        (local_branch, push_branches),
        (local_tag, push_tags),
    ] for ref in refs]

    add_remote(
        repo,
        remote,
        url,
        fetch_refspecs,
        push_refspecs,
        **kwargs
    )

def onesided_merge(repo, commit, new_parent):
    return git.Commit.create_from_tree(
        repo,
        commit.tree,
        'merge commit',
        [commit, new_parent],
        head = False,
        author_date = commit.authored_datetime,
        commit_date = commit.committed_datetime,
    )

# Only creates a new commit if necessary.
def tag_onesided_merge(repo, tag, commit, new_parent):
    if not repo.is_ancestor(new_parent, commit):
        commit = onesided_merge(repo, commit, new_parent)
    return repo.create_tag(tag, commit)

def checkout(repo, dir, ref):
    ''' Checkout a reference into the given directory. '''
    cmd = ['tar', '-x']
    with general.working_dir(dir):
        general.log_command(logger, cmd, True)
        tar = subprocess.Popen(cmd, stdin = subprocess.PIPE)
    repo.archive(tar.stdin, ref)
    tar.stdin.close()
    general.wait_and_check(tar, cmd)

@contextlib.contextmanager
def checkout_manager(repo, ref):
    ''' Context manager for a temporary directory containing a checkout. '''
    with tempfile.TemporaryDirectory() as dir:
        dir = Path(dir)
        checkout(repo, dir, ref)
        yield dir
