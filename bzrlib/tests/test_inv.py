# Copyright (C) 2005, 2006 Canonical Ltd
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

from cStringIO import StringIO
import os
import time

from bzrlib import errors, inventory, osutils
from bzrlib.branch import Branch
from bzrlib.diff import internal_diff
from bzrlib.inventory import (Inventory, ROOT_ID, InventoryFile,
    InventoryDirectory, InventoryEntry, TreeReference)
from bzrlib.osutils import (has_symlinks, rename, pathjoin, is_inside_any, 
    is_inside_or_parent_of_any)
from bzrlib.tests import TestCase, TestCaseWithTransport
from bzrlib.transform import TreeTransform
from bzrlib.uncommit import uncommit


class TestInventory(TestCase):

    def test_is_within(self):

        SRC_FOO_C = pathjoin('src', 'foo.c')
        for dirs, fn in [(['src', 'doc'], SRC_FOO_C),
                         (['src'], SRC_FOO_C),
                         (['src'], 'src'),
                         ]:
            self.assert_(is_inside_any(dirs, fn))
            
        for dirs, fn in [(['src'], 'srccontrol'),
                         (['src'], 'srccontrol/foo')]:
            self.assertFalse(is_inside_any(dirs, fn))

    def test_is_within_or_parent(self):
        for dirs, fn in [(['src', 'doc'], 'src/foo.c'),
                         (['src'], 'src/foo.c'),
                         (['src/bar.c'], 'src'),
                         (['src/bar.c', 'bla/foo.c'], 'src'),
                         (['src'], 'src'),
                         ]:
            self.assert_(is_inside_or_parent_of_any(dirs, fn))
            
        for dirs, fn in [(['src'], 'srccontrol'),
                         (['srccontrol/foo.c'], 'src'),
                         (['src'], 'srccontrol/foo')]:
            self.assertFalse(is_inside_or_parent_of_any(dirs, fn))

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

    def test_non_directory_children(self):
        """Test path2id when a parent directory has no children"""
        inv = inventory.Inventory('tree_root')
        inv.add(inventory.InventoryFile('file-id','file', 
                                        parent_id='tree_root'))
        inv.add(inventory.InventoryLink('link-id','link', 
                                        parent_id='tree_root'))
        self.assertIs(None, inv.path2id('file/subfile'))
        self.assertIs(None, inv.path2id('link/subfile'))

    def test_iter_entries(self):
        inv = Inventory()
        
        for args in [('src', 'directory', 'src-id'), 
                     ('doc', 'directory', 'doc-id'), 
                     ('src/hello.c', 'file', 'hello-id'),
                     ('src/bye.c', 'file', 'bye-id'),
                     ('Makefile', 'file', 'makefile-id')]:
            inv.add_path(*args)

        self.assertEqual([
            ('', ROOT_ID),
            ('Makefile', 'makefile-id'),
            ('doc', 'doc-id'),
            ('src', 'src-id'),
            ('src/bye.c', 'bye-id'),
            ('src/hello.c', 'hello-id'),
            ], [(path, ie.file_id) for path, ie in inv.iter_entries()])
            
    def test_iter_entries_by_dir(self):
        inv = Inventory()
        
        for args in [('src', 'directory', 'src-id'), 
                     ('doc', 'directory', 'doc-id'), 
                     ('src/hello.c', 'file', 'hello-id'),
                     ('src/bye.c', 'file', 'bye-id'),
                     ('zz', 'file', 'zz-id'),
                     ('src/sub/', 'directory', 'sub-id'),
                     ('src/zz.c', 'file', 'zzc-id'),
                     ('src/sub/a', 'file', 'a-id'),
                     ('Makefile', 'file', 'makefile-id')]:
            inv.add_path(*args)

        self.assertEqual([
            ('', ROOT_ID),
            ('Makefile', 'makefile-id'),
            ('doc', 'doc-id'),
            ('src', 'src-id'),
            ('zz', 'zz-id'),
            ('src/bye.c', 'bye-id'),
            ('src/hello.c', 'hello-id'),
            ('src/sub', 'sub-id'),
            ('src/zz.c', 'zzc-id'),
            ('src/sub/a', 'a-id'),
            ], [(path, ie.file_id) for path, ie in inv.iter_entries_by_dir()])
            
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

    def test_make_entry(self):
        self.assertIsInstance(inventory.make_entry("file", "name", ROOT_ID),
            inventory.InventoryFile)
        self.assertIsInstance(inventory.make_entry("symlink", "name", ROOT_ID),
            inventory.InventoryLink)
        self.assertIsInstance(inventory.make_entry("directory", "name", ROOT_ID),
            inventory.InventoryDirectory)

    def test_make_entry_non_normalized(self):
        orig_normalized_filename = osutils.normalized_filename

        try:
            osutils.normalized_filename = osutils._accessible_normalized_filename
            entry = inventory.make_entry("file", u'a\u030a', ROOT_ID)
            self.assertEqual(u'\xe5', entry.name)
            self.assertIsInstance(entry, inventory.InventoryFile)

            osutils.normalized_filename = osutils._inaccessible_normalized_filename
            self.assertRaises(errors.InvalidNormalization,
                    inventory.make_entry, 'file', u'a\u030a', ROOT_ID)
        finally:
            osutils.normalized_filename = orig_normalized_filename


class TestEntryDiffing(TestCaseWithTransport):

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
        self.tree_2 = self.wt
        self.inv_2 = self.tree_2.read_working_inventory()
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


class TestSnapshot(TestCaseWithTransport):

    def setUp(self):
        # for full testing we'll need a branch
        # with a subdir to test parent changes.
        # and a file, link and dir under that.
        # but right now I only need one attribute
        # to change, and then test merge patterns
        # with fake parent entries.
        super(TestSnapshot, self).setUp()
        self.wt = self.make_branch_and_tree('.')
        self.branch = self.wt.branch
        self.build_tree(['subdir/', 'subdir/file'], line_endings='binary')
        self.wt.add(['subdir', 'subdir/file'],
                                       ['dirid', 'fileid'])
        if has_symlinks():
            pass
        self.wt.commit('message_1', rev_id = '1')
        self.tree_1 = self.branch.repository.revision_tree('1')
        self.inv_1 = self.branch.repository.get_inventory('1')
        self.file_1 = self.inv_1['fileid']
        self.file_active = self.wt.inventory['fileid']
        self.builder = self.branch.get_commit_builder([], timestamp=time.time(), revision_id='2')

    def test_snapshot_new_revision(self):
        # This tests that a simple commit with no parents makes a new
        # revision value in the inventory entry
        self.file_active.snapshot('2', 'subdir/file', {}, self.wt, self.builder)
        # expected outcome - file_1 has a revision id of '2', and we can get
        # its text of 'file contents' out of the weave.
        self.assertEqual(self.file_1.revision, '1')
        self.assertEqual(self.file_active.revision, '2')
        # this should be a separate test probably, but lets check it once..
        lines = self.branch.repository.weave_store.get_weave(
            'fileid', 
            self.branch.get_transaction()).get_lines('2')
        self.assertEqual(lines, ['contents of subdir/file\n'])

    def test_snapshot_unchanged(self):
        #This tests that a simple commit does not make a new entry for
        # an unchanged inventory entry
        self.file_active.snapshot('2', 'subdir/file', {'1':self.file_1},
                                  self.wt, self.builder)
        self.assertEqual(self.file_1.revision, '1')
        self.assertEqual(self.file_active.revision, '1')
        vf = self.branch.repository.weave_store.get_weave(
            'fileid', 
            self.branch.repository.get_transaction())
        self.assertRaises(errors.RevisionNotPresent,
                          vf.get_lines,
                          '2')

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
        versionfile = self.branch.repository.weave_store.get_weave(
            'fileid', self.branch.repository.get_transaction())
        versionfile.clone_text('other', '1', ['1'])
        self.file_active.snapshot('2', 'subdir/file', 
                                  {'1':self.file_1, 'other':other_ie},
                                  self.wt, self.builder)
        self.assertEqual(self.file_active.revision, '2')

    def test_snapshot_changed(self):
        # This tests that a commit with one different parent results in a new
        # revision id in the entry.
        self.file_active.name='newname'
        rename('subdir/file', 'subdir/newname')
        self.file_active.snapshot('2', 'subdir/newname', {'1':self.file_1}, 
                                  self.wt, self.builder)
        # expected outcome - file_1 has a revision id of '2'
        self.assertEqual(self.file_active.revision, '2')


class TestPreviousHeads(TestCaseWithTransport):

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
        self.file_active = self.wt.inventory['fileid']
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


class TestDescribeChanges(TestCase):

    def test_describe_change(self):
        # we need to test the following change combinations:
        # rename
        # reparent
        # modify
        # gone
        # added
        # renamed/reparented and modified
        # change kind (perhaps can't be done yet?)
        # also, merged in combination with all of these?
        old_a = InventoryFile('a-id', 'a_file', ROOT_ID)
        old_a.text_sha1 = '123132'
        old_a.text_size = 0
        new_a = InventoryFile('a-id', 'a_file', ROOT_ID)
        new_a.text_sha1 = '123132'
        new_a.text_size = 0

        self.assertChangeDescription('unchanged', old_a, new_a)

        new_a.text_size = 10
        new_a.text_sha1 = 'abcabc'
        self.assertChangeDescription('modified', old_a, new_a)

        self.assertChangeDescription('added', None, new_a)
        self.assertChangeDescription('removed', old_a, None)
        # perhaps a bit questionable but seems like the most reasonable thing...
        self.assertChangeDescription('unchanged', None, None)

        # in this case it's both renamed and modified; show a rename and 
        # modification:
        new_a.name = 'newfilename'
        self.assertChangeDescription('modified and renamed', old_a, new_a)

        # reparenting is 'renaming'
        new_a.name = old_a.name
        new_a.parent_id = 'somedir-id'
        self.assertChangeDescription('modified and renamed', old_a, new_a)

        # reset the content values so its not modified
        new_a.text_size = old_a.text_size
        new_a.text_sha1 = old_a.text_sha1
        new_a.name = old_a.name

        new_a.name = 'newfilename'
        self.assertChangeDescription('renamed', old_a, new_a)

        # reparenting is 'renaming'
        new_a.name = old_a.name
        new_a.parent_id = 'somedir-id'
        self.assertChangeDescription('renamed', old_a, new_a)

    def assertChangeDescription(self, expected_change, old_ie, new_ie):
        change = InventoryEntry.describe_change(old_ie, new_ie)
        self.assertEqual(expected_change, change)


class TestRevert(TestCaseWithTransport):

    def test_dangling_id(self):
        wt = self.make_branch_and_tree('b1')
        self.assertEqual(len(wt.inventory), 1)
        open('b1/a', 'wb').write('a test\n')
        wt.add('a')
        self.assertEqual(len(wt.inventory), 2)
        os.unlink('b1/a')
        wt.revert([])
        self.assertEqual(len(wt.inventory), 1)


class TestIsRoot(TestCase):
    """Ensure our root-checking code is accurate."""

    def test_is_root(self):
        inv = Inventory('TREE_ROOT')
        self.assertTrue(inv.is_root('TREE_ROOT'))
        self.assertFalse(inv.is_root('booga'))
        inv.root.file_id = 'booga'
        self.assertFalse(inv.is_root('TREE_ROOT'))
        self.assertTrue(inv.is_root('booga'))
        # works properly even if no root is set
        inv.root = None
        self.assertFalse(inv.is_root('TREE_ROOT'))
        self.assertFalse(inv.is_root('booga'))


class TestTreeReference(TestCase):
    
    def test_create(self):
        inv = Inventory('tree-root-123')
        inv.add(TreeReference('nested-id', 'nested', parent_id='tree-root-123',
                              revision='rev', reference_revision='rev2'))
