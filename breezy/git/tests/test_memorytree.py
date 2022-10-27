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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Tests for the GitMemoryTree class."""

from ... import errors
from ...transport import NoSuchFile
from . import TestCaseWithTransport


class TestMemoryTree(TestCaseWithTransport):

    def make_branch(self, path, format='git'):
        return super(TestMemoryTree, self).make_branch(path, format=format)

    def make_branch_and_tree(self, path, format='git'):
        return super(TestMemoryTree, self).make_branch_and_tree(path, format=format)

    def test_create_on_branch(self):
        """Creating a mutable tree on a trivial branch works."""
        branch = self.make_branch('branch')
        tree = branch.create_memorytree()
        self.assertEqual(branch.controldir, tree.controldir)
        self.assertEqual(branch, tree.branch)
        self.assertEqual([], tree.get_parent_ids())

    def test_create_on_branch_with_content(self):
        """Creating a mutable tree on a non-trivial branch works."""
        wt = self.make_branch_and_tree('sometree')
        self.build_tree(['sometree/foo'])
        wt.add(['foo'])
        rev_id = wt.commit('first post')
        tree = wt.branch.create_memorytree()
        with tree.lock_read():
            self.assertEqual([rev_id], tree.get_parent_ids())
            self.assertEqual(b'contents of sometree/foo\n',
                             tree.get_file('foo').read())

    def test_lock_tree_write(self):
        """Check we can lock_tree_write and unlock MemoryTrees."""
        branch = self.make_branch('branch')
        tree = branch.create_memorytree()
        tree.lock_tree_write()
        tree.unlock()

    def test_lock_tree_write_after_read_fails(self):
        """Check that we error when trying to upgrade a read lock to write."""
        branch = self.make_branch('branch')
        tree = branch.create_memorytree()
        tree.lock_read()
        self.assertRaises(errors.ReadOnlyError, tree.lock_tree_write)
        tree.unlock()

    def test_lock_write(self):
        """Check we can lock_write and unlock MemoryTrees."""
        branch = self.make_branch('branch')
        tree = branch.create_memorytree()
        tree.lock_write()
        tree.unlock()

    def test_lock_write_after_read_fails(self):
        """Check that we error when trying to upgrade a read lock to write."""
        branch = self.make_branch('branch')
        tree = branch.create_memorytree()
        tree.lock_read()
        self.assertRaises(errors.ReadOnlyError, tree.lock_write)
        tree.unlock()

    def test_add_with_kind(self):
        branch = self.make_branch('branch')
        tree = branch.create_memorytree()
        tree.lock_write()
        tree.add(['', 'afile', 'adir'], ['directory', 'file', 'directory'])
        self.assertTrue(tree.is_versioned('afile'))
        self.assertFalse(tree.is_versioned('adir'))
        self.assertFalse(tree.has_filename('afile'))
        self.assertFalse(tree.has_filename('adir'))
        tree.unlock()

    def test_put_new_file(self):
        branch = self.make_branch('branch')
        tree = branch.create_memorytree()
        with tree.lock_write():
            tree.add(['', 'foo'], kinds=['directory', 'file'])
            tree.put_file_bytes_non_atomic('foo', b'barshoom')
            self.assertEqual(b'barshoom', tree.get_file('foo').read())

    def test_put_existing_file(self):
        branch = self.make_branch('branch')
        tree = branch.create_memorytree()
        with tree.lock_write():
            tree.add(['', 'foo'], kinds=['directory', 'file'])
            tree.put_file_bytes_non_atomic('foo', b'first-content')
            tree.put_file_bytes_non_atomic('foo', b'barshoom')
            self.assertEqual(b'barshoom', tree.get_file('foo').read())

    def test_add_in_subdir(self):
        branch = self.make_branch('branch')
        tree = branch.create_memorytree()
        with tree.lock_write():
            tree.add([''], ['directory'])
            tree.mkdir('adir')
            tree.put_file_bytes_non_atomic('adir/afile', b'barshoom')
            tree.add(['adir/afile'], ['file'])
            self.assertTrue(tree.is_versioned('adir/afile'))
            self.assertTrue(tree.is_versioned('adir'))

    def test_commit_trivial(self):
        """Smoke test for commit on a MemoryTree.

        Becamse of commits design and layering, if this works, all commit
        logic should work quite reliably.
        """
        branch = self.make_branch('branch')
        tree = branch.create_memorytree()
        with tree.lock_write():
            tree.add(['', 'foo'], kinds=['directory', 'file'])
            tree.put_file_bytes_non_atomic('foo', b'barshoom')
            revision_id = tree.commit('message baby')
            # the parents list for the tree should have changed.
            self.assertEqual([revision_id], tree.get_parent_ids())
        # and we should have a revision that is accessible outside the tree lock
        revtree = tree.branch.repository.revision_tree(revision_id)
        with revtree.lock_read():
            self.assertEqual(b'barshoom', revtree.get_file('foo').read())

    def test_unversion(self):
        """Some test for unversion of a memory tree."""
        branch = self.make_branch('branch')
        tree = branch.create_memorytree()
        with tree.lock_write():
            tree.add(['', 'foo'], kinds=['directory', 'file'])
            tree.unversion(['foo'])
            self.assertFalse(tree.is_versioned('foo'))
            self.assertFalse(tree.has_filename('foo'))

    def test_last_revision(self):
        """There should be a last revision method we can call."""
        tree = self.make_branch_and_memory_tree('branch')
        with tree.lock_write():
            tree.add('')
            rev_id = tree.commit('first post')
        self.assertEqual(rev_id, tree.last_revision())

    def test_rename_file(self):
        tree = self.make_branch_and_memory_tree('branch')
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.add(['', 'foo'], ['directory', 'file'], ids=[b'root-id', b'foo-id'])
        tree.put_file_bytes_non_atomic('foo', b'content\n')
        tree.commit('one', rev_id=b'rev-one')
        tree.rename_one('foo', 'bar')
        self.assertEqual('bar', tree.id2path(b'foo-id'))
        self.assertEqual(b'content\n', tree._file_transport.get_bytes('bar'))
        self.assertRaises(NoSuchFile,
                          tree._file_transport.get_bytes, 'foo')
        tree.commit('two', rev_id=b'rev-two')
        self.assertEqual(b'content\n', tree._file_transport.get_bytes('bar'))
        self.assertRaises(NoSuchFile,
                          tree._file_transport.get_bytes, 'foo')

        rev_tree2 = tree.branch.repository.revision_tree(b'rev-two')
        self.assertEqual('bar', rev_tree2.id2path(b'foo-id'))
        self.assertEqual(b'content\n', rev_tree2.get_file_text('bar'))

    def test_rename_file_to_subdir(self):
        tree = self.make_branch_and_memory_tree('branch')
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.add('')
        tree.mkdir('subdir', b'subdir-id')
        tree.add('foo', 'file', b'foo-id')
        tree.put_file_bytes_non_atomic('foo', b'content\n')
        tree.commit('one', rev_id=b'rev-one')

        tree.rename_one('foo', 'subdir/bar')
        self.assertEqual('subdir/bar', tree.id2path(b'foo-id'))
        self.assertEqual(b'content\n',
                         tree._file_transport.get_bytes('subdir/bar'))
        tree.commit('two', rev_id=b'rev-two')
        rev_tree2 = tree.branch.repository.revision_tree(b'rev-two')
        self.assertEqual('subdir/bar', rev_tree2.id2path(b'foo-id'))
