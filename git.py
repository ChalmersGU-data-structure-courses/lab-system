from enum import Enum, auto
import git
from pathlib import PurePosixPath

import general

# References

refs = PurePosixPath('refs')
heads = PurePosixPath('heads')
tags = PurePosixPath('tags')
remotes = PurePosixPath('remotes')
remote_tags = PurePosixPath('remote_tags')
wildcard = '*'

def remove_prefix(path, prefix, **kwargs):
    return PurePosixPath(**general.remove_prefix(path.parts, prefix.parts), **kwargs)

def local_branch(branch):
    return refs / heads / branch

def local_tag(tag):
    return refs / tags / tag

def remote_branch(remote, brach):
    return refs / remotes / remote / branch

def remote_tag(remote, tag):
    return refs / remote_tags / remote / tag

class Namespacing(Enum):
    local = auto()
    remote = auto()

def namespaced_branch(remote, branch, namespacing):
    return {
        Namespacing.local: local_branch(branch),
        Namespacing.remote: remote_branch(remote, branch),
    }[namespacing]

def namespaced_tag(remote, tag, namespacing):
    return {
        Namespacing.local: local_tag(tag),
        Namespacing.remote: remote_tag(remote, tag),
    }[namespacing]

resolve_ref = lambda repo, ref: git.refs.reference.Reference(repo, ref).commit

# Refspecs

def refspec(src = None, dst = None, force = False):
    def ref_str(ref):
        return str(ref) if ref else ''

    return f'{"+" if force else ""}{ref_str(src)}:{ref_str(dst)}'

# Other stuff

def boolean(x):
    return str(bool(x)).lower()

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
            else:
                assert exist_ok, "section {} exists".format(section)
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
    fetch_branches_namespacing = Namespacing.local
    fetch_tags = [],
    fetch_tags_namespacing = Namespacing.local
    push_branches = [],
    push_tags = [],
    force = True,
    **kwargs
):
    '''
    Add a tracking remote to a git repository.
    This sets up fetch tracking of branches and tags according to the given parameters.
    For fetched references, there are two namespacing options:
    * Namespacing.local: let local references mirror the remote ones,
    * Namespacing.remote: put remote references in their own 'refs' namespace
                          ('remotes' for branches and 'remote-tags' for tags).
    To fetch or pull all branches or tags, give an argument of [wildcard].
    '''

    fetch_refspecs = [refspec(
        namespaced(remote, wildcard, Namespacing.local),
        namespaced(remote, wildcard, fetch),
        force = force,
    ) for (namespaced, option) in [
        (namespaced_branch, fetch_branches),
        (namespaced_tag, fetch_tags),
    ]]

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
