# Copyright (C) 2007 Canonical Ltd
# Copyright (C) 2008-2009 Jelmer Vernooij <jelmer@samba.org>
# Copyright (C) 2008 John Carr
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Converters, etc for going between Bazaar and Git ids."""

import stat

from bzrlib import (
    errors,
    foreign,
    osutils,
    trace,
    urlutils,
    )
from bzrlib.inventory import (
    ROOT_ID,
    )
from bzrlib.foreign import (
    ForeignVcs, 
    VcsMappingRegistry, 
    ForeignRevision,
    )
from bzrlib.xml_serializer import (
    escape_invalid_chars,
    )

DEFAULT_FILE_MODE = stat.S_IFREG | 0644


def escape_file_id(file_id):
    return file_id.replace('_', '__').replace(' ', '_s')


def unescape_file_id(file_id):
    ret = []
    i = 0
    while i < len(file_id):
        if file_id[i] != '_':
            ret.append(file_id[i])
        else:
            if file_id[i+1] == '_':
                ret.append("_")
            elif file_id[i+1] == 's':
                ret.append(" ")
            else:
                raise AssertionError("unknown escape character %s" % file_id[i+1])
            i += 1
        i += 1
    return "".join(ret)


def fix_person_identifier(text):
    if "<" in text and ">" in text:
        return text
    return "%s <%s>" % (text, text)


def warn_escaped(commit, num_escaped):
    trace.warning("Escaped %d XML-invalid characters in %s. Will be unable "
                  "to regenerate the SHA map.", num_escaped, commit)


def warn_unusual_mode(commit, path, mode):
    trace.warning("Unusual file mode %o for %s in %s. Will be unable to "
                  "regenerate the SHA map.", mode, path, commit)


class BzrGitMapping(foreign.VcsMapping):
    """Class that maps between Git and Bazaar semantics."""
    experimental = False

    def __init__(self):
        super(BzrGitMapping, self).__init__(foreign_git)

    def __eq__(self, other):
        return type(self) == type(other) and self.revid_prefix == other.revid_prefix

    @classmethod
    def revision_id_foreign_to_bzr(cls, git_rev_id):
        """Convert a git revision id handle to a Bazaar revision id."""
        return "%s:%s" % (cls.revid_prefix, git_rev_id)

    @classmethod
    def revision_id_bzr_to_foreign(cls, bzr_rev_id):
        """Convert a Bazaar revision id to a git revision id handle."""
        if not bzr_rev_id.startswith("%s:" % cls.revid_prefix):
            raise errors.InvalidRevisionId(bzr_rev_id, cls)
        return bzr_rev_id[len(cls.revid_prefix)+1:], cls()

    def generate_file_id(self, path):
        # Git paths are just bytestrings
        # We must just hope they are valid UTF-8..
        if path == "":
            return ROOT_ID
        return escape_file_id(path)

    def parse_file_id(self, file_id):
        if file_id == ROOT_ID:
            return ""
        return unescape_file_id(file_id)

    def import_commit(self, commit):
        """Convert a git commit to a bzr revision.

        :return: a `bzrlib.revision.Revision` object.
        """
        if commit is None:
            raise AssertionError("Commit object can't be None")
        rev = ForeignRevision(commit.id, self, self.revision_id_foreign_to_bzr(commit.id))
        rev.parent_ids = tuple([self.revision_id_foreign_to_bzr(p) for p in commit.parents])
        rev.message, num_escaped = escape_invalid_chars(commit.message.decode("utf-8", "replace"))
        if num_escaped:
            warn_escaped(commit.id, num_escaped)
        rev.committer, num_escaped = escape_invalid_chars(str(commit.committer).decode("utf-8", "replace"))
        if num_escaped:
            warn_escaped(commit.id, num_escaped)
        if commit.committer != commit.author:
            rev.properties['author'], num_escaped = escape_invalid_chars(str(commit.author).decode("utf-8", "replace"))
            if num_escaped:
                warn_escaped(commit.id, num_escaped)

        if commit.commit_time != commit.author_time:
            rev.properties['author-timestamp'] = str(commit.author_time)
        if commit.commit_timezone != commit.author_timezone:
            rev.properties['author-timezone'] = "%d" % (commit.author_timezone, )
        rev.timestamp = commit.commit_time
        rev.timezone = commit.commit_timezone
        return rev


class BzrGitMappingv1(BzrGitMapping):
    revid_prefix = 'git-v1'
    experimental = False

    def __str__(self):
        return self.revid_prefix


class BzrGitMappingExperimental(BzrGitMappingv1):
    revid_prefix = 'git-experimental'
    experimental = True


class GitMappingRegistry(VcsMappingRegistry):

    def revision_id_bzr_to_foreign(self, bzr_revid):
        if not bzr_revid.startswith("git-"):
            raise errors.InvalidRevisionId(bzr_revid, None)
        (mapping_version, git_sha) = bzr_revid.split(":", 1)
        mapping = self.get(mapping_version)
        return mapping.revision_id_bzr_to_foreign(bzr_revid)

    parse_revision_id = revision_id_bzr_to_foreign


mapping_registry = GitMappingRegistry()
mapping_registry.register_lazy('git-v1', "bzrlib.plugins.git.mapping",
                                   "BzrGitMappingv1")
mapping_registry.register_lazy('git-experimental', "bzrlib.plugins.git.mapping",
                                   "BzrGitMappingExperimental")


class ForeignGit(ForeignVcs):
    """The Git Stupid Content Tracker"""

    def __init__(self):
        super(ForeignGit, self).__init__(mapping_registry)

    @classmethod
    def show_foreign_revid(cls, foreign_revid):
        return { "git commit": foreign_revid }


foreign_git = ForeignGit()
default_mapping = BzrGitMappingv1()


def text_to_blob(texts, entry):
    from dulwich.objects import Blob
    text = texts.get_record_stream([(entry.file_id, entry.revision)], 'unordered', True).next().get_bytes_as('fulltext')
    blob = Blob()
    blob._text = text
    return blob


def symlink_to_blob(entry):
    from dulwich.objects import Blob
    blob = Blob()
    blob._text = entry.symlink_target
    return blob

def mode_is_executable(mode):
    return bool(mode & 0111)

def mode_kind(mode):
    entry_kind = (mode & 0700000) / 0100000
    if entry_kind == 0:
        return 'directory'
    elif entry_kind == 1:
        file_kind = (mode & 070000) / 010000
        if file_kind == 0:
            return 'file'
        elif file_kind == 2:
            return 'symlink'
        elif file_kind == 6:
            return 'tree-reference'
        else:
            raise AssertionError(
                "Unknown file kind %d, perms=%o." % (file_kind, mode,))
    else:
        raise AssertionError(
            "Unknown kind, perms=%r." % (mode,))


def entry_mode(entry):
    if entry.kind == 'directory':
        return stat.S_IFDIR
    elif entry.kind == 'symlink':
        return stat.S_IFLNK
    elif entry.kind == 'file':
        mode = stat.S_IFREG | 0644
        if entry.executable:
            mode |= 0111
        return mode
    else:
        raise AssertionError


def directory_to_tree(entry, lookup_ie_sha1):
    from dulwich.objects import Tree
    tree = Tree()
    for name in sorted(entry.children.keys()):
        ie = entry.children[name]
        tree.add(entry_mode(ie), name.encode("utf-8"), lookup_ie_sha1(ie))
    tree.serialize()
    return tree


def inventory_to_tree_and_blobs(inventory, texts, mapping, cur=None):
    """Convert a Bazaar tree to a Git tree.

    :return: Yields tuples with object sha1, object and path
    """
    from dulwich.objects import Tree
    import stat
    stack = []
    if cur is None:
        cur = ""
    tree = Tree()

    # stack contains the set of trees that we haven't 
    # finished constructing
    for path, entry in inventory.iter_entries():
        while stack and not path.startswith(osutils.pathjoin(cur, "")):
            # We've hit a file that's not a child of the previous path
            tree.serialize()
            sha = tree.id
            yield sha, tree, cur.encode("utf-8")
            t = (stat.S_IFDIR, urlutils.basename(cur).encode('UTF-8'), sha)
            cur, tree = stack.pop()
            tree.add(*t)

        if entry.kind == "directory":
            stack.append((cur, tree))
            cur = path
            tree = Tree()
        else:
            if entry.kind == "file":
                blob = text_to_blob(texts, entry)
            elif entry.kind == "symlink":
                blob = symlink_to_blob(entry)
            else:
                raise AssertionError("Unknown kind %s" % entry.kind)
            sha = blob.id
            yield sha, blob, path.encode("utf-8")
            name = urlutils.basename(path).encode("utf-8")
            tree.add(entry_mode(entry), name, sha)

    while len(stack) > 1:
        tree.serialize()
        sha = tree.id
        yield sha, tree, cur.encode("utf-8")
        t = (stat.S_IFDIR, urlutils.basename(cur).encode('UTF-8'), sha)
        cur, tree = stack.pop()
        tree.add(*t)

    tree.serialize()
    yield tree.id, tree, cur.encode("utf-8")


def revision_to_commit(rev, tree_sha, parent_lookup):
    """Turn a Bazaar revision in to a Git commit

    :param tree_sha: Tree sha for the commit
    :param parent_lookup: Function for looking up the GIT sha equiv of a bzr revision
    :return dulwich.objects.Commit represent the revision:
    """
    from dulwich.objects import Commit
    commit = Commit()
    commit.tree = tree_sha
    for p in rev.parent_ids:
        git_p = parent_lookup(p)
        if git_p is not None:
            assert len(git_p) == 40, "unexpected length for %r" % git_p
            commit.parents.append(git_p)
    commit.message = rev.message.encode("utf-8")
    commit.committer = fix_person_identifier(rev.committer.encode("utf-8"))
    commit.author = fix_person_identifier(rev.get_apparent_authors()[0].encode("utf-8"))
    commit.commit_time = long(rev.timestamp)
    if 'author-timestamp' in rev.properties:
        commit.author_time = long(rev.properties['author-timestamp'])
    else:
        commit.author_time = commit.commit_time
    commit.commit_timezone = rev.timezone
    if 'author-timezone' in rev.properties:
        commit.author_timezone = int(rev.properties['author-timezone'])
    else:
        commit.author_timezone = commit.commit_timezone 
    return commit
