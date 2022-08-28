# Copyright (C) 2007 Canonical Ltd
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

"""Tests for interface conformance of 'WorkingTree.rename_one'"""

import os

from breezy import (
    errors,
    osutils,
    tests,
    transport as _mod_transport,
    )
from breezy.tests import (
    features,
    )
from breezy.tests.matchers import HasPathRelations

from breezy.tests.per_workingtree import TestCaseWithWorkingTree


class TestRenameOne(TestCaseWithWorkingTree):

    def assertPathRelations(self, previous_tree, tree, relations):
        self.assertThat(tree, HasPathRelations(previous_tree, relations))

    def test_rename_one_target_not_dir(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a'])
        tree.add(['a'])
        tree.commit('initial')

        self.assertRaises(errors.BzrMoveFailedError,
                          tree.rename_one, 'a', 'not-a-dir/b')

    def test_rename_one_non_existent(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/'])
        tree.add(['a'])
        tree.commit('initial')
        self.assertRaises(errors.BzrMoveFailedError,
                          tree.rename_one, 'not-a-file', 'a/failure')
        self.assertRaises(errors.BzrMoveFailedError,
                          tree.rename_one, 'not-a-file', 'also_not')

    def test_rename_one_target_not_versioned(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'b'])
        tree.add(['b'])
        tree.commit('initial')
        if tree.has_versioned_directories():
            self.assertRaises(errors.BzrMoveFailedError,
                              tree.rename_one, 'b', 'a/b')
        else:
            tree.rename_one('b', 'a/b')

    def test_rename_one_unversioned(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'b'])
        tree.add(['a'])
        tree.commit('initial')
        self.assertRaises(errors.BzrMoveFailedError,
                          tree.rename_one, 'b', 'a/b')

    def test_rename_one_samedir(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/'])
        tree.add(['a', 'b'])
        tree.commit('initial')

        a_contents = tree.get_file_text('a')
        tree.rename_one('a', 'foo')
        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''), ('b/', 'b/'), ('foo', 'a')])
        self.assertPathDoesNotExist('a')
        self.assertFileEqual(a_contents, 'foo')

    def test_rename_one_not_localdir(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/a', 'tree/b/'])
        tree.add(['a', 'b'])
        tree.commit('initial')

        a_contents = tree.get_file_text('a')
        tree.rename_one('a', 'b/foo')
        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''), ('b/', 'b/'), ('b/foo', 'a')])
        self.assertPathDoesNotExist('tree/a')
        self.assertFileEqual(a_contents, 'tree/b/foo')

    def test_rename_one_subdir(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/', 'b/c'])
        tree.add(['a', 'b', 'b/c'])
        tree.commit('initial')
        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''), ('a', 'a'), ('b/', 'b/'), ('b/c', 'b/c')])
        a_contents = tree.get_file_text('a')
        tree.rename_one('a', 'b/d')
        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''), ('b/', 'b/'), ('b/c', 'b/c'), ('b/d', 'a')])
        self.assertPathDoesNotExist('a')
        self.assertFileEqual(a_contents, 'b/d')

    def test_rename_one_parent_dir(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/', 'b/c'])
        tree.add(['a', 'b', 'b/c'])
        tree.commit('initial')
        c_contents = tree.get_file_text('b/c')
        tree.rename_one('b/c', 'd')
        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''), ('a', 'a'), ('b/', 'b/'), ('d', 'b/c')])
        self.assertPathDoesNotExist('b/c')
        self.assertFileEqual(c_contents, 'd')

    def test_rename_one_fail_consistent(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/', 'b/a', 'c'])
        tree.add(['a', 'b', 'c'])
        tree.commit('initial')
        # Target already exists
        self.assertRaises(errors.RenameFailedFilesExist,
                          tree.rename_one, 'a', 'b/a')
        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''), ('a', 'a'), ('b/', 'b/'), ('c', 'c')])

    def test_rename_one_onto_existing(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b'])
        tree.add(['a', 'b'])
        tree.commit('initial')

        self.assertRaises(errors.BzrMoveFailedError,
                          tree.rename_one, 'a', 'b')

    def test_rename_one_onto_self(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['b/', 'b/a'])
        tree.add(['b', 'b/a'])
        tree.commit('initial')

        self.assertRaises(errors.BzrMoveFailedError,
                          tree.rename_one, 'b/a', 'b/a')

    def test_rename_one_onto_self_root(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a'])
        tree.add(['a'])
        tree.commit('initial')

        self.assertRaises(errors.BzrMoveFailedError,
                          tree.rename_one, 'a', 'a')

    def test_rename_one_after(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/'])
        tree.add(['a', 'b'])
        tree.commit('initial')
        os.rename('a', 'b/foo')

        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''), ('a', 'a'), ('b/', 'b/')])

        # We don't need after=True as long as source is missing and target
        # exists.
        tree.rename_one('a', 'b/foo')
        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''), ('b/', 'b/'), ('b/foo', 'a')])

    def test_rename_one_after_with_after(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/'])
        tree.add(['a', 'b'])
        tree.commit('initial')
        os.rename('a', 'b/foo')

        if tree.has_versioned_directories():
            self.assertPathRelations(tree.basis_tree(), tree,
                                     [('', ''), ('a', 'a'), ('b/', 'b/')])
        else:
            self.assertPathRelations(tree.basis_tree(), tree,
                                     [('', ''), ('a', 'a')])

        # Passing after=True should work as well
        tree.rename_one('a', 'b/foo', after=True)
        self.assertPathRelations(tree.basis_tree(), tree,
                                 [('', ''), ('b/', 'b/'), ('b/foo', 'a')])

    def test_rename_one_after_dest_versioned(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a'])
        tree.add(['a'])
        tree.commit('initial')
        os.rename('a', 'b')
        tree.add(['b'])

        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''), ('a', 'a'), ('b', None)])

        e = self.assertRaises(
            errors.BzrMoveFailedError, tree.rename_one, 'a', 'b')
        self.assertIsInstance(e.extra, errors.AlreadyVersionedError)

    def test_rename_one_after_with_after_dest_versioned(self):
        ''' using after with an already versioned file should fail '''
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b'])
        tree.add(['a', 'b'])
        tree.commit('initial')
        os.unlink('a')

        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''), ('a', 'a'), ('b', 'b')])

        e = self.assertRaises(
            errors.BzrMoveFailedError,
            tree.rename_one, 'a', 'b', after=True)
        self.assertIsInstance(e.extra, errors.AlreadyVersionedError)

    def test_rename_one_after_with_after_dest_added(self):
        ''' using after with a newly added file should work '''
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a'])
        tree.add(['a'])
        tree.commit('initial')
        os.rename('a', 'b')
        tree.add(['b'])

        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''), ('a', 'a'), ('b', None)])
        tree.rename_one('a', 'b', after=True)
        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''), ('b', 'a')])

    def test_rename_one_after_source_removed(self):
        """Rename even if the source was already unversioned."""
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/'])
        tree.add(['a', 'b'])
        tree.commit('initial')
        os.rename('a', 'b/foo')
        tree.remove(['a'])

        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''), ('b/', 'b/')])

        # We don't need after=True as long as source is missing and target
        # exists.
        tree.rename_one('a', 'b/foo')
        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''), ('b/', 'b/'), ('b/foo', 'a')])

    def test_rename_one_after_no_target(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/'])
        tree.add(['a', 'b'])
        tree.commit('initial')

        # Passing after when the file hasn't been rename_one raises an
        # exception
        self.assertRaises(errors.BzrMoveFailedError,
                          tree.rename_one, 'a', 'b/foo', after=True)
        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''), ('a', 'a'), ('b/', 'b/')])

    def test_rename_one_after_source_and_dest(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/', 'b/foo'])
        tree.add(['a', 'b'])
        tree.commit('initial')

        # TODO: jam 20070225 I would usually use 'rb', but assertFileEqual
        #       uses 'r'.
        with open('a', 'r') as a_file:
            a_text = a_file.read()
        with open('b/foo', 'r') as foo_file:
            foo_text = foo_file.read()

        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''), ('a', 'a'), ('b/', 'b/')])
        self.assertRaises(errors.RenameFailedFilesExist,
                          tree.rename_one, 'a', 'b/foo', after=False)
        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''), ('a', 'a'), ('b/', 'b/')])
        self.assertFileEqual(a_text, 'a')
        self.assertFileEqual(foo_text, 'b/foo')
        # But you can pass after=True
        tree.rename_one('a', 'b/foo', after=True)
        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''), ('b/', 'b/'), ('b/foo', 'a')])
        # But it shouldn't actually move anything
        self.assertFileEqual(a_text, 'a')
        self.assertFileEqual(foo_text, 'b/foo')

    def test_rename_one_directory(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'a/b', 'a/c/', 'a/c/d', 'e/'])
        tree.add(['a', 'a/b', 'a/c', 'a/c/d', 'e'])
        tree.commit('initial')

        tree.rename_one('a', 'e/f')
        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''), ('e/', 'e/'), ('e/f/', 'a/'),
             ('e/f/b', 'a/b'), ('e/f/c/', 'a/c/'),
             ('e/f/c/d', 'a/c/d')])

    def test_rename_one_moved(self):
        """Moving a moved entry works as expected."""
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'a/b', 'c/'])
        tree.add(['a', 'a/b', 'c'])
        tree.commit('initial')

        tree.rename_one('a/b', 'c/foo')
        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''), ('a/', 'a/'), ('c/', 'c/'), ('c/foo', 'a/b')])

        tree.rename_one('c/foo', 'bar')
        self.assertPathRelations(
            tree.basis_tree(), tree,
            [('', ''), ('a/', 'a/'), ('bar', 'a/b'), ('c/', 'c/')])

    def test_rename_to_denormalised_fails(self):
        if osutils.normalizes_filenames():
            raise tests.TestNotApplicable('OSX normalizes filenames')
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a'])
        tree.add(['a'])
        self.assertRaises(
            (errors.InvalidNormalization, UnicodeEncodeError),
            tree.rename_one, 'a', u'ba\u030arry')

    def test_rename_unversioned_non_ascii(self):
        """Check error when renaming an unversioned non-ascii file"""
        self.requireFeature(features.UnicodeFilenameFeature)
        tree = self.make_branch_and_tree(".")
        self.build_tree([u"\xA7"])
        e = self.assertRaises(errors.BzrRenameFailedError,
                              tree.rename_one, u"\xA7", "b")
        self.assertIsInstance(e.extra, errors.NotVersionedError)
        self.assertEqual(e.extra.path, u"\xA7")

    def test_rename_into_unversioned_non_ascii_dir(self):
        """Check error when renaming into unversioned non-ascii directory"""
        self.requireFeature(features.UnicodeFilenameFeature)
        tree = self.make_branch_and_tree(".")
        self.build_tree(["a", u"\xA7/"])
        tree.add(["a"])
        if tree.has_versioned_directories():
            e = self.assertRaises(errors.BzrMoveFailedError,
                                  tree.rename_one, "a", u"\xA7/a")
            self.assertIsInstance(e.extra, errors.NotVersionedError)
            self.assertEqual(e.extra.path, u"\xA7")
        else:
            tree.rename_one("a", u"\xA7/a")

    def test_rename_over_already_versioned_non_ascii(self):
        """Check error renaming over an already versioned non-ascii file"""
        self.requireFeature(features.UnicodeFilenameFeature)
        tree = self.make_branch_and_tree(".")
        self.build_tree(["a", u"\xA7"])
        tree.add(["a", u"\xA7"])
        e = self.assertRaises(errors.BzrMoveFailedError,
                              tree.rename_one, "a", u"\xA7")
        self.assertIsInstance(e.extra, errors.AlreadyVersionedError)
        self.assertEqual(e.extra.path, u"\xA7")

    def test_rename_after_non_existant_non_ascii(self):
        """Check error renaming after move with missing non-ascii file"""
        self.requireFeature(features.UnicodeFilenameFeature)
        tree = self.make_branch_and_tree(".")
        self.build_tree(["a"])
        tree.add(["a"])
        e = self.assertRaises(errors.BzrMoveFailedError,
                              tree.rename_one, "a", u"\xA7", after=True)
        self.assertIsInstance(e.extra, _mod_transport.NoSuchFile)
        self.assertEqual(e.extra.path, u"\xA7")
