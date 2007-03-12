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

"""Tests for interface conformance of inventories of trees."""


from cStringIO import StringIO
import os

from bzrlib.diff import internal_diff
from bzrlib.mutabletree import MutableTree
from bzrlib.osutils import (
    has_symlinks,
    )
from bzrlib.tests import TestSkipped
from bzrlib.tests.tree_implementations import TestCaseWithTree
from bzrlib.uncommit import uncommit


class TestEntryDiffing(TestCaseWithTree):

    def setUp(self):
        super(TestEntryDiffing, self).setUp()
        self.wt = self.make_branch_and_tree('.')
        self.branch = self.wt.branch
        print >> open('file', 'wb'), 'foo'
        print >> open('binfile', 'wb'), 'foo'
        self.wt.add(['file'], ['fileid'])
        self.wt.add(['binfile'], ['binfileid'])
        if has_symlinks():
            os.symlink('target1', 'symlink')
            self.wt.add(['symlink'], ['linkid'])
        self.wt.commit('message_1', rev_id = '1')
        print >> open('file', 'wb'), 'bar'
        print >> open('binfile', 'wb'), 'x' * 1023 + '\x00'
        if has_symlinks():
            os.unlink('symlink')
            os.symlink('target2', 'symlink')
        self.tree_1 = self.branch.repository.revision_tree('1')
        self.inv_1 = self.branch.repository.get_inventory('1')
        self.file_1 = self.inv_1['fileid']
        self.file_1b = self.inv_1['binfileid']
        self.tree_2 = self.workingtree_to_test_tree(self.wt)
        self.tree_2.lock_read()
        self.addCleanup(self.tree_2.unlock)
        self.inv_2 = self.tree_2.inventory
        self.file_2 = self.inv_2['fileid']
        self.file_2b = self.inv_2['binfileid']
        if has_symlinks():
            self.link_1 = self.inv_1['linkid']
            self.link_2 = self.inv_2['linkid']

    def test_file_diff_deleted(self):
        output = StringIO()
        self.file_1.diff(internal_diff, 
                          "old_label", self.tree_1,
                          "/dev/null", None, None,
                          output)
        self.assertEqual(output.getvalue(), "--- old_label\n"
                                            "+++ /dev/null\n"
                                            "@@ -1,1 +0,0 @@\n"
                                            "-foo\n"
                                            "\n")

    def test_file_diff_added(self):
        output = StringIO()
        self.file_1.diff(internal_diff, 
                          "new_label", self.tree_1,
                          "/dev/null", None, None,
                          output, reverse=True)
        self.assertEqual(output.getvalue(), "--- /dev/null\n"
                                            "+++ new_label\n"
                                            "@@ -0,0 +1,1 @@\n"
                                            "+foo\n"
                                            "\n")

    def test_file_diff_changed(self):
        output = StringIO()
        self.file_1.diff(internal_diff, 
                          "/dev/null", self.tree_1, 
                          "new_label", self.file_2, self.tree_2,
                          output)
        self.assertEqual(output.getvalue(), "--- /dev/null\n"
                                            "+++ new_label\n"
                                            "@@ -1,1 +1,1 @@\n"
                                            "-foo\n"
                                            "+bar\n"
                                            "\n")
        
    def test_file_diff_binary(self):
        output = StringIO()
        self.file_1.diff(internal_diff, 
                          "/dev/null", self.tree_1, 
                          "new_label", self.file_2b, self.tree_2,
                          output)
        self.assertEqual(output.getvalue(), 
                         "Binary files /dev/null and new_label differ\n")
    def test_link_diff_deleted(self):
        if not has_symlinks():
            return
        output = StringIO()
        self.link_1.diff(internal_diff, 
                          "old_label", self.tree_1,
                          "/dev/null", None, None,
                          output)
        self.assertEqual(output.getvalue(),
                         "=== target was 'target1'\n")

    def test_link_diff_added(self):
        if not has_symlinks():
            return
        output = StringIO()
        self.link_1.diff(internal_diff, 
                          "new_label", self.tree_1,
                          "/dev/null", None, None,
                          output, reverse=True)
        self.assertEqual(output.getvalue(),
                         "=== target is 'target1'\n")

    def test_link_diff_changed(self):
        if not has_symlinks():
            return
        output = StringIO()
        self.link_1.diff(internal_diff, 
                          "/dev/null", self.tree_1, 
                          "new_label", self.link_2, self.tree_2,
                          output)
        self.assertEqual(output.getvalue(),
                         "=== target changed 'target1' => 'target2'\n")


class TestPreviousHeads(TestCaseWithTree):

    def setUp(self):
        # we want several inventories, that respectively
        # give use the following scenarios:
        # A) fileid not in any inventory (A),
        # B) fileid present in one inventory (B) and (A,B)
        # C) fileid present in two inventories, and they
        #   are not mutual descendents (B, C)
        # D) fileid present in two inventories and one is
        #   a descendent of the other. (B, D)
        super(TestPreviousHeads, self).setUp()
        self.wt = self.make_branch_and_tree('.')
        self.branch = self.wt.branch
        self.build_tree(['file'])
        self.wt.commit('new branch', allow_pointless=True, rev_id='A')
        self.inv_A = self.branch.repository.get_inventory('A')
        self.wt.add(['file'], ['fileid'])
        self.wt.commit('add file', rev_id='B')
        self.inv_B = self.branch.repository.get_inventory('B')
        uncommit(self.branch, tree=self.wt)
        self.assertEqual(self.branch.revision_history(), ['A'])
        self.wt.commit('another add of file', rev_id='C')
        self.inv_C = self.branch.repository.get_inventory('C')
        self.wt.add_parent_tree_id('B')
        self.wt.commit('merge in B', rev_id='D')
        self.inv_D = self.branch.repository.get_inventory('D')
        self.tree = self.workingtree_to_test_tree(self.wt)
        self.tree.lock_read()
        self.addCleanup(self.tree.unlock)
        self.file_active = self.tree.inventory['fileid']
        self.weave = self.branch.repository.weave_store.get_weave('fileid',
            self.branch.repository.get_transaction())
        
    def get_previous_heads(self, inventories):
        return self.file_active.find_previous_heads(
            inventories, 
            self.branch.repository.weave_store,
            self.branch.repository.get_transaction())
        
    def test_fileid_in_no_inventory(self):
        self.assertEqual({}, self.get_previous_heads([self.inv_A]))

    def test_fileid_in_one_inventory(self):
        self.assertEqual({'B':self.inv_B['fileid']},
                         self.get_previous_heads([self.inv_B]))
        self.assertEqual({'B':self.inv_B['fileid']},
                         self.get_previous_heads([self.inv_A, self.inv_B]))
        self.assertEqual({'B':self.inv_B['fileid']},
                         self.get_previous_heads([self.inv_B, self.inv_A]))

    def test_fileid_in_two_inventories_gives_both_entries(self):
        self.assertEqual({'B':self.inv_B['fileid'],
                          'C':self.inv_C['fileid']},
                          self.get_previous_heads([self.inv_B, self.inv_C]))
        self.assertEqual({'B':self.inv_B['fileid'],
                          'C':self.inv_C['fileid']},
                          self.get_previous_heads([self.inv_C, self.inv_B]))

    def test_fileid_in_two_inventories_already_merged_gives_head(self):
        self.assertEqual({'D':self.inv_D['fileid']},
                         self.get_previous_heads([self.inv_B, self.inv_D]))
        self.assertEqual({'D':self.inv_D['fileid']},
                         self.get_previous_heads([self.inv_D, self.inv_B]))

    # TODO: test two inventories with the same file revision 


class TestInventory(TestCaseWithTree):

    def setUp(self):
        super(TestInventory, self).setUp()
        self.tree = self.get_tree_with_subdirs_and_all_content_types()
        self.tree.lock_read()
        self.addCleanup(self.tree.unlock)
        # Commenting out the following line still fails.
        self.inv = self.tree.inventory

    def test_symlink_target(self):
        if isinstance(self.tree, MutableTree):
            raise TestSkipped(
                'symlinks not accurately represented in working trees')
        entry = self.inv[self.inv.path2id('symlink')]
        self.assertEqual(entry.symlink_target, 'link-target')

    def test_symlink(self):
        entry = self.inv[self.inv.path2id('symlink')]
        self.assertEqual(entry.kind, 'symlink')
        self.assertEqual(None, entry.text_size)
