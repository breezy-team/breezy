# Copyright (C) 2006-2010 Canonical Ltd
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

"""Tests for WorkingTree.set_root_id."""

import sys

from breezy import errors
from breezy.tests import TestSkipped
from breezy.tests.per_workingtree import TestCaseWithWorkingTree


class TestSetRootId(TestCaseWithWorkingTree):
    def test_set_and_read_unicode(self):
        if sys.platform == "win32":
            raise TestSkipped("don't use oslocks on win32 in unix manner")
        # This test tests that setting the root doesn't flush, so it
        # deliberately tests concurrent access that isn't possible on windows.
        self.thisFailsStrictLockCheck()
        tree = self.make_branch_and_tree("a-tree")
        if not tree.supports_setting_file_ids():
            self.skipTest("format does not support setting file ids")
        # setting the root id allows it to be read via get_root_id.
        root_id = "\xe5n-id".encode()
        with tree.lock_write():
            old_id = tree.path2id("")
            tree.set_root_id(root_id)
            self.assertEqual(root_id, tree.path2id(""))
            # set root id should not have triggered a flush of the tree,
            # so check a new tree sees the old state.
            reference_tree = tree.controldir.open_workingtree()
            self.assertEqual(old_id, reference_tree.path2id(""))
        # having unlocked the tree, the value should have been
        # preserved into the next lock, which is an implicit read
        # lock around the get_root_id call.
        self.assertEqual(root_id, tree.path2id(""))
        # and if we get a new working tree instance, then the value
        # should still be retained
        tree = tree.controldir.open_workingtree()
        self.assertEqual(root_id, tree.path2id(""))
        tree._validate()

    def test_set_root_id(self):
        tree = self.make_branch_and_tree(".")
        if not tree.supports_setting_file_ids():
            self.skipTest("format does not support setting file ids")
        tree.lock_write()
        self.addCleanup(tree.unlock)
        orig_root_id = tree.path2id("")
        self.assertNotEqual(b"custom-root-id", orig_root_id)
        self.assertEqual("", tree.id2path(orig_root_id))
        self.assertRaises(errors.NoSuchId, tree.id2path, "custom-root-id")
        tree.set_root_id(b"custom-root-id")
        self.assertEqual(b"custom-root-id", tree.path2id(""))
        self.assertEqual(b"custom-root-id", tree.path2id(""))
        self.assertEqual("", tree.id2path(b"custom-root-id"))
        self.assertRaises(errors.NoSuchId, tree.id2path, orig_root_id)
        tree._validate()
