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
from bzrlib.diff import internal_diff
from bzrlib.inventory import Inventory, InventoryEntry, ROOT_ID
from bzrlib.osutils import has_symlinks
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


class TestInventoryEntry(TestCaseInTempDir):

    def test_file_kind_character(self):
        file = InventoryEntry('123', 'hello.c', 'file', ROOT_ID)
        self.assertEqual(file.kind_character(), '')

    def test_dir_kind_character(self):
        dir = InventoryEntry('123', 'hello.c', 'directory', ROOT_ID)
        self.assertEqual(dir.kind_character(), '/')

    def test_link_kind_character(self):
        dir = InventoryEntry('123', 'hello.c', 'symlink', ROOT_ID)
        self.assertEqual(dir.kind_character(), '')

    def test_dir_detect_changes(self):
        left = InventoryEntry('123', 'hello.c', 'directory', ROOT_ID)
        left.text_sha1 = 123
        left.executable = True
        left.symlink_target='foo'
        right = InventoryEntry('123', 'hello.c', 'directory', ROOT_ID)
        right.text_sha1 = 321
        right.symlink_target='bar'
        self.assertEqual((False, False), left.detect_changes(right))
        self.assertEqual((False, False), right.detect_changes(left))

    def test_file_detect_changes(self):
        left = InventoryEntry('123', 'hello.c', 'file', ROOT_ID)
        left.text_sha1 = 123
        right = InventoryEntry('123', 'hello.c', 'file', ROOT_ID)
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
        left = InventoryEntry('123', 'hello.c', 'symlink', ROOT_ID)
        left.text_sha1 = 123
        left.executable = True
        left.symlink_target='foo'
        right = InventoryEntry('123', 'hello.c', 'symlink', ROOT_ID)
        right.text_sha1 = 321
        right.symlink_target='foo'
        self.assertEqual((False, False), left.detect_changes(right))
        self.assertEqual((False, False), right.detect_changes(left))
        left.symlink_target = 'different'
        self.assertEqual((True, False), left.detect_changes(right))
        self.assertEqual((True, False), right.detect_changes(left))

    def test_file_has_text(self):
        file = InventoryEntry('123', 'hello.c', 'file', ROOT_ID)
        self.failUnless(file.has_text())

    def test_directory_has_text(self):
        dir = InventoryEntry('123', 'hello.c', 'directory', ROOT_ID)
        self.failIf(dir.has_text())

    def test_link_has_text(self):
        link = InventoryEntry('123', 'hello.c', 'symlink', ROOT_ID)
        self.failIf(link.has_text())


class TestEntryDiffing(TestCaseInTempDir):

    def setUp(self):
        super(TestEntryDiffing, self).setUp()
        self.branch = Branch.initialize('.')
        print >> open('file', 'wb'), 'foo'
        self.branch.add(['file'], ['fileid'])
        if has_symlinks():
            os.symlink('target1', 'symlink')
            self.branch.add(['symlink'], ['linkid'])
        self.branch.commit('message_1', rev_id = '1')
        print >> open('file', 'wb'), 'bar'
        if has_symlinks():
            os.unlink('symlink')
            os.symlink('target2', 'symlink')
        self.tree_1 = self.branch.revision_tree('1')
        self.inv_1 = self.branch.get_inventory('1')
        self.file_1 = self.inv_1['fileid']
        self.tree_2 = self.branch.working_tree()
        self.inv_2 = self.branch.inventory
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
        
    def test_link_diff_deleted(self):
        output = StringIO()
        self.link_1.diff(internal_diff, 
                          "old_label", self.tree_1,
                          "/dev/null", None, None,
                          output)
        self.assertEqual(output.getvalue(),
                         "=== target was 'target1'\n")

    def test_link_diff_added(self):
        output = StringIO()
        self.link_1.diff(internal_diff, 
                          "new_label", self.tree_1,
                          "/dev/null", None, None,
                          output, reverse=True)
        self.assertEqual(output.getvalue(),
                         "=== target is 'target1'\n")

    def test_link_diff_changed(self):
        output = StringIO()
        self.link_1.diff(internal_diff, 
                          "/dev/null", self.tree_1, 
                          "new_label", self.link_2, self.tree_2,
                          output)
        self.assertEqual(output.getvalue(),
                         "=== target changed 'target1' => 'target2'\n")
