# Copyright (C) 2007-2008 Canonical Ltd
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

from bzrlib import errors, foreign, urlutils
from bzrlib.inventory import ROOT_ID
from bzrlib.foreign import (
        ForeignVcs, 
        VcsMappingRegistry, 
        ForeignRevision,
        )

def escape_file_id(file_id):
    return file_id.replace('_', '__').replace(' ', '_s')


def unescape_file_id(file_id):
    return file_id.replace("_s", " ").replace("__", "_")


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
        if path == "":
            return ROOT_ID
        return escape_file_id(path.encode('utf-8'))

    def import_commit(self, commit):
        """Convert a git commit to a bzr revision.

        :return: a `bzrlib.revision.Revision` object.
        """
        if commit is None:
            raise AssertionError("Commit object can't be None")
        rev = ForeignRevision(commit.id, self, self.revision_id_foreign_to_bzr(commit.id))
        rev.parent_ids = tuple([self.revision_id_foreign_to_bzr(p) for p in commit.parents])
        rev.message = commit.message.decode("utf-8", "replace")
        rev.committer = str(commit.committer).decode("utf-8", "replace")
        if commit.committer != commit.author:
            rev.properties['author'] = str(commit.author).decode("utf-8", "replace")
        rev.timestamp = commit.commit_time
        rev.timezone = 0
        return rev


class BzrGitMappingv1(BzrGitMapping):
    revid_prefix = 'git-v1'
    experimental = False


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
    """Foreign Git."""

    def __init__(self):
        super(ForeignGit, self).__init__(mapping_registry)

    @classmethod
    def show_foreign_revid(cls, foreign_revid):
        return { "git commit": foreign_revid }


foreign_git = ForeignGit()
default_mapping = BzrGitMappingv1()


def inventory_to_tree_and_blobs(repo, mapping, revision_id):
    from dulwich.objects import Tree, Blob
    from bzrlib.inventory import InventoryDirectory, InventoryFile
    import stat
    stack = []
    cur = ""
    tree = Tree()

    inv = repo.get_inventory(revision_id)

    # stack contains the set of trees that we haven't 
    # finished constructing

    for path, entry in inv.iter_entries():
        while stack and not path.startswith(cur):
            tree.serialize()
            sha = tree.sha().hexdigest()
            yield sha, tree, cur
            t = (stat.S_IFDIR, urlutils.basename(cur).encode('UTF-8'), sha)
            cur, tree = stack.pop()
            tree.add(*t)

        if type(entry) == InventoryDirectory:
            stack.append((cur, tree))
            cur = path
            tree = Tree()

        if type(entry) == InventoryFile:
            #FIXME: We can make potentially make this Lazy to avoid shaing lots of stuff
            # and having all these objects in memory at once
            blob = Blob()
            _, blob._text = repo.iter_files_bytes([(entry.file_id, entry.revision, path)]).next()
            sha = blob.sha().hexdigest()
            yield sha, blob, path

            name = urlutils.basename(path).encode("utf-8")
            mode = stat.S_IFREG | 0644
            if entry.executable:
                mode |= 0111
            tree.add(mode, name, sha)

    while len(stack) > 1:
        tree.serialize()
        sha = tree.sha().hexdigest()
        yield sha, tree, cur
        t = (stat.S_IFDIR, urlutils.basename(cur).encode('UTF-8'), sha)
        cur, tree = stack.pop()
        tree.add(*t)

    tree.serialize()
    yield tree.sha().hexdigest(), tree, cur


def revision_to_commit(rev, tree_sha, parent_lookup):
    """Turn a Bazaar revision in to a Git commit

    :param tree_sha: Tree sha for the commit
    :param parent_lookup: Function for looking up the GIT sha equiv of a bzr revision
    :return dulwich.objects.Commit represent the revision:
    """
    from dulwich.objects import Commit
    commit = Commit()
    commit._tree = tree_sha
    for p in rev.parent_ids:
        git_p = parent_lookup(p)
        if git_p is not None:
            commit._parents.append(git_p)
    commit._message = rev.message
    commit._committer = rev.committer
    if 'author' in rev.properties:
        commit._author = rev.properties['author']
    else:
        commit._author = rev.committer
    commit._commit_time = long(rev.timestamp)
    commit.serialize()
    return commit
