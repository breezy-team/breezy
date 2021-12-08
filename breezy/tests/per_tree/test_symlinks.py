# Copyright (C) 2007-2010 Canonical Ltd
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

"""Tests for interface conformance of inventories of trees."""


from breezy import (
    osutils,
    tests,
    )
from breezy.git.branch import GitBranch
from breezy.tests import (
    per_tree,
    )
from breezy.mutabletree import MutableTree
from breezy.tests import TestSkipped
from breezy.transform import PreviewTree
from breezy.tests import (
    features,
    )


def get_entry(tree, path):
    return next(tree.iter_entries_by_dir(specific_files=[path]))[1]


class TestSymlinkSupportFunction(per_tree.TestCaseWithTree):

    def test_supports_symlinks(self):
        self.tree = self.make_branch_and_tree('.')
        self.assertIn(self.tree.supports_symlinks(), [True, False])


class TestTreeWithSymlinks(per_tree.TestCaseWithTree):

    def setUp(self):
        super(TestTreeWithSymlinks, self).setUp()
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        self.tree = self.get_tree_with_subdirs_and_all_content_types()
        self.tree.lock_read()
        self.addCleanup(self.tree.unlock)

    def test_symlink_target(self):
        if isinstance(self.tree, (MutableTree, PreviewTree)):
            raise TestSkipped(
                'symlinks not accurately represented in working trees and'
                ' preview trees')
        entry = get_entry(self.tree, 'symlink')
        self.assertEqual(entry.symlink_target, 'link-target')

    def test_symlink_target_tree(self):
        self.assertEqual('link-target',
                         self.tree.get_symlink_target('symlink'))

    def test_kind_symlink(self):
        self.assertEqual('symlink', self.tree.kind('symlink'))
        self.assertIs(None, self.tree.get_file_size('symlink'))

    def test_symlink(self):
        entry = get_entry(self.tree, 'symlink')
        self.assertEqual(entry.kind, 'symlink')
        self.assertEqual(None, entry.text_size)


class TestTreeWithoutSymlinks(per_tree.TestCaseWithTree):

    def setUp(self):
        super(TestTreeWithoutSymlinks, self).setUp()
        self.branch = self.make_branch('a')
        mem_tree = self.branch.create_memorytree()
        with mem_tree.lock_write():
            mem_tree._file_transport.symlink('source', 'symlink')
            mem_tree.add(['', 'symlink'])
            rev1 = mem_tree.commit('rev1')
        self.assertPathDoesNotExist('a/symlink')

    def test_clone_skips_symlinks(self):
        if isinstance(self.branch, (GitBranch,)):
            # TODO(jelmer): Fix this test for git repositories
            raise TestSkipped(
                'git trees do not honor osutils.supports_symlinks yet')
        self.overrideAttr(osutils, 'supports_symlinks', lambda p: False)
        # This should not attempt to create any symlinks
        result_dir = self.branch.controldir.sprout('b')
        result_tree = result_dir.open_workingtree()
        self.assertFalse(result_tree.supports_symlinks())
        self.assertPathDoesNotExist('b/symlink')
        basis_tree = self.branch.basis_tree()
        self.assertTrue(basis_tree.has_filename('symlink'))
        with result_tree.lock_read():
            self.assertEqual(
                [('symlink', 'symlink')],
                [c.path for c in result_tree.iter_changes(basis_tree)])
