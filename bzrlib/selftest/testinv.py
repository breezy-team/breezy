# Copyright (C) 2005 by Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

from cStringIO import StringIO
import os

from bzrlib.branch import Branch
from bzrlib.clone import copy_branch
import bzrlib.errors as errors
from bzrlib.diff import internal_diff
from bzrlib.inventory import Inventory, ROOT_ID
import bzrlib.inventory as inventory
from bzrlib.osutils import has_symlinks, rename
from bzrlib.selftest import TestCase, TestCaseInTempDir


class TestInventory(TestCase):

    def test_is_within(self):
        from bzrlib.osutils import is_inside_any

        SRC_FOO_C = os.path.join('src', 'foo.c')
        for dirs, fn in [(['src', 'doc'], SRC_FOO_C),
                         (['src'], SRC_FOO_C),
                         (['src'], 'src'),
                         ]:
            self.assert_(is_inside_any(dirs, fn))
            
        for dirs, fn in [(['src'], 'srccontrol'),
                         (['src'], 'srccontrol/foo')]:
            self.assertFalse(is_inside_any(dirs, fn))
            
    def test_ids(self):
        """Test detection of files within selected directories."""
        inv = Inventory()
        
        for args in [('src', 'directory', 'src-id'), 
                     ('doc', 'directory', 'doc-id'), 
                     ('src/hello.c', 'file'),
                     ('src/bye.c', 'file', 'bye-id'),
                     ('Makefile', 'file')]:
            inv.add_path(*args)
            
        self.assertEqual(inv.path2id('src'), 'src-id')
        self.assertEqual(inv.path2id('src/bye.c'), 'bye-id')
        
        self.assert_('src-id' in inv)


    def test_version(self):
        """Inventory remembers the text's version."""
        inv = Inventory()
        ie = inv.add_path('foo.txt', 'file')
        ## XXX


class TestInventoryEntry(TestCase):

    def test_file_kind_character(self):
        file = inventory.InventoryFile('123', 'hello.c', ROOT_ID)
        self.assertEqual(file.kind_character(), '')

    def test_dir_kind_character(self):
        dir = inventory.InventoryDirectory('123', 'hello.c', ROOT_ID)
        self.assertEqual(dir.kind_character(), '/')

    def test_link_kind_character(self):
        dir = inventory.InventoryLink('123', 'hello.c', ROOT_ID)
        self.assertEqual(dir.kind_character(), '')

    def test_dir_detect_changes(self):
        left = inventory.InventoryDirectory('123', 'hello.c', ROOT_ID)
        left.text_sha1 = 123
        left.executable = True
        left.symlink_target='foo'
        right = inventory.InventoryDirectory('123', 'hello.c', ROOT_ID)
        right.text_sha1 = 321
        right.symlink_target='bar'
        self.assertEqual((False, False), left.detect_changes(right))
        self.assertEqual((False, False), right.detect_changes(left))

    def test_file_detect_changes(self):
        left = inventory.InventoryFile('123', 'hello.c', ROOT_ID)
        left.text_sha1 = 123
        right = inventory.InventoryFile('123', 'hello.c', ROOT_ID)
        right.text_sha1 = 123
        self.assertEqual((False, False), left.detect_changes(right))
        self.assertEqual((False, False), right.detect_changes(left))
        left.executable = True
        self.assertEqual((False, True), left.detect_changes(right))
        self.assertEqual((False, True), right.detect_changes(left))
        right.text_sha1 = 321
        self.assertEqual((True, True), left.detect_changes(right))
        self.assertEqual((True, True), right.detect_changes(left))

    def test_symlink_detect_changes(self):
        left = inventory.InventoryLink('123', 'hello.c', ROOT_ID)
        left.text_sha1 = 123
        left.executable = True
        left.symlink_target='foo'
        right = inventory.InventoryLink('123', 'hello.c', ROOT_ID)
        right.text_sha1 = 321
        right.symlink_target='foo'
        self.assertEqual((False, False), left.detect_changes(right))
        self.assertEqual((False, False), right.detect_changes(left))
        left.symlink_target = 'different'
        self.assertEqual((True, False), left.detect_changes(right))
        self.assertEqual((True, False), right.detect_changes(left))

    def test_file_has_text(self):
        file = inventory.InventoryFile('123', 'hello.c', ROOT_ID)
        self.failUnless(file.has_text())

    def test_directory_has_text(self):
        dir = inventory.InventoryDirectory('123', 'hello.c', ROOT_ID)
        self.failIf(dir.has_text())

    def test_link_has_text(self):
        link = inventory.InventoryLink('123', 'hello.c', ROOT_ID)
        self.failIf(link.has_text())


class TestEntryDiffing(TestCaseInTempDir):

    def setUp(self):
        super(TestEntryDiffing, self).setUp()
        self.branch = Branch.initialize('.')
        self.wt = self.branch.working_tree()
        print >> open('file', 'wb'), 'foo'
        self.branch.working_tree().add(['file'], ['fileid'])
        if has_symlinks():
            os.symlink('target1', 'symlink')
            self.branch.working_tree().add(['symlink'], ['linkid'])
        self.wt.commit('message_1', rev_id = '1')
        print >> open('file', 'wb'), 'bar'
        if has_symlinks():
            os.unlink('symlink')
            os.symlink('target2', 'symlink')
        self.tree_1 = self.branch.storage.revision_tree('1')
        self.inv_1 = self.branch.storage.get_inventory('1')
        self.file_1 = self.inv_1['fileid']
        self.tree_2 = self.branch.working_tree()
        self.inv_2 = self.tree_2.read_working_inventory()
        self.file_2 = self.inv_2['fileid']
        if has_symlinks():
            self.link_1 = self.inv_1['linkid']
            self.link_2 = self.inv_2['linkid']

    def test_file_diff_deleted(self):
        output = StringIO()
        self.file_1.diff(internal_diff, 
                          "old_label", self.tree_1,
                          "/dev/null", None, None,
                          output)
        self.assertEqual(output.getvalue(), "--- old_label\t\n"
                                            "+++ /dev/null\t\n"
                                            "@@ -1,1 +0,0 @@\n"
                                            "-foo\n"
                                            "\n")

    def test_file_diff_added(self):
        output = StringIO()
        self.file_1.diff(internal_diff, 
                          "new_label", self.tree_1,
                          "/dev/null", None, None,
                          output, reverse=True)
        self.assertEqual(output.getvalue(), "--- /dev/null\t\n"
                                            "+++ new_label\t\n"
                                            "@@ -0,0 +1,1 @@\n"
                                            "+foo\n"
                                            "\n")

    def test_file_diff_changed(self):
        output = StringIO()
        self.file_1.diff(internal_diff, 
                          "/dev/null", self.tree_1, 
                          "new_label", self.file_2, self.tree_2,
                          output)
        self.assertEqual(output.getvalue(), "--- /dev/null\t\n"
                                            "+++ new_label\t\n"
                                            "@@ -1,1 +1,1 @@\n"
                                            "-foo\n"
                                            "+bar\n"
                                            "\n")
        
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


class TestSnapshot(TestCaseInTempDir):

    def setUp(self):
        # for full testing we'll need a branch
        # with a subdir to test parent changes.
        # and a file, link and dir under that.
        # but right now I only need one attribute
        # to change, and then test merge patterns
        # with fake parent entries.
        super(TestSnapshot, self).setUp()
        self.branch = Branch.initialize('.')
        self.build_tree(['subdir/', 'subdir/file'], line_endings='binary')
        self.branch.working_tree().add(['subdir', 'subdir/file'],
                                       ['dirid', 'fileid'])
        if has_symlinks():
            pass
        self.wt = self.branch.working_tree()
        self.wt.commit('message_1', rev_id = '1')
        self.tree_1 = self.branch.storage.revision_tree('1')
        self.inv_1 = self.branch.storage.get_inventory('1')
        self.file_1 = self.inv_1['fileid']
        self.work_tree = self.branch.working_tree()
        self.file_active = self.work_tree.inventory['fileid']

    def test_snapshot_new_revision(self):
        # This tests that a simple commit with no parents makes a new
        # revision value in the inventory entry
        self.file_active.snapshot('2', 'subdir/file', {}, self.work_tree, 
                                  self.branch.storage.weave_store,
                                  self.branch.get_transaction())
        # expected outcome - file_1 has a revision id of '2', and we can get
        # its text of 'file contents' out of the weave.
        self.assertEqual(self.file_1.revision, '1')
        self.assertEqual(self.file_active.revision, '2')
        # this should be a separate test probably, but lets check it once..
        lines = self.branch.storage.weave_store.get_lines('fileid','2',
            self.branch.get_transaction())
        self.assertEqual(lines, ['contents of subdir/file\n'])

    def test_snapshot_unchanged(self):
        #This tests that a simple commit does not make a new entry for
        # an unchanged inventory entry
        self.file_active.snapshot('2', 'subdir/file', {'1':self.file_1},
                                  self.work_tree, 
                                  self.branch.storage.weave_store,
                                  self.branch.get_transaction())
        self.assertEqual(self.file_1.revision, '1')
        self.assertEqual(self.file_active.revision, '1')
        self.assertRaises(errors.WeaveError,
                          self.branch.storage.weave_store.get_lines, 'fileid', 
                          '2', self.branch.get_transaction())

    def test_snapshot_merge_identical_different_revid(self):
        # This tests that a commit with two identical parents, one of which has
        # a different revision id, results in a new revision id in the entry.
        # 1->other, commit a merge of other against 1, results in 2.
        other_ie = inventory.InventoryFile('fileid', 'newname', self.file_1.parent_id)
        other_ie = inventory.InventoryFile('fileid', 'file', self.file_1.parent_id)
        other_ie.revision = '1'
        other_ie.text_sha1 = self.file_1.text_sha1
        other_ie.text_size = self.file_1.text_size
        self.assertEqual(self.file_1, other_ie)
        other_ie.revision = 'other'
        self.assertNotEqual(self.file_1, other_ie)
        self.branch.storage.weave_store.add_identical_text('fileid', '1', 
            'other', ['1'], self.branch.get_transaction())
        self.file_active.snapshot('2', 'subdir/file', 
                                  {'1':self.file_1, 'other':other_ie},
                                  self.work_tree, 
                                  self.branch.storage.weave_store,
                                  self.branch.get_transaction())
        self.assertEqual(self.file_active.revision, '2')

    def test_snapshot_changed(self):
        # This tests that a commit with one different parent results in a new
        # revision id in the entry.
        self.file_active.name='newname'
        rename('subdir/file', 'subdir/newname')
        self.file_active.snapshot('2', 'subdir/newname', {'1':self.file_1}, 
                                  self.work_tree, 
                                  self.branch.storage.weave_store,
                                  self.branch.get_transaction())
        # expected outcome - file_1 has a revision id of '2'
        self.assertEqual(self.file_active.revision, '2')


class TestPreviousHeads(TestCaseInTempDir):

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
        self.build_tree(['file'])
        self.branch = Branch.initialize('.')
        self.wt = self.branch.working_tree()
        self.wt.commit('new branch', allow_pointless=True, rev_id='A')
        self.inv_A = self.branch.storage.get_inventory('A')
        self.branch.working_tree().add(['file'], ['fileid'])
        self.wt.commit('add file', rev_id='B')
        self.inv_B = self.branch.storage.get_inventory('B')
        self.branch.put_controlfile('revision-history', 'A\n')
        self.assertEqual(self.branch.revision_history(), ['A'])
        self.wt.commit('another add of file', rev_id='C')
        self.inv_C = self.branch.storage.get_inventory('C')
        self.wt.add_pending_merge('B')
        self.wt.commit('merge in B', rev_id='D')
        self.inv_D = self.branch.storage.get_inventory('D')
        self.file_active = self.wt.inventory['fileid']
        self.weave = self.branch.storage.weave_store.get_weave('fileid',
            self.branch.get_transaction())
        
    def get_previous_heads(self, inventories):
        return self.file_active.find_previous_heads(inventories, self.weave)
        
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
