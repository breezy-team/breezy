# Copyright (C) 2006 Jelmer Vernooij <jelmer@samba.org>

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

from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir
from bzrlib.delta import compare_trees
from bzrlib.errors import NoSuchRevision, NoSuchFile
from bzrlib.inventory import Inventory, ROOT_ID
from bzrlib.trace import mutter
from bzrlib.tree import EmptyTree
from bzrlib.workingtree import WorkingTree

import os
import format
import checkout
from tests import TestCaseWithSubversionRepository, RENAMES

class TestWorkingTree(TestCaseWithSubversionRepository):
    def test_add_duplicate(self):
        self.make_client_and_bzrdir('a', 'dc')
        self.build_tree({"dc/bl": "data"})
        self.client_add("dc/bl")
        tree = WorkingTree.open("dc")
        tree.add(["bl"])

    def test_add_unexisting(self):
        self.make_client_and_bzrdir('a', 'dc')
        tree = WorkingTree.open("dc")
        self.assertRaises(NoSuchFile, tree.add, ["bl"])

    def test_add(self):
        self.make_client_and_bzrdir('a', 'dc')
        self.build_tree({"dc/bl": "data"})
        tree = WorkingTree.open("dc")
        tree.add(["bl"])

        inv = tree.read_working_inventory()
        self.assertIsInstance(inv, Inventory)
        self.assertTrue(inv.has_filename("bl"))
        self.assertFalse(inv.has_filename("aa"))

    def test_add_reopen(self):
        self.make_client_and_bzrdir('a', 'dc')
        self.build_tree({"dc/bl": "data"})
        tree = WorkingTree.open("dc")
        tree.add(["bl"])

        inv = WorkingTree.open("dc").read_working_inventory()
        self.assertTrue(inv.has_filename("bl"))

    def test_remove(self):
        self.make_client_and_bzrdir('a', 'dc')
        self.build_tree({"dc/bl": "data"})
        tree = WorkingTree.open("dc")
        tree.add(["bl"])
        tree.remove(["bl"])
        inv = tree.read_working_inventory()
        self.assertFalse(inv.has_filename("bl"))

    def test_remove_dup(self):
        self.make_client_and_bzrdir('a', 'dc')
        self.build_tree({"dc/bl": "data"})
        tree = WorkingTree.open("dc")
        tree.add(["bl"])
        os.remove("dc/bl")
        inv = tree.read_working_inventory()
        self.assertFalse(inv.has_filename("bl"))

    def test_is_control_file(self):
        self.make_client_and_bzrdir('a', 'dc')
        tree = WorkingTree.open("dc")
        self.assertTrue(tree.is_control_filename(".svn"))
        self.assertFalse(tree.is_control_filename(".bzr"))

    def test_revert(self):
        self.make_client_and_bzrdir('a', 'dc')
        self.build_tree({"dc/bl": "data"})
        self.client_add("dc/bl")
        self.client_commit("dc", "Bla")
        tree = WorkingTree.open("dc")
        os.remove("dc/bl")
        tree.revert(["bl"])
        self.assertEqual("data", open('dc/bl').read())

    def test_rename_one(self):
        self.make_client_and_bzrdir('a', 'dc')
        self.build_tree({"dc/bl": "data"})
        self.client_add("dc/bl")
        self.client_commit("dc", "Bla")
        tree = WorkingTree.open("dc")
        tree.rename_one("bl", "bloe")
        
        basis_inv = tree.basis_tree().inventory
        inv = tree.read_working_inventory()
        self.assertFalse(inv.has_filename("bl"))
        self.assertTrue(inv.has_filename("bloe"))
        self.assertEqual(basis_inv.path2id("bl"), 
                         inv.path2id("bloe"))
        self.assertIs(None, inv.path2id("bl"))
        self.assertIs(None, basis_inv.path2id("bloe"))

    def test_empty_basis_tree(self):
        self.make_client_and_bzrdir('a', 'dc')
        tree = WorkingTree.open("dc")
        self.assertIsInstance(tree.basis_tree(), EmptyTree)

    def test_basis_tree(self):
        self.make_client_and_bzrdir('a', 'dc')
        self.build_tree({"dc/bl": "data"})
        self.client_add("dc/bl")
        self.client_commit("dc", "Bla")
        tree = WorkingTree.open("dc")
        self.assertEqual("svn-v1:1@%s-" % tree.branch.repository.uuid,
                         tree.basis_tree().get_revision_id())

    def test_move(self):
        self.make_client_and_bzrdir('a', 'dc')
        self.build_tree({"dc/bl": "data", "dc/a": "data2", "dc/dir": None})
        self.client_add("dc/bl")
        self.client_add("dc/a")
        self.client_add("dc/dir")
        self.client_commit("dc", "Bla")
        tree = WorkingTree.open("dc")
        tree.move(["bl", "a"], "dir")
        
        basis_inv = tree.basis_tree().inventory
        inv = tree.read_working_inventory()
        self.assertFalse(inv.has_filename("bl"))
        self.assertFalse(inv.has_filename("a"))
        self.assertTrue(inv.has_filename("dir/bl"))
        self.assertTrue(inv.has_filename("dir/a"))
        mutter('basis: %r' % basis_inv.entries())
        mutter('working: %r' % inv.entries())
        if RENAMES:
            self.assertEqual(basis_inv.path2id("bl"), 
                             inv.path2id("dir/bl"))
            self.assertEqual(basis_inv.path2id("a"), 
                            inv.path2id("dir/a"))
        self.assertFalse(inv.has_filename("bl"))
        self.assertFalse(basis_inv.has_filename("dir/bl"))

    def test_pending_merges(self):
        self.make_client_and_bzrdir('a', 'dc')
        self.build_tree({"dc/bl": "data"})
        tree = WorkingTree.open("dc")
        self.assertEqual([], tree.pending_merges())
 
    def test_delta(self):
        self.make_client_and_bzrdir('a', 'dc')
        self.build_tree({"dc/bl": "data"})
        self.client_add("dc/bl")
        self.build_tree({"dc/bl": "data"})
        self.client_commit("dc", "Bla")
        self.build_tree({"dc/bl": "data2"})
        tree = WorkingTree.open("dc")
        basis = tree.basis_tree()
        delta = compare_trees(tree.basis_tree(), tree)
        self.assertEqual("bl", delta.modified[0][0])
 
    def test_working_inventory(self):
        self.make_client_and_bzrdir('a', 'dc')
        self.build_tree({"dc/bl": "data", "dc/foo/bar": "bla", "dc/foo/bla": "aa"})
        self.client_add("dc/bl")
        self.client_add("dc/foo")
        self.client_commit("dc", "bla")
        self.build_tree({"dc/test": "data"})
        self.client_add("dc/test")
        tree = WorkingTree.open("dc")
        inv = tree.read_working_inventory()
        self.assertEqual(ROOT_ID, inv.path2id(""))
        self.assertTrue(inv.path2id("foo") != "")
        self.assertTrue(inv.has_filename("bl"))
        self.assertTrue(inv.has_filename("foo"))
        self.assertTrue(inv.has_filename("foo/bar"))
        self.assertTrue(inv.has_filename("test"))

    def test_ignore_list(self):
        self.make_client_and_bzrdir('a', 'dc')
        self.build_tree({"dc/bl": None})
        self.client_add("dc/bl")
        self.client_set_prop("dc/bl", "svn:ignore", "test.*\n")
        self.client_commit("dc", "bla")
        self.client_set_prop("dc", "svn:ignore", "foo\nbar\n")

        tree = WorkingTree.open("dc")
        ignorelist = tree.get_ignore_list()
        self.assertTrue("bl/test.*" in ignorelist)
        self.assertTrue("foo" in ignorelist)
        self.assertTrue("bar" in ignorelist)

    def test_is_ignored(self):
        self.make_client_and_bzrdir('a', 'dc')
        self.build_tree({"dc/bl": None})
        self.client_add("dc/bl")
        self.client_set_prop("dc/bl", "svn:ignore", "test.*\n")
        self.client_commit("dc", "bla")
        self.client_set_prop("dc", "svn:ignore", "foo\nbar\n")

        tree = WorkingTree.open("dc")
        self.assertTrue(tree.is_ignored("bl/test.foo"))
        self.assertFalse(tree.is_ignored("bl/notignored"))
        self.assertTrue(tree.is_ignored("foo"))
        self.assertTrue(tree.is_ignored("bar"))
        self.assertFalse(tree.is_ignored("alsonotignored"))

    def test_ignore_controldir(self):
        self.make_client_and_bzrdir('a', 'dc')
        tree = WorkingTree.open("dc")
        self.assertEqual([], list(tree.unknowns()))

    def test_unknowns(self):
        self.make_client_and_bzrdir('a', 'dc')
        self.build_tree({"dc/bl": None})

        tree = WorkingTree.open("dc")
        self.assertEqual(['bl'], list(tree.unknowns()))

    def test_extras(self):
        self.make_client_and_bzrdir('a', 'dc')
        self.build_tree({"dc/bl": None})

        tree = WorkingTree.open("dc")
        self.assertEqual(['.svn', 'bl'], list(tree.extras()))

    def test_pending_merges(self):
        self.make_client_and_bzrdir('a', 'dc')
        self.build_tree({"dc/bl": None})

        tree = WorkingTree.open("dc")
        tree.set_pending_merges(["a", "c"])
        self.assertEqual(["a", "c"], tree.pending_merges())
        tree.set_pending_merges([])
        self.assertEqual([], tree.pending_merges())

    def test_update_after_commit(self):
        self.make_client_and_bzrdir('a', 'dc')
        self.build_tree({"dc/bl": "data"})
        self.client_add("dc/bl")
        tree = WorkingTree.open("dc")
        orig_tree = tree.basis_tree()
        tree.commit(message="data")
        self.assertEqual("svn-v1:1@%s-" % tree.branch.repository.uuid, 
                         tree.basis_tree().get_revision_id())
        delta = compare_trees(orig_tree, tree.basis_tree())
        self.assertTrue(delta.has_changed())
        tree = WorkingTree.open("dc")
        delta = compare_trees(tree, tree.basis_tree())
        self.assertEqual("svn-v1:1@%s-" % tree.branch.repository.uuid, 
                         tree.basis_tree().get_revision_id())
        self.assertFalse(delta.has_changed())

