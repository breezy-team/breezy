# Copyright (C) 2009 Jelmer Vernooij <jelmer@samba.org>
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


"""Git Trees."""

from bzrlib import (
    delta,
    errors,
    revisiontree,
    tree,
    )

from bzrlib.plugins.git.inventory import (
    GitInventory,
    )
from bzrlib.plugins.git.mapping import (
    mode_kind,
    )


class GitRevisionTree(revisiontree.RevisionTree):

    def __init__(self, repository, revision_id):
        self._revision_id = revision_id
        self._repository = repository
        store = repository._git.object_store
        assert isinstance(revision_id, str)
        git_id, self.mapping = repository.lookup_git_revid(revision_id)
        try:
            commit = store[git_id]
        except KeyError, r:
            raise errors.NoSuchRevision(repository, revision_id)
        self.tree = commit.tree
        self._inventory = GitInventory(self.tree, self.mapping, store, 
                                       revision_id)

    def get_revision_id(self):
        return self._revision_id

    def get_file_text(self, file_id, path=None):
        if path is not None:
            entry = self._inventory._get_ie(path)
        else:
            entry = self._inventory[file_id]
        if entry.kind == 'directory': return ""
        return entry.object.data


def tree_delta_from_git_changes(changes, mapping, specific_file=None, 
                                require_versioned=False):
    """Create a TreeDelta from two git trees.
    
    source and target are iterators over tuples with: 
        (filename, sha, mode)
    """
    ret = delta.TreeDelta()
    for (oldpath, newpath), (oldmode, newmode), (oldsha, newsha) in changes:
        if oldpath is None:
            ret.added.append((newpath, mapping.generate_file_id(newpath), mode_kind(newmode)))
        elif newpath is None:
            ret.removed.append((oldpath, mapping.generate_file_id(oldpath), mode_kind(oldmode)))
        elif oldpath != newpath:
            ret.renamed.append((oldpath, newpath, mapping.generate_file_id(oldpath), mode_kind(newmode), (oldsha != newsha), (oldmode != newmode)))
        elif mode_kind(oldmode) != mode_kind(newmode):
            ret.kind_changed.append((newpath, mapping.generate_file_id(newpath), mode_kind(oldmode), mode_kind(newmode)))
        elif oldsha != newsha or oldmode != newmode:
            ret.modified.append((newpath, mapping.generate_file_id(newpath), mode_kind(newmode), (oldsha != newsha), (oldmode != newmode)))
        else:
            ret.unchanged.append((newpath, mapping.generate_file_id(newpath), mode_kind(newmode)))
    return ret


class InterGitRevisionTrees(tree.InterTree):
    """InterTree that works between two git revision trees."""

    @classmethod
    def is_compatible(cls, source, target):
        return (isinstance(source, GitRevisionTree) and 
                isinstance(target, GitRevisionTree))

    def compare(self, want_unchanged=False, specific_files=None,
                extra_trees=None, require_versioned=False, include_root=False,
                want_unversioned=False):
        if self.source._repository._git.object_store != self.target._repository._git.object_store:
            raise AssertionError
        changes = self.source._repository._git.object_store.tree_changes(
            self.source.tree, self.target.tree, want_unchanged=want_unchanged)
        return tree_delta_from_git_changes(changes, self.target.mapping, 
            specific_file=specific_files)


tree.InterTree.register_optimiser(InterGitRevisionTrees)
