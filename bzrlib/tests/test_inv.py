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

from bzrlib import errors, inventory, osutils
from bzrlib.inventory import (Inventory, ROOT_ID, InventoryFile,
    InventoryDirectory, InventoryEntry, TreeReference)
from bzrlib.osutils import (pathjoin, is_inside_any, 
    is_inside_or_parent_of_any)
from bzrlib.tests import TestCase


class TestInventory(TestCase):

    def test_add_path(self):

        inv = Inventory(root_id=None)
        self.assertIs(None, inv.root)
        ie = inv.add_path("", "directory", "my-root")
        self.assertEqual("my-root", ie.file_id)
        self.assertIs(ie, inv.root)

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
            ], [(path, ie.file_id) for path, ie in inv.iter_entries_by_dir(
                specific_file_ids=('a-id', 'zzc-id', 'doc-id', ROOT_ID,
                'hello-id', 'bye-id', 'zz-id', 'src-id', 'makefile-id', 
                'sub-id'))])

        self.assertEqual([
            ('Makefile', 'makefile-id'),
            ('doc', 'doc-id'),
            ('zz', 'zz-id'),
            ('src/bye.c', 'bye-id'),
            ('src/hello.c', 'hello-id'),
            ('src/zz.c', 'zzc-id'),
            ('src/sub/a', 'a-id'),
            ], [(path, ie.file_id) for path, ie in inv.iter_entries_by_dir(
                specific_file_ids=('a-id', 'zzc-id', 'doc-id',
                'hello-id', 'bye-id', 'zz-id', 'makefile-id'))])

        self.assertEqual([
            ('Makefile', 'makefile-id'),
            ('src/bye.c', 'bye-id'),
            ], [(path, ie.file_id) for path, ie in inv.iter_entries_by_dir(
                specific_file_ids=('bye-id', 'makefile-id'))])

        self.assertEqual([
            ('Makefile', 'makefile-id'),
            ('src/bye.c', 'bye-id'),
            ], [(path, ie.file_id) for path, ie in inv.iter_entries_by_dir(
                specific_file_ids=('bye-id', 'makefile-id'))])

        self.assertEqual([
            ('src/bye.c', 'bye-id'),
            ], [(path, ie.file_id) for path, ie in inv.iter_entries_by_dir(
                specific_file_ids=('bye-id',))])

    def test_add_recursive(self):
        parent = InventoryDirectory('src-id', 'src', ROOT_ID)
        child = InventoryFile('hello-id', 'hello.c', 'src-id')
        parent.children[child.file_id] = child
        inv = Inventory()
        inv.add(parent)
        self.assertEqual('src/hello.c', inv.id2path('hello-id'))


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


class TestEncoding(TestCase):

    def test_error_encoding(self):
        inv = Inventory('tree-root')
        inv.add(InventoryFile('a-id', u'\u1234', 'tree-root'))
        try:
            inv.add(InventoryFile('b-id', u'\u1234', 'tree-root'))
        except errors.BzrError, e:
            self.assertContainsRe(str(e), u'\u1234'.encode('utf-8'))
