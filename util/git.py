import contextlib
import copy
import datetime
import functools
import logging
import operator
import shlex
import stat
import subprocess
from enum import Enum, auto
from pathlib import PurePosixPath

import git
import gitdb

import util.general
import util.path
import util.threading


logger = logging.getLogger(__name__)

# Reference names.

refs = PurePosixPath("refs")
heads = PurePosixPath("heads")
tags = PurePosixPath("tags")
remotes = PurePosixPath("remotes")
remote_tags = PurePosixPath("remote_tags")

wildcard = "*"
head = "HEAD"
master = "master"


def remove_prefix(path, prefix, **kwargs):
    return PurePosixPath(
        **util.general.remove_prefix(path.parts, prefix.parts), **kwargs
    )


def local_ref(is_tag, reference):
    return refs / (tags if is_tag else heads) / reference


local_branch = functools.partial(local_ref, False)
local_tag = functools.partial(local_ref, True)


def qualify(remote, reference):
    return PurePosixPath(remote) / reference


def remote_ref(is_tag, remote, reference):
    return refs / (remote_tags if is_tag else remotes) / qualify(remote, reference)


def local_or_remote_ref(is_tag, remote, reference):
    """If remote is None, then we assume that the reference is local."""
    if remote is None:
        return local_ref(is_tag, reference)
    return remote_ref(is_tag, remote, reference)


remote_branch = functools.partial(remote_ref, False)
remote_tag = functools.partial(remote_ref, True)


class Namespacing(Enum):
    local = auto()
    qualified = auto()
    qualified_suffix_tag = auto()  # Hack, for now.
    remote = auto()


def namespaced_ref(is_tag, namespacing, remote, reference):
    if namespacing in [Namespacing.qualified, Namespacing.qualified_suffix_tag]:
        reference = qualify(remote, reference)
        if namespacing == Namespacing.qualified_suffix_tag:
            reference = reference / "tag"
    return local_or_remote_ref(
        is_tag, remote if namespacing == Namespacing.remote else None, reference
    )


namespaced_branch = functools.partial(namespaced_ref, False)
namespaced_tag = functools.partial(namespaced_ref, True)


def normalize_branch(repo, branch):
    """
    Construct a head in the given repository from a given branch name.

    Arguments:
    * repo: Instance of git.Repository.
    * branch:
        An instance of git.Head, PurePosixPath, or str describing the branch.
        All paths are interpreted relative to refs / heads.

    Returns an instance of git.Head.
    This method will not raise an exception if the tag does not exist.
    """
    if isinstance(branch, git.Head):
        return branch
    branch = PurePosixPath(branch)
    return git.Head(repo, str(refs / heads / branch))


# Commits.


def commit_date(commit):
    return datetime.datetime.fromtimestamp(commit.committed_date).astimezone()


def find_unique_ancestor(repo, commit, ancestors):
    """
    Find out which one of the given ancestors a commit derives from.

    Arguments:
    * repo: instance of git.Repository
    * commit: whatever GitPython recognizes as a reference
    * ancestors: Dictionary valued in commits.

    Returns the unique keys of 'ancestors' whose value is the ancestor of the given commit.
    Raises UniquenessError if there is no unique such key.
    """

    def f():
        for key, ancestor in ancestors.items():
            if repo.is_ancestor(ancestor, commit):
                yield key

    return util.general.from_singleton(f())


# Tags.


def normalize_tag(repo, tag):
    """
    Construct a tag in the given repository from a given tag name.

    Arguments:
    * repo: Instance of git.Repository.
    * tag:
        An instance of git.Tag, PurePosixPath, or str describing the tag.
        All paths are interpreted relative to refs / tags.

    Returns an instance of git.Tag.
    This method will not raise an exception if the tag does not exist.
    """
    if isinstance(tag, git.Tag):
        return tag
    tag = PurePosixPath(tag)
    return repo.tag(str(tag))


def tag_exist(ref):
    """
    Test whether a reference exists.
    ref is an instance of git.Reference.
    Return a boolean. indicating whether
    """
    try:
        ref.commit  # pylint: disable=pointless-statement
        return True
    except ValueError as e:
        if str(e).endswith(" does not exist"):
            return False
        raise


def tag_message(tag, default_to_commit_message=False):
    """
    Get the message for an annotated tag.
    Returns None if the tag is not annotated unless default_to_commit_message is set.
    In that case, we return the message of the commit pointed to by the tag.
    """
    x = tag.object
    if isinstance(x, git.TagObject) or default_to_commit_message:
        return x.message
    return None


def tag_commit(tag):
    """
    Gets the commit associated to a tag reference of type git.SymbolicReference.
    Recursively resolves tag objects.
    This works around an insufficiency in git.SymbolicReference.commit for tag references.

    Arguments:
    * tag: Instance of git.SymbolicReference
    """
    return git.TagReference.commit.fget(tag)


# References.


def resolve(repo, ref):
    """
    Resolve a reference in the given repository to a commit.

    Arguments:
    * repo: Instance of git.Repository.
    * ref:
        An instance of git.Commit, git.Reference, PurePosixPath, or str describing the commit.
        All paths are interpreted absolutely with respect to the repository.

    Return an instance of git.Commit.
    Raises a ValueError is the reference cannot be resolved.
    """
    if isinstance(ref, git.Commit):
        return ref
    if not isinstance(ref, git.Reference):
        ref = git.Reference(repo, str(ref))
    return ref.commit


references_hierarchy_basic = {
    refs.name: {
        heads.name: {},
        tags.name: {},
        remotes.name: {},
        remote_tags.name: {},
    },
}


def references_hierarchy(repo):
    return util.general.expand_hierarchy(
        {PurePosixPath(ref.path): ref for ref in repo.refs},
        operator.attrgetter("parts"),
        initial_value=copy.deepcopy(references_hierarchy_basic),
    )


def flatten_references_hierarchy(ref_hierarchy):
    return util.general.flatten_hierarchy(
        ref_hierarchy, key_combine=lambda x: PurePosixPath(*x)
    )


# Refspecs


def refspec(src=None, dst=None, force=False):
    def ref_str(ref):
        return str(ref) if ref else ""

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
    fetch_refspecs: list[str] | None = None,
    push_refspecs: list[str] | None = None,
    prune=None,
    no_tags=False,
    exist_ok=False,
    overwrite=False,
):
    """
    Add a remote to a git repository.
    Bug: does not escape characters in 'remote' argument.
    """
    if fetch_refspecs is None:
        fetch_refspecs = []
    if push_refspecs is None:
        push_refspecs = []

    with repo.config_writer() as c:
        section = f'remote "{remote}"'
        if c.has_section(section):
            if overwrite:
                c.remove_section(section)
            elif not exist_ok:
                raise OverwriteException(f"remote {remote} already exists")
        c.add_section(section)
        c.add_value(section, "url", url)
        # pylint: disable-next=redefined-outer-name
        for refspec in fetch_refspecs:
            c.add_value(section, "fetch", refspec)
        # pylint: disable-next=redefined-outer-name
        for refspec in push_refspecs:
            c.add_value(section, "push", refspec)
        if prune is not None:
            c.add_value(section, "prune", boolean(prune))
        if no_tags:
            c.add_value(section, "tagopt", "--no-tags")


# Tags fetched will be prefixed by remote.
def add_tracking_remote(
    repo,
    remote,
    url,
    fetch_branches: list[str] | None = None,
    fetch_tags: list[str] | None = None,
    push_branches: list[str] | None = None,
    push_tags: list[str] | None = None,
    force=True,
    **kwargs,
):
    """
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
    """
    if fetch_branches is None:
        fetch_branches = []
    if fetch_tags is None:
        fetch_tags = []
    if push_branches is None:
        push_branches = []
    if push_tags is None:
        push_tags = []

    fetch_refspecs = [
        refspec(
            namespaced(Namespacing.local, remote, ref),
            namespaced(namespacing, remote, ref),
            force=force,
        )
        for (namespaced, namespaced_refs) in [
            (namespaced_branch, fetch_branches),
            (namespaced_tag, fetch_tags),
        ]
        for (namespacing, ref) in namespaced_refs
    ]

    push_refspecs = [
        refspec(local(ref), local(ref), force=force)
        for (local, refs) in [
            (local_branch, push_branches),
            (local_tag, push_tags),
        ]
        for ref in refs
    ]

    add_remote(repo, remote, url, fetch_refspecs, push_refspecs, **kwargs)


def onesided_merge(repo, commit, new_parent):
    return git.Commit.create_from_tree(
        repo,
        commit.tree,
        "merge commit",
        [commit, new_parent],
        author_date=commit.authored_datetime,
        commit_date=commit.committed_datetime,
    )


# Only creates a new commit if necessary.
def tag_onesided_merge(repo, tag_name, commit, new_parent):
    if not repo.is_ancestor(new_parent, commit):
        commit = onesided_merge(repo, commit, new_parent)
    return repo.create_tag(tag_name, commit)


def checkout(repo, dir, ref, capture_stderr=False):
    """Checkout a reference into the given directory."""
    cmd = ["tar", "-x"]
    with util.path.working_dir(dir):
        util.general.log_command(logger, cmd, True)
        # pylint: disable-next=R1732
        tar = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE if capture_stderr else None,
        )

    if capture_stderr:
        t = util.threading.FileReader(tar.stderr)

    repo.archive(tar.stdin, ref)
    tar.stdin.close()

    util.general.wait_and_check(
        tar,
        cmd,
        # pylint: disable-next=possibly-used-before-assignment
        stderr=t.get_result().decode() if capture_stderr else None,
    )


@contextlib.contextmanager
def checkout_manager(repo, ref):
    """Context manager for a temporary directory containing a checkout."""
    with util.path.temp_dir() as dir:
        checkout(repo, dir, ref)
        yield dir


def format_entry(entry, as_log_message=False):
    """
    Formats a triple (binsha, mode, name) as a non-terminated string for use with git mktree.
    If as_log_message is set, shell-escapes the name.
    """
    (binsha, mode, name) = entry
    hexsha = gitdb.util.bin_to_hex(binsha).decode()
    kind = {
        stat.S_IFREG: "blob",
        stat.S_IFDIR: "tree",
    }[stat.S_IFMT(mode)]
    # The last whitespace is a tab character.
    return f"{mode:06o} {kind} {hexsha}	{name if as_log_message else util.path.format_path(name)}"


def create_blob_from_file(repo, file):
    """
    Loads a blob for the given file into the given repository.
    Returns an instance of git.Blob.
    """
    hexsha = repo.git.hash_object(file, "-w", "--no-filters")
    binsha = gitdb.util.hex_to_bin(hexsha)
    return git.Blob(repo, binsha, mode=file.stat().st_mode)


def create_tree_from_entries(repo, entries):
    """
    Creates a tree for the given entries in the given repository.
    Entries is an iterable of triples (binsha, mode, name).
    Returns an instance of git.Tree.
    """
    process = repo.git.mktree(
        "-z",
        istream=subprocess.PIPE,
        as_process=True,
        universal_newlines=True,
    )
    (out, err) = process.communicate(
        util.general.join_lines(map(format_entry, entries), terminator="\0")
    )
    if process.returncode:
        raise git.GitCommandError(
            shlex.join(process.args), process.returncode, out, err
        )
    binsha = gitdb.util.hex_to_bin(out.strip())
    return git.Tree(repo, binsha)


def create_tree_from_dir(repo, dir):
    """
    Loads a tree for the given directory into the given repository.
    This loads blobs for all contained files and recursively
    loads trees for the contained directories.
    Returns an instance of git.Tree.

    TODO:
    Currently, this implementation does one process call per descendant of dir.
    If performance becomes an issue, we can switch to batch calls
    of git hash-object and git mktree.
    """

    def entries():
        for path in dir.iterdir():
            if path.is_file():
                obj = create_blob_from_file(repo, path)
            elif path.is_dir():
                obj = create_tree_from_dir(repo, path)
            else:
                raise ValueError(
                    f"not a file or directory: {util.path.format_path(path)}"
                )
            yield (obj.binsha, obj.mode, path.name)

    return create_tree_from_entries(repo, entries())


def read_text_file_from_tree(tree, path):
    path = str(PurePosixPath(path))
    return tree[path].data_stream.read().decode()


def merge_blobs(
    repo: git.Repo,
    base: git.objects.Blob,
    current: git.objects.Blob,
    other: git.objects.Blob,
    *merge_file_options,
) -> git.objects.Blob:
    with util.path.temp_dir() as tmp_dir:
        file_current = tmp_dir / "current"
        file_base = tmp_dir / "base"
        file_other = tmp_dir / "other"

        file_current.write_bytes(current.data_stream.read())
        file_base.write_bytes(base.data_stream.read())
        file_other.write_bytes(other.data_stream.read())

        repo.git.merge_file(
            *merge_file_options,
            "--",
            file_current,
            file_base,
            file_other,
        )
        result = create_blob_from_file(repo, file_current)
        result.path = current.path
        return result


def resolve_unmerged_blobs(repo, index, *merge_file_options):
    index.resolve_blobs(
        merge_blobs(repo, base, current, other, *merge_file_options)
        for (
            filename,
            ((_, base), (_, current), (_, other)),
        ) in index.unmerged_blobs().items()
    )


def get_root_commit(commit):
    while commit.parents:
        commit = commit.parents[0]
    return commit


@contextlib.contextmanager
def with_tag(repo, path, ref, message=None):
    tag = repo.create_tag(path=path, ref=ref, message=message)
    try:
        yield tag
    finally:
        repo.delete_tag(tag)
