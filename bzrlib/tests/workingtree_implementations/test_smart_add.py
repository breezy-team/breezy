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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Test that we can use smart_add on all Tree implementations."""

from bzrlib import (
    add,
    errors,
    workingtree,
    )
from bzrlib.add import (
    AddAction,
    AddFromBaseAction,
    smart_add,
    smart_add_tree,
    )

from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree


class TestSmartAddTree(TestCaseWithWorkingTree):

    def test_single_file(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/a'])
        add.smart_add_tree(tree, ['tree'])

        tree.lock_read()
        try:
            files = [(path, status, kind)
                     for path, status, kind, file_id, parent_id
                      in tree.list_files(include_root=True)]
        finally:
            tree.unlock()
        self.assertEqual([('', 'V', 'directory'), ('a', 'V', 'file')],
                         files)

    def test_save_false(self):
        """Dry-run add doesn't permanently affect the tree."""
        wt = self.make_branch_and_tree('.')
        self.build_tree(['file'])
        smart_add_tree(wt, ['file'], save=False)
        # The in-memory inventory is left modified in inventory-based trees;
        # it may not be in dirstate trees.  Anyhow, now we reload to make sure
        # the on-disk version is not modified.
        wt = wt.bzrdir.open_workingtree()
        self.assertEqual(wt.path2id('file'), None)
