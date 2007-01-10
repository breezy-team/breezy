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
from bzrlib.errors import NoSuchRevision, NoSuchFile
from bzrlib.inventory import Inventory, ROOT_ID
from bzrlib.revision import NULL_REVISION
from bzrlib.trace import mutter
from bzrlib.workingtree import WorkingTree

import svn.core
import svn.wc

import os

import format
import checkout
from repository import MAPPING_VERSION
import tree
from tests import TestCaseWithSubversionRepository, RENAMES

class TestWorkingTree(TestCaseWithSubversionRepository):
    def test_add_duplicate(self):
        self.make_client('a', 'dc')
        self.build_tree({"dc/bl": "data"})
        self.client_add("dc/bl")
        tree = WorkingTree.open("dc")
        tree.add(["bl"])

    def test_add_unexisting(self):
        self.make_client('a', 'dc')
        tree = WorkingTree.open("dc")
        self.assertRaises(NoSuchFile, tree.add, ["bl"])

    def test_add(self):
        self.make_client('a', 'dc')
        self.build_tree({"dc/bl": "data"})
        tree = WorkingTree.open("dc")
        tree.add(["bl"])

        inv = tree.read_working_inventory()
        self.assertIsInstance(inv, Inventory)
        self.assertTrue(inv.has_filename("bl"))
        self.assertFalse(inv.has_filename("aa"))

    def test_lock_write(self):
        self.make_client('a', 'dc')
        tree = WorkingTree.open("dc")
        tree.lock_write()

    def test_lock_read(self):
        self.make_client('a', 'dc')
        tree = WorkingTree.open("dc")
        tree.lock_read()

    def test_unlock(self):
        self.make_client('a', 'dc')
        tree = WorkingTree.open("dc")
        tree.unlock()

    def test_get_ignore_list_empty(self):
        self.make_client('a', 'dc')
        tree = WorkingTree.open("dc")
        self.assertEqual([".svn"] + svn.core.SVN_CONFIG_DEFAULT_GLOBAL_IGNORES.split(" "), tree.get_ignore_list())

    def test_get_ignore_list_onelevel(self):
        self.make_client('a', 'dc')
        self.client_set_prop("dc", "svn:ignore", "*.d\n*.c\n")
        tree = WorkingTree.open("dc")
        self.assertEqual([".svn"] + svn.core.SVN_CONFIG_DEFAULT_GLOBAL_IGNORES.split(" ") + ["./*.d", "./*.c"], tree.get_ignore_list())

    def test_get_ignore_list_morelevel(self):
        self.make_client('a', 'dc')
        self.client_set_prop("dc", "svn:ignore", "*.d\n*.c\n")
        self.build_tree({'dc/x': None})
        self.client_add("dc/x")
        self.client_set_prop("dc/x", "svn:ignore", "*.e\n")
        tree = WorkingTree.open("dc")
        self.assertEqual([".svn"] + svn.core.SVN_CONFIG_DEFAULT_GLOBAL_IGNORES.split(" ") + ["./*.d", "./*.c", "./x/*.e"], tree.get_ignore_list())

    def test_add_reopen(self):
        self.make_client('a', 'dc')
        self.build_tree({"dc/bl": "data"})
        tree = WorkingTree.open("dc")
        tree.add(["bl"])

        inv = WorkingTree.open("dc").read_working_inventory()
        self.assertTrue(inv.has_filename("bl"))

    def test_remove(self):
        self.make_client('a', 'dc')
        self.build_tree({"dc/bl": "data"})
        tree = WorkingTree.open("dc")
        tree.add(["bl"])
        tree.remove(["bl"])
        inv = tree.read_working_inventory()
        self.assertFalse(inv.has_filename("bl"))

    def test_remove_dup(self):
        self.make_client('a', 'dc')
        self.build_tree({"dc/bl": "data"})
        tree = WorkingTree.open("dc")
        tree.add(["bl"])
        os.remove("dc/bl")
        inv = tree.read_working_inventory()
        self.assertFalse(inv.has_filename("bl"))

    def test_is_control_file(self):
        self.make_client('a', 'dc')
        tree = WorkingTree.open("dc")
        self.assertTrue(tree.is_control_filename(".svn"))
        self.assertFalse(tree.is_control_filename(".bzr"))

    def test_revert(self):
        self.make_client('a', 'dc')
        self.build_tree({"dc/bl": "data"})
        self.client_add("dc/bl")
        self.client_commit("dc", "Bla")
        tree = WorkingTree.open("dc")
        os.remove("dc/bl")
        tree.revert(["bl"])
        self.assertEqual("data", open('dc/bl').read())

    def test_rename_one(self):
        self.make_client('a', 'dc')
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
        self.make_client('a', 'dc')
        wt = WorkingTree.open("dc")
        self.assertEqual(NULL_REVISION, wt.basis_tree().inventory.revision_id)
        self.assertEqual(Inventory(), wt.basis_tree().inventory)

    def test_basis_tree(self):
        self.make_client('a', 'dc')
        self.build_tree({"dc/bl": "data"})
        self.client_add("dc/bl")
        self.client_commit("dc", "Bla")
        self.client_update("dc")
        tree = WorkingTree.open("dc")
        self.assertEqual(
            tree.branch.generate_revision_id(1),
            tree.basis_tree().get_revision_id())

    def test_move(self):
        self.make_client('a', 'dc')
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

    def test_pending_merges_empty(self):
        self.make_client('a', 'dc')
        self.build_tree({"dc/bl": "data"})
        tree = WorkingTree.open("dc")
        self.assertEqual([], tree.pending_merges())
 
    def test_delta(self):
        self.make_client('a', 'dc')
        self.build_tree({"dc/bl": "data"})
        self.client_add("dc/bl")
        self.build_tree({"dc/bl": "data"})
        self.client_commit("dc", "Bla")
        self.build_tree({"dc/bl": "data2"})
        tree = WorkingTree.open("dc")
        basis = tree.basis_tree()
        delta = tree.changes_from(tree.basis_tree())
        self.assertEqual("bl", delta.modified[0][0])
 
    def test_working_inventory(self):
        self.make_client('a', 'dc')
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
        self.make_client('a', 'dc')
        self.build_tree({"dc/bl": None})
        self.client_add("dc/bl")
        self.client_set_prop("dc/bl", "svn:ignore", "test.*\n")
        self.client_commit("dc", "bla")
        self.client_set_prop("dc", "svn:ignore", "foo\nbar\n")

        tree = WorkingTree.open("dc")
        ignorelist = tree.get_ignore_list()
        self.assertTrue("./bl/test.*" in ignorelist)
        self.assertTrue("./foo" in ignorelist)
        self.assertTrue("./bar" in ignorelist)

    def test_is_ignored(self):
        self.make_client('a', 'dc')
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
        self.make_client('a', 'dc')
        tree = WorkingTree.open("dc")
        self.assertEqual([], list(tree.unknowns()))

    def test_unknowns(self):
        self.make_client('a', 'dc')
        self.build_tree({"dc/bl": None})

        tree = WorkingTree.open("dc")
        self.assertEqual(['bl'], list(tree.unknowns()))

    def test_extras(self):
        self.make_client('a', 'dc')
        self.build_tree({"dc/bl": None})

        tree = WorkingTree.open("dc")
        self.assertEqual(['.svn', 'bl'], list(tree.extras()))

    def test_executable(self):
        self.make_client('a', 'dc')
        self.build_tree({"dc/bla": "data"})
        self.client_add("dc/bla")
        self.client_set_prop("dc/bla", "svn:executable", "*")
        tree = WorkingTree.open("dc")
        inv = tree.read_working_inventory()
        self.assertTrue(inv[inv.path2id("bla")].executable)

    def test_symlink(self):
        self.make_client('a', 'dc')
        import os
        os.symlink("target", "dc/bla")
        self.client_add("dc/bla")
        tree = WorkingTree.open("dc")
        inv = tree.read_working_inventory()
        self.assertEqual('symlink', inv[inv.path2id("bla")].kind)
        self.assertEqual("target", inv[inv.path2id("bla")].symlink_target)

    def test_pending_merges(self):
        self.make_client('a', 'dc')
        self.build_tree({"dc/bl": None})

        tree = WorkingTree.open("dc")
        tree.set_pending_merges(["a", "c"])
        self.assertEqual(["a", "c"], tree.pending_merges())
        tree.set_pending_merges([])
        self.assertEqual([], tree.pending_merges())

    def test_set_pending_merges_prop(self):
        self.make_client('a', 'dc')
        self.build_tree({"dc/bl": None})
        self.client_add("dc/bl")
        
        tree = WorkingTree.open("dc")
        tree.set_pending_merges([
            "svn-v%d:1@a-uuid-foo-branch%%2fpath" % MAPPING_VERSION, "c"])
        self.assertEqual(
                "svn-v%d:1@a-uuid-foo-branch%%2fpath\tc\n" % MAPPING_VERSION, 
                self.client_get_prop("dc", "bzr:merge"))

    def test_set_pending_merges_svk(self):
        self.make_client('a', 'dc')
        self.build_tree({"dc/bl": None})
        self.client_add("dc/bl")
        
        tree = WorkingTree.open("dc")
        tree.set_pending_merges([
            "svn-v%d:1@a-uuid-foo-branch%%2fpath" % MAPPING_VERSION, "c"])
        self.assertEqual("a-uuid-foo:/branch/path:1\n", 
                         self.client_get_prop("dc", "svk:merge"))

    def test_commit_callback(self):
        self.make_client('a', 'dc')
        self.build_tree({"dc/bl": "data"})
        self.client_add("dc/bl")
        tree = WorkingTree.open("dc")
        orig_tree = tree.basis_tree()
        tree.commit(message_callback=lambda x: "data")

    def test_update_after_commit(self):
        self.make_client('a', 'dc')
        self.build_tree({"dc/bl": "data"})
        self.client_add("dc/bl")
        tree = WorkingTree.open("dc")
        orig_tree = tree.basis_tree()
        tree.commit(message="data")
        self.assertEqual(
                tree.branch.generate_revision_id(1),
                tree.basis_tree().get_revision_id())
        delta = tree.basis_tree().changes_from(orig_tree)
        self.assertTrue(delta.has_changed())
        tree = WorkingTree.open("dc")
        delta = tree.basis_tree().changes_from(tree)
        self.assertEqual(
             tree.branch.generate_revision_id(1),
             tree.basis_tree().get_revision_id())
        self.assertFalse(delta.has_changed())

    def test_status(self):
        self.make_client('a', 'dc')
        tree = WorkingTree.open("dc")
        self.assertTrue(os.path.exists("dc/.svn"))
        self.assertFalse(os.path.exists("dc/.bzr"))
        tree.read_working_inventory()

    def test_status_bzrdir(self):
        self.make_client('a', 'dc')
        bzrdir = BzrDir.open("dc")
        self.assertTrue(os.path.exists("dc/.svn"))
        self.assertTrue(not os.path.exists("dc/.bzr"))
        bzrdir.open_workingtree()

    def test_file_id_consistent(self):
        self.make_client('a', 'dc')
        self.build_tree({'dc/file': 'data'})
        tree = WorkingTree.open("dc")
        tree.add(["file"])
        oldid = tree.inventory.path2id("file")
        tree = WorkingTree.open("dc")
        newid = tree.inventory.path2id("file")
        self.assertEqual(oldid, newid)

    def test_file_id_kept(self):
        self.make_client('a', 'dc')
        self.build_tree({'dc/file': 'data'})
        tree = WorkingTree.open("dc")
        tree.add(["file"], ["fooid"])
        self.assertEqual("fooid", tree.inventory.path2id("file"))
        tree = WorkingTree.open("dc")
        self.assertEqual("fooid", tree.inventory.path2id("file"))

    def test_file_rename_id(self):
        self.make_client('a', 'dc')
        self.build_tree({'dc/file': 'data'})
        tree = WorkingTree.open("dc")
        tree.add(["file"], ["fooid"])
        tree.commit("msg")
        tree.rename_one("file", "file2")
        self.assertEqual(None, tree.inventory.path2id("file"))
        self.assertEqual("fooid", tree.inventory.path2id("file2"))
        tree = WorkingTree.open("dc")
        self.assertEqual("fooid", tree.inventory.path2id("file2"))

    def test_file_id_kept_2(self):
        self.make_client('a', 'dc')
        self.build_tree({'dc/file': 'data', 'dc/other': 'blaid'})
        tree = WorkingTree.open("dc")
        tree.add(["file", "other"], ["fooid", "blaid"])
        self.assertEqual("fooid", tree.inventory.path2id("file"))
        self.assertEqual("blaid", tree.inventory.path2id("other"))

    def test_file_remove_id(self):
        self.make_client('a', 'dc')
        self.build_tree({'dc/file': 'data'})
        tree = WorkingTree.open("dc")
        tree.add(["file"], ["fooid"])
        tree.commit("msg")
        tree.remove(["file"])
        self.assertEqual(None, tree.inventory.path2id("file"))
        tree = WorkingTree.open("dc")
        self.assertEqual(None, tree.inventory.path2id("file"))

    def test_file_move_id(self):
        self.make_client('a', 'dc')
        self.build_tree({'dc/file': 'data', 'dc/dir': None})
        tree = WorkingTree.open("dc")
        tree.add(["file", "dir"], ["fooid", "blaid"])
        tree.commit("msg")
        tree.move(["file"], "dir")
        self.assertEqual(None, tree.inventory.path2id("file"))
        self.assertEqual("fooid", tree.inventory.path2id("dir/file"))
        tree = WorkingTree.open("dc")
        self.assertEqual(None, tree.inventory.path2id("file"))
        self.assertEqual("fooid", tree.inventory.path2id("dir/file"))

    def test_escaped_char_filename(self):
        self.make_client('a', 'dc')
        self.build_tree({'dc/file with spaces': 'data'})
        tree = WorkingTree.open("dc")
        tree.add(["file with spaces"], ["fooid"])
        tree.commit("msg")
        self.assertEqual("fooid", tree.inventory.path2id("file with spaces"))


