# Copyright (C) 2007 Jelmer Vernooij <jelmer@samba.org>

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

from bzrlib.bzrdir import BzrDir
from bzrlib.errors import NoRepositoryPresent
from bzrlib.tests import TestCase
from bzrlib.workingtree import WorkingTree

from tree import SvnBasisTree
from tests import TestCaseWithSubversionRepository

class TestBasisTree(TestCaseWithSubversionRepository):
    def test_executable(self):
        repos_url = self.make_client("d", "dc")
        self.build_tree({"dc/file": "x"})
        self.client_add("dc/file")
        self.client_set_prop("dc/file", "svn:executable", "*")
        self.client_commit("dc", "executable")
        tree = SvnBasisTree(WorkingTree.open("dc"))
        self.assertTrue(tree.inventory[tree.inventory.path2id("file")].executable)

    def test_executable_changed(self):
        repos_url = self.make_client("d", "dc")
        self.build_tree({"dc/file": "x"})
        self.client_add("dc/file")
        self.client_commit("dc", "executable")
        self.client_update("dc")
        self.client_set_prop("dc/file", "svn:executable", "*")
        tree = SvnBasisTree(WorkingTree.open("dc"))
        self.assertFalse(tree.inventory[tree.inventory.path2id("file")].executable)

    def test_symlink(self):
        repos_url = self.make_client("d", "dc")
        import os
        os.symlink("target", "dc/file")
        self.build_tree({"dc/file": "x"})
        self.client_add("dc/file")
        self.client_commit("dc", "symlink")
        self.client_update("dc")
        tree = SvnBasisTree(WorkingTree.open("dc"))
        self.assertEqual('symlink', 
                         tree.inventory[tree.inventory.path2id("file")].kind)
        self.assertEqual("target",
                         tree.inventory[tree.inventory.path2id("file")].symlink_target)

    def test_symlink_next(self):
        repos_url = self.make_client("d", "dc")
        import os
        os.symlink("target", "dc/file")
        self.build_tree({"dc/file": "x", "dc/bla": "p"})
        self.client_add("dc/file")
        self.client_add("dc/bla")
        self.client_commit("dc", "symlink")
        self.build_tree({"dc/bla": "pa"})
        self.client_commit("dc", "change")
        self.client_update("dc")
        tree = SvnBasisTree(WorkingTree.open("dc"))
        self.assertEqual('symlink', 
                         tree.inventory[tree.inventory.path2id("file")].kind)
        self.assertEqual("target",
                         tree.inventory[tree.inventory.path2id("file")].symlink_target)

    def test_executable_link(self):
        repos_url = self.make_client("d", "dc")
        import os
        os.symlink("target", "dc/file")
        self.build_tree({"dc/file": "x"})
        self.client_add("dc/file")
        self.client_set_prop("dc/file", "svn:executable", "*")
        self.client_commit("dc", "exe1")
        wt = WorkingTree.open("dc")
        tree = SvnBasisTree(wt)
        self.assertFalse(tree.inventory[tree.inventory.path2id("file")].executable)
        self.assertFalse(wt.inventory[wt.inventory.path2id("file")].executable)

