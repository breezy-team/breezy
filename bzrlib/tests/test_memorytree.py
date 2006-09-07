# Copyright (C) 2006 Canonical Ltd
# Authors:  Robert Collins <robert.collins@canonical.com>
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

"""Tests for the MemoryTree class."""

from bzrlib import errors
from bzrlib.memorytree import MemoryTree
from bzrlib.tests import TestCaseWithTransport
from bzrlib.treebuilder import TreeBuilder


class TestMemoryTree(TestCaseWithTransport):
    
    def test_create_on_branch(self):
        """Creating a mutable tree on a trivial branch works."""
        branch = self.make_branch('branch')
        tree = MemoryTree.create_on_branch(branch)
        self.assertEqual(branch.bzrdir, tree.bzrdir)
        self.assertEqual(branch, tree.branch)
        self.assertEqual([], tree.get_parent_ids())
    
    def test_create_on_branch_with_content(self):
        """Creating a mutable tree on a non-trivial branch works."""
        branch = self.make_branch('branch')
        tree = MemoryTree.create_on_branch(branch)
        # build some content
        tree.lock_write()
        builder = TreeBuilder()
        builder.start_tree(tree)
        builder.build(['foo'])
        builder.finish_tree()
        rev_id = tree.commit('first post')
        tree.unlock()
        tree = MemoryTree.create_on_branch(branch)
        tree.lock_read()
        self.assertEqual([rev_id], tree.get_parent_ids())
        self.assertEqual('contents of foo\n',
            tree.get_file(tree.path2id('foo')).read())
        tree.unlock()

    def test_lock_write(self):
        """Check we can lock_write and unlock MemoryTrees."""
        branch = self.make_branch('branch')
        tree = MemoryTree.create_on_branch(branch)
        tree.lock_write()
        tree.unlock()

    def test_lock_write_after_read_fails(self):
        """Check that we error when trying to upgrade a read lock to write."""
        branch = self.make_branch('branch')
        tree = MemoryTree.create_on_branch(branch)
        tree.lock_read()
        self.assertRaises(errors.ReadOnlyError, tree.lock_write)
        tree.unlock()

    def test_add_with_kind(self):
        branch = self.make_branch('branch')
        tree = MemoryTree.create_on_branch(branch)
        tree.lock_write()
        tree.add(['afile', 'adir'], None, ['file', 'directory'])
        self.assertEqual('afile', tree.id2path(tree.path2id('afile')))
        self.assertEqual('adir', tree.id2path(tree.path2id('adir')))
        self.assertFalse(tree.has_filename('afile'))
        self.assertFalse(tree.has_filename('adir'))
        tree.unlock()

    def test_put_new_file(self):
        branch = self.make_branch('branch')
        tree = MemoryTree.create_on_branch(branch)
        tree.lock_write()
        tree.add(['foo'], ids=['foo-id'], kinds=['file'])
        tree.put_file_bytes_non_atomic('foo-id', 'barshoom')
        self.assertEqual('barshoom', tree.get_file('foo-id').read())
        tree.unlock()

    def test_put_existing_file(self):
        branch = self.make_branch('branch')
        tree = MemoryTree.create_on_branch(branch)
        tree.lock_write()
        tree.add(['foo'], ids=['foo-id'], kinds=['file'])
        tree.put_file_bytes_non_atomic('foo-id', 'first-content')
        tree.put_file_bytes_non_atomic('foo-id', 'barshoom')
        self.assertEqual('barshoom', tree.get_file('foo-id').read())
        tree.unlock()

    def test_commit_trivial(self):
        """Smoke test for commit on a MemoryTree.

        Becamse of commits design and layering, if this works, all commit
        logic should work quite reliably.
        """
        branch = self.make_branch('branch')
        tree = MemoryTree.create_on_branch(branch)
        tree.lock_write()
        tree.add(['foo'], ids=['foo-id'], kinds=['file'])
        tree.put_file_bytes_non_atomic('foo-id', 'barshoom')
        revision_id = tree.commit('message baby')
        # the parents list for the tree should have changed.
        self.assertEqual([revision_id], tree.get_parent_ids())
        tree.unlock()
        # and we should have a revision that is accessible outside the tree lock
        revtree = tree.branch.repository.revision_tree(revision_id)
        self.assertEqual('barshoom', revtree.get_file('foo-id').read())
