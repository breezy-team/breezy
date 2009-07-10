# Copyright (C) 2005, 2006, 2007 Canonical Ltd
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

"""Tests for different inventory implementations"""

# NOTE: Don't import Inventory here, to make sure that we don't accidentally
# hardcode that when we should be using self.make_inventory

from bzrlib import (
        errors,
        )

from bzrlib.inventory import (
        InventoryDirectory,
        InventoryEntry,
        InventoryFile,
        InventoryLink,
        ROOT_ID,
        TreeReference,
        )

from bzrlib.tests import (
        TestCase,
        )


class TestInventory(TestCase):

    def make_inventory(self, root_id):
        return self.inventory_class(root_id=root_id)

    def prepare_inv_with_nested_dirs(self):
        inv = self.make_inventory('tree-root')
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
        return inv


class TestInventoryUpdates(TestInventory):

    def test_creation_from_root_id(self):
        # iff a root id is passed to the constructor, a root directory is made
        inv = self.make_inventory(root_id='tree-root')
        self.assertNotEqual(None, inv.root)
        self.assertEqual('tree-root', inv.root.file_id)

    def test_add_path_of_root(self):
        # if no root id is given at creation time, there is no root directory
        inv = self.make_inventory(root_id=None)
        self.assertIs(None, inv.root)
        # add a root entry by adding its path
        ie = inv.add_path("", "directory", "my-root")
        self.assertEqual("my-root", ie.file_id)
        self.assertIs(ie, inv.root)

    def test_add_path(self):
        inv = self.make_inventory(root_id='tree_root')
        ie = inv.add_path('hello', 'file', 'hello-id')
        self.assertEqual('hello-id', ie.file_id)
        self.assertEqual('file', ie.kind)

    def test_copy(self):
        """Make sure copy() works and creates a deep copy."""
        inv = self.make_inventory(root_id='some-tree-root')
        ie = inv.add_path('hello', 'file', 'hello-id')
        inv2 = inv.copy()
        inv.root.file_id = 'some-new-root'
        ie.name = 'file2'
        self.assertEqual('some-tree-root', inv2.root.file_id)
        self.assertEqual('hello', inv2['hello-id'].name)

    def test_copy_empty(self):
        """Make sure an empty inventory can be copied."""
        inv = self.make_inventory(root_id=None)
        inv2 = inv.copy()
        self.assertIs(None, inv2.root)

    def test_copy_copies_root_revision(self):
        """Make sure the revision of the root gets copied."""
        inv = self.make_inventory(root_id='someroot')
        inv.root.revision = 'therev'
        inv2 = inv.copy()
        self.assertEquals('someroot', inv2.root.file_id)
        self.assertEquals('therev', inv2.root.revision)

    def test_create_tree_reference(self):
        inv = self.make_inventory('tree-root-123')
        inv.add(TreeReference('nested-id', 'nested', parent_id='tree-root-123',
                              revision='rev', reference_revision='rev2'))

    def test_error_encoding(self):
        inv = self.make_inventory('tree-root')
        inv.add(InventoryFile('a-id', u'\u1234', 'tree-root'))
        try:
            inv.add(InventoryFile('b-id', u'\u1234', 'tree-root'))
        except errors.BzrError, e:
            self.assertContainsRe(str(e), u'\u1234'.encode('utf-8'))
        else:
            self.fail('BzrError not raised')

    def test_add_recursive(self):
        parent = InventoryDirectory('src-id', 'src', 'tree-root')
        child = InventoryFile('hello-id', 'hello.c', 'src-id')
        parent.children[child.file_id] = child
        inv = self.make_inventory('tree-root')
        inv.add(parent)
        self.assertEqual('src/hello.c', inv.id2path('hello-id'))


class TestInventoryApplyDelta(TestInventory):

    def test_apply_delta_add(self):
        inv = self.make_inventory('tree-root')
        inv.apply_delta([
            (None, "a", "a-id", InventoryFile('a-id', 'a', 'tree-root')),
            ])
        self.assertEqual('a', inv.id2path('a-id'))

    def test_apply_delta_delete(self):
        inv = self.make_inventory('tree-root')
        inv.apply_delta([
            (None, "a", "a-id", InventoryFile('a-id', 'a', 'tree-root')),
            ])
        self.assertEqual('a', inv.id2path('a-id'))
        a_ie = inv['a-id']
        inv.apply_delta([("a", None, "a-id", a_ie)])
        self.assertRaises(errors.NoSuchId, inv.id2path, 'a-id')

    def test_apply_delta_rename(self):
        inv = self.make_inventory('tree-root')
        inv.apply_delta([
            (None, "a", "a-id", InventoryFile('a-id', 'a', 'tree-root')),
            ])
        self.assertEqual('a', inv.id2path('a-id'))
        a_ie = inv['a-id']
        b_ie = InventoryFile(a_ie.file_id, "b", a_ie.parent_id)
        inv.apply_delta([("a", "b", "a-id", b_ie)])
        self.assertEqual("b", inv.id2path('a-id'))

    def test_apply_delta_illegal(self):
        # A file-id cannot appear in a delta more than once
        inv = self.make_inventory('tree-root')
        self.assertRaises(AssertionError, inv.apply_delta, [
            ("a", "a", "id-1", InventoryFile('id-1', 'a', 'tree-root')),
            ("a", "b", "id-1", InventoryFile('id-1', 'b', 'tree-root')),
            ])


class TestInventoryReads(TestInventory):

    def test_is_root(self):
        """Ensure our root-checking code is accurate."""
        inv = self.make_inventory('TREE_ROOT')
        self.assertTrue(inv.is_root('TREE_ROOT'))
        self.assertFalse(inv.is_root('booga'))
        inv.root.file_id = 'booga'
        self.assertFalse(inv.is_root('TREE_ROOT'))
        self.assertTrue(inv.is_root('booga'))
        # works properly even if no root is set
        inv.root = None
        self.assertFalse(inv.is_root('TREE_ROOT'))
        self.assertFalse(inv.is_root('booga'))

    def test_ids(self):
        """Test detection of files within selected directories."""
        inv = self.make_inventory(ROOT_ID)
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
        inv = self.make_inventory('tree_root')
        inv.add(InventoryFile('file-id','file',
                                        parent_id='tree_root'))
        inv.add(InventoryLink('link-id','link',
                                        parent_id='tree_root'))
        self.assertIs(None, inv.path2id('file/subfile'))
        self.assertIs(None, inv.path2id('link/subfile'))

    def test_iter_entries(self):
        inv = self.make_inventory('tree-root')
        for args in [('src', 'directory', 'src-id'),
                     ('doc', 'directory', 'doc-id'),
                     ('src/hello.c', 'file', 'hello-id'),
                     ('src/bye.c', 'file', 'bye-id'),
                     ('src/sub', 'directory', 'sub-id'),
                     ('src/sub/a', 'file', 'a-id'),
                     ('Makefile', 'file', 'makefile-id')]:
            inv.add_path(*args)

        # Test all entries
        self.assertEqual([
            ('', 'tree-root'),
            ('Makefile', 'makefile-id'),
            ('doc', 'doc-id'),
            ('src', 'src-id'),
            ('src/bye.c', 'bye-id'),
            ('src/hello.c', 'hello-id'),
            ('src/sub', 'sub-id'),
            ('src/sub/a', 'a-id'),
            ], [(path, ie.file_id) for path, ie in inv.iter_entries()])

        # Test a subdirectory
        self.assertEqual([
            ('bye.c', 'bye-id'),
            ('hello.c', 'hello-id'),
            ('sub', 'sub-id'),
            ('sub/a', 'a-id'),
            ], [(path, ie.file_id) for path, ie in inv.iter_entries(
            from_dir='src-id')])

        # Test not recursing at the root level
        self.assertEqual([
            ('', 'tree-root'),
            ('Makefile', 'makefile-id'),
            ('doc', 'doc-id'),
            ('src', 'src-id'),
            ], [(path, ie.file_id) for path, ie in inv.iter_entries(
            recursive=False)])

        # Test not recursing at a subdirectory level
        self.assertEqual([
            ('bye.c', 'bye-id'),
            ('hello.c', 'hello-id'),
            ('sub', 'sub-id'),
            ], [(path, ie.file_id) for path, ie in inv.iter_entries(
            from_dir='src-id', recursive=False)])

    def test_iter_just_entries(self):
        inv = self.make_inventory('tree-root')
        for args in [('src', 'directory', 'src-id'),
                     ('doc', 'directory', 'doc-id'),
                     ('src/hello.c', 'file', 'hello-id'),
                     ('src/bye.c', 'file', 'bye-id'),
                     ('Makefile', 'file', 'makefile-id')]:
            inv.add_path(*args)
        self.assertEqual([
            'bye-id',
            'doc-id',
            'hello-id',
            'makefile-id',
            'src-id',
            'tree-root',
            ], sorted([ie.file_id for ie in inv.iter_just_entries()]))

    def test_iter_entries_by_dir(self):
        inv = self. prepare_inv_with_nested_dirs()
        self.assertEqual([
            ('', 'tree-root'),
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
            ('', 'tree-root'),
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
                specific_file_ids=('a-id', 'zzc-id', 'doc-id', 'tree-root',
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

        self.assertEqual([
            ('', 'tree-root'),
            ('src', 'src-id'),
            ('src/bye.c', 'bye-id'),
            ], [(path, ie.file_id) for path, ie in inv.iter_entries_by_dir(
                specific_file_ids=('bye-id',), yield_parents=True)])
 

class TestInventoryFiltering(TestInventory):

    def test_inv_filter_empty(self):
        inv = self.prepare_inv_with_nested_dirs()
        new_inv = inv.filter([])
        self.assertEqual([
            ('', 'tree-root'),
            ], [(path, ie.file_id) for path, ie in new_inv.iter_entries()])
    
    def test_inv_filter_files(self):
        inv = self.prepare_inv_with_nested_dirs()
        new_inv = inv.filter(['zz-id', 'hello-id', 'a-id'])
        self.assertEqual([
            ('', 'tree-root'),
            ('src', 'src-id'),
            ('src/hello.c', 'hello-id'),
            ('src/sub', 'sub-id'),
            ('src/sub/a', 'a-id'),
            ('zz', 'zz-id'),
            ], [(path, ie.file_id) for path, ie in new_inv.iter_entries()])
    
    def test_inv_filter_dirs(self):
        inv = self.prepare_inv_with_nested_dirs()
        new_inv = inv.filter(['doc-id', 'sub-id'])
        self.assertEqual([
            ('', 'tree-root'),
            ('doc', 'doc-id'),
            ('src', 'src-id'),
            ('src/sub', 'sub-id'),
            ('src/sub/a', 'a-id'),
            ], [(path, ie.file_id) for path, ie in new_inv.iter_entries()])

    def test_inv_filter_files_and_dirs(self):
        inv = self.prepare_inv_with_nested_dirs()
        new_inv = inv.filter(['makefile-id', 'src-id'])
        self.assertEqual([
            ('', 'tree-root'),
            ('Makefile', 'makefile-id'),
            ('src', 'src-id'),
            ('src/bye.c', 'bye-id'),
            ('src/hello.c', 'hello-id'),
            ('src/sub', 'sub-id'),
            ('src/sub/a', 'a-id'),
            ('src/zz.c', 'zzc-id'),
            ], [(path, ie.file_id) for path, ie in new_inv.iter_entries()])
