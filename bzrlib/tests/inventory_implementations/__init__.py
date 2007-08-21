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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

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
        multiply_tests_from_modules,
        )


class TestInventoryBasics(TestCase):
    # Most of these were moved the rather old bzrlib.tests.test_inv module
    
    def make_inventory(self, root_id):
        return self.inventory_class(root_id=root_id)

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
                     ('Makefile', 'file', 'makefile-id')]:
            inv.add_path(*args)
        self.assertEqual([
            ('', 'tree-root'),
            ('Makefile', 'makefile-id'),
            ('doc', 'doc-id'),
            ('src', 'src-id'),
            ('src/bye.c', 'bye-id'),
            ('src/hello.c', 'hello-id'),
            ], [(path, ie.file_id) for path, ie in inv.iter_entries()])

    def test_iter_entries_by_dir(self):
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

    def test_add_recursive(self):
        parent = InventoryDirectory('src-id', 'src', 'tree-root')
        child = InventoryFile('hello-id', 'hello.c', 'src-id')
        parent.children[child.file_id] = child
        inv = self.make_inventory('tree-root')
        inv.add(parent)
        self.assertEqual('src/hello.c', inv.id2path('hello-id'))


def _inventory_test_scenarios():
    """Return a sequence of test scenarios.

    Each scenario is (scenario_name_suffix, params).  The params are each 
    set as attributes on the test case.
    """
    from bzrlib.inventory import (
        Inventory,
        )
    yield ('Inventory', dict(inventory_class=Inventory))


def test_suite():
    """Generate suite containing all parameterized tests"""
    modules_to_test = [
            'bzrlib.tests.inventory_implementations',
            ]
    return multiply_tests_from_modules(modules_to_test,
            _inventory_test_scenarios())
