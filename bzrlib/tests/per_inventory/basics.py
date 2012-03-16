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
        inventory,
        osutils,
        )

from bzrlib.inventory import (
        InventoryDirectory,
        InventoryEntry,
        InventoryFile,
        InventoryLink,
        TreeReference,
        )

from bzrlib.tests.per_inventory import TestCaseWithInventory

from bzrlib.symbol_versioning import (
    deprecated_in,
    )


class TestInventory(TestCaseWithInventory):

    def make_init_inventory(self):
        inv = inventory.Inventory('tree-root')
        inv.revision = 'initial-rev'
        inv.root.revision = 'initial-rev'
        return self.inv_to_test_inv(inv)

    def make_file(self, file_id, name, parent_id, content='content\n',
                  revision='new-test-rev'):
        ie = InventoryFile(file_id, name, parent_id)
        ie.text_sha1 = osutils.sha_string(content)
        ie.text_size = len(content)
        ie.revision = revision
        return ie

    def make_link(self, file_id, name, parent_id, target='link-target\n'):
        ie = InventoryLink(file_id, name, parent_id)
        ie.symlink_target = target
        return ie

    def prepare_inv_with_nested_dirs(self):
        inv = inventory.Inventory('tree-root')
        for args in [('src', 'directory', 'src-id'),
                     ('doc', 'directory', 'doc-id'),
                     ('src/hello.c', 'file', 'hello-id'),
                     ('src/bye.c', 'file', 'bye-id'),
                     ('zz', 'file', 'zz-id'),
                     ('src/sub/', 'directory', 'sub-id'),
                     ('src/zz.c', 'file', 'zzc-id'),
                     ('src/sub/a', 'file', 'a-id'),
                     ('Makefile', 'file', 'makefile-id')]:
            ie = inv.add_path(*args)
            if args[1] == 'file':
                ie.text_sha1 = osutils.sha_string('content\n')
                ie.text_size = len('content\n')
        return self.inv_to_test_inv(inv)


class TestInventoryCreateByApplyDelta(TestInventory):
    """A subset of the inventory delta application tests.

    See test_inv which has comprehensive delta application tests for
    inventories, dirstate, and repository based inventories.
    """
    def test_add(self):
        inv = self.make_init_inventory()
        inv = inv.create_by_apply_delta([
            (None, "a", "a-id", self.make_file('a-id', 'a', 'tree-root')),
            ], 'new-test-rev')
        self.assertEqual('a', inv.id2path('a-id'))

    def test_delete(self):
        inv = self.make_init_inventory()
        inv = inv.create_by_apply_delta([
            (None, "a", "a-id", self.make_file('a-id', 'a', 'tree-root')),
            ], 'new-rev-1')
        self.assertEqual('a', inv.id2path('a-id'))
        inv = inv.create_by_apply_delta([
            ("a", None, "a-id", None),
            ], 'new-rev-2')
        self.assertRaises(errors.NoSuchId, inv.id2path, 'a-id')

    def test_rename(self):
        inv = self.make_init_inventory()
        inv = inv.create_by_apply_delta([
            (None, "a", "a-id", self.make_file('a-id', 'a', 'tree-root')),
            ], 'new-rev-1')
        self.assertEqual('a', inv.id2path('a-id'))
        a_ie = inv['a-id']
        b_ie = self.make_file(a_ie.file_id, "b", a_ie.parent_id)
        inv = inv.create_by_apply_delta([("a", "b", "a-id", b_ie)], 'new-rev-2')
        self.assertEqual("b", inv.id2path('a-id'))

    def test_illegal(self):
        # A file-id cannot appear in a delta more than once
        inv = self.make_init_inventory()
        self.assertRaises(errors.InconsistentDelta, inv.create_by_apply_delta, [
            (None, "a", "id-1", self.make_file('id-1', 'a', 'tree-root')),
            (None, "b", "id-1", self.make_file('id-1', 'b', 'tree-root')),
            ], 'new-rev-1')


class TestInventoryReads(TestInventory):

    def test_is_root(self):
        """Ensure our root-checking code is accurate."""
        inv = self.make_init_inventory()
        self.assertTrue(inv.is_root('tree-root'))
        self.assertFalse(inv.is_root('booga'))
        ie = inv['tree-root'].copy()
        ie.file_id = 'booga'
        inv = inv.create_by_apply_delta([("", None, "tree-root", None),
                                         (None, "", "booga", ie)], 'new-rev-2')
        self.assertFalse(inv.is_root('TREE_ROOT'))
        self.assertTrue(inv.is_root('booga'))

    def test_ids(self):
        """Test detection of files within selected directories."""
        inv = inventory.Inventory('TREE_ROOT')
        for args in [('src', 'directory', 'src-id'),
                     ('doc', 'directory', 'doc-id'),
                     ('src/hello.c', 'file'),
                     ('src/bye.c', 'file', 'bye-id'),
                     ('Makefile', 'file')]:
            ie = inv.add_path(*args)
            if args[1] == 'file':
                ie.text_sha1 = osutils.sha_string('content\n')
                ie.text_size = len('content\n')
        inv = self.inv_to_test_inv(inv)
        self.assertEqual(inv.path2id('src'), 'src-id')
        self.assertEqual(inv.path2id('src/bye.c'), 'bye-id')

    def test_non_directory_children(self):
        """Test path2id when a parent directory has no children"""
        inv = inventory.Inventory('tree-root')
        inv.add(self.make_file('file-id','file', 'tree-root'))
        inv.add(self.make_link('link-id','link', 'tree-root'))
        self.assertIs(None, inv.path2id('file/subfile'))
        self.assertIs(None, inv.path2id('link/subfile'))

    def test_iter_entries(self):
        inv = self.prepare_inv_with_nested_dirs()

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
            ('src/zz.c', 'zzc-id'),
            ('zz', 'zz-id'),
            ], [(path, ie.file_id) for path, ie in inv.iter_entries()])

        # Test a subdirectory
        self.assertEqual([
            ('bye.c', 'bye-id'),
            ('hello.c', 'hello-id'),
            ('sub', 'sub-id'),
            ('sub/a', 'a-id'),
            ('zz.c', 'zzc-id'),
            ], [(path, ie.file_id) for path, ie in inv.iter_entries(
            from_dir='src-id')])

        # Test not recursing at the root level
        self.assertEqual([
            ('', 'tree-root'),
            ('Makefile', 'makefile-id'),
            ('doc', 'doc-id'),
            ('src', 'src-id'),
            ('zz', 'zz-id'),
            ], [(path, ie.file_id) for path, ie in inv.iter_entries(
            recursive=False)])

        # Test not recursing at a subdirectory level
        self.assertEqual([
            ('bye.c', 'bye-id'),
            ('hello.c', 'hello-id'),
            ('sub', 'sub-id'),
            ('zz.c', 'zzc-id'),
            ], [(path, ie.file_id) for path, ie in inv.iter_entries(
            from_dir='src-id', recursive=False)])

    def test_iter_just_entries(self):
        inv = self.prepare_inv_with_nested_dirs()
        self.assertEqual([
            'a-id',
            'bye-id',
            'doc-id',
            'hello-id',
            'makefile-id',
            'src-id',
            'sub-id',
            'tree-root',
            'zz-id',
            'zzc-id',
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

    def test_inv_filter_entry_not_present(self):
        inv = self.prepare_inv_with_nested_dirs()
        new_inv = inv.filter(['not-present-id'])
        self.assertEqual([
            ('', 'tree-root'),
            ], [(path, ie.file_id) for path, ie in new_inv.iter_entries()])
