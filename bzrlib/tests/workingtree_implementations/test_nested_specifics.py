# Copyright (C) 2007 Canonical Ltd
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


from bzrlib.tests import TestNotApplicable
from bzrlib.transform import TreeTransform
from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree


class TestNestedSupport(TestCaseWithWorkingTree):

    def make_branch_and_tree(self, path):
        tree = TestCaseWithWorkingTree.make_branch_and_tree(self, path)
        if not tree.supports_tree_reference():
            raise TestNotApplicable('Tree references not supported')
        return tree

    def test_set_get_tree_reference(self):
        """This tests that setting a tree reference is persistent."""
        tree = self.make_branch_and_tree('.')
        transform = TreeTransform(tree)
        trans_id = transform.new_directory('reference', transform.root,
            'subtree-id')
        transform.set_tree_reference('subtree-revision', trans_id)
        transform.apply()
        tree = tree.bzrdir.open_workingtree()
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual('subtree-revision',
            tree.inventory['subtree-id'].reference_revision)

    def test_extract_while_locked(self):
        tree = self.make_branch_and_tree('.')
        tree.lock_write()
        self.addCleanup(tree.unlock)
        self.build_tree(['subtree/'])
        tree.add(['subtree'], ['subtree-id'])
        subtree = tree.extract('subtree-id')

    def test_no_autodetect_subtree(self):
        tree = self.make_branch_and_tree('.')
        tree.lock_write()
        subtree = self.make_branch_and_tree('subtree')
        tree.add(['subtree'], ['subtree-id'])
        self.assertEqual('subtree', tree.id2path('subtree-id'))
        self.assertEqual('directory', tree.kind('subtree-id'))
