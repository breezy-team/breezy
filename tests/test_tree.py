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
"""Basis and revision tree tests."""

from bzrlib.inventory import Inventory, TreeReference
from bzrlib.osutils import has_symlinks
from bzrlib.repository import Repository
from bzrlib.revision import NULL_REVISION
from bzrlib.tests import TestCase
from bzrlib.workingtree import WorkingTree

import errors
import os
from tree import (SvnBasisTree, parse_externals_description, 
                  inventory_add_external)
import sys
from tests import TestCaseWithSubversionRepository

class TestBasisTree(TestCaseWithSubversionRepository):
    def test_executable(self):
        self.make_client("d", "dc")
        self.build_tree({"dc/file": "x"})
        self.client_add("dc/file")
        self.client_set_prop("dc/file", "svn:executable", "*")
        self.client_commit("dc", "executable")
        tree = SvnBasisTree(self.open_checkout("dc"))
        self.assertTrue(tree.inventory[tree.inventory.path2id("file")].executable)

    def test_executable_changed(self):
        self.make_client("d", "dc")
        self.build_tree({"dc/file": "x"})
        self.client_add("dc/file")
        self.client_commit("dc", "executable")
        self.client_update("dc")
        self.client_set_prop("dc/file", "svn:executable", "*")
        tree = SvnBasisTree(self.open_checkout("dc"))
        self.assertFalse(tree.inventory[tree.inventory.path2id("file")].executable)

    def test_symlink(self):
        if not has_symlinks():
            return
        self.make_client("d", "dc")
        os.symlink("target", "dc/file")
        self.build_tree({"dc/file": "x"})
        self.client_add("dc/file")
        self.client_commit("dc", "symlink")
        self.client_update("dc")
        tree = SvnBasisTree(self.open_checkout("dc"))
        self.assertEqual('symlink', 
                         tree.inventory[tree.inventory.path2id("file")].kind)
        self.assertEqual("target",
                         tree.inventory[tree.inventory.path2id("file")].symlink_target)

    def test_symlink_next(self):
        if not has_symlinks():
            return
        self.make_client("d", "dc")
        os.symlink("target", "dc/file")
        self.build_tree({"dc/file": "x", "dc/bla": "p"})
        self.client_add("dc/file")
        self.client_add("dc/bla")
        self.client_commit("dc", "symlink")
        self.build_tree({"dc/bla": "pa"})
        self.client_commit("dc", "change")
        self.client_update("dc")
        tree = SvnBasisTree(self.open_checkout("dc"))
        self.assertEqual('symlink', 
                         tree.inventory[tree.inventory.path2id("file")].kind)
        self.assertEqual("target",
                         tree.inventory[tree.inventory.path2id("file")].symlink_target)

    def test_executable_link(self):
        if not has_symlinks():
            return
        self.make_client("d", "dc")
        os.symlink("target", "dc/file")
        self.build_tree({"dc/file": "x"})
        self.client_add("dc/file")
        self.client_set_prop("dc/file", "svn:executable", "*")
        self.client_commit("dc", "exe1")
        wt = self.open_checkout("dc")
        tree = SvnBasisTree(wt)
        self.assertFalse(tree.inventory[tree.inventory.path2id("file")].executable)
        self.assertFalse(wt.inventory[wt.inventory.path2id("file")].executable)


class TestExternalsParser(TestCase):
    def test_parse_externals(self):
        self.assertEqual({
            'third-party/sounds': (None, "http://sounds.red-bean.com/repos"),
            'third-party/skins': (None, "http://skins.red-bean.com/repositories/skinproj"),
            'third-party/skins/toolkit': (21, "http://svn.red-bean.com/repos/skin-maker")},
            parse_externals_description("http://example.com",
"""third-party/sounds             http://sounds.red-bean.com/repos
third-party/skins              http://skins.red-bean.com/repositories/skinproj
third-party/skins/toolkit -r21 http://svn.red-bean.com/repos/skin-maker"""))

    def test_parse_comment(self):
        self.assertEqual({
            'third-party/sounds': (None, "http://sounds.red-bean.com/repos")
                },
            parse_externals_description("http://example.com/",
"""

third-party/sounds             http://sounds.red-bean.com/repos
#third-party/skins              http://skins.red-bean.com/repositories/skinproj
#third-party/skins/toolkit -r21 http://svn.red-bean.com/repos/skin-maker"""))

    def test_parse_relative(self):
        self.assertEqual({
            'third-party/sounds': (None, "http://example.com/branches/other"),
                },
            parse_externals_description("http://example.com/trunk",
"third-party/sounds             ../branches/other"))

    def test_parse_invalid_missing_url(self):
        """No URL specified."""
        self.assertRaises(errors.InvalidExternalsDescription, 
            lambda: parse_externals_description("http://example.com/", "bla"))
            
    def test_parse_invalid_too_much_data(self):
        """No URL specified."""
        self.assertRaises(errors.InvalidExternalsDescription, 
            lambda: parse_externals_description(None, "bla -R40 http://bla/"))
 

class TestInventoryExternals(TestCaseWithSubversionRepository):
    def test_add_nested_norev(self):
        """Add a nested tree with no specific revision referenced."""
        repos_url = self.make_client('d', 'dc')
        repos = Repository.open(repos_url)
        mapping = repos.get_mapping()
        inv = Inventory(root_id='blabloe')
        inventory_add_external(inv, 'blabloe', 'blie/bla', 
                mapping.generate_revision_id(repos.uuid, 1, ""), 
                None, repos_url)
        self.assertEqual(TreeReference(
            mapping.generate_file_id(repos.uuid, 0, "", u""),
             'bla', inv.path2id('blie'), 
             revision=mapping.generate_revision_id(repos.uuid, 1, "")), 
             inv[inv.path2id('blie/bla')])

    def test_add_simple_norev(self):
        repos_url = self.make_client('d', 'dc')
        repos = Repository.open(repos_url)
        mapping = repos.get_mapping()
        inv = Inventory(root_id='blabloe')
        inventory_add_external(inv, 'blabloe', 'bla', 
            mapping.generate_revision_id(repos.uuid, 1, ""), None, 
            repos_url)

        self.assertEqual(TreeReference(
            mapping.generate_file_id(repos.uuid, 0, "", u""),
             'bla', 'blabloe', 
             revision=mapping.generate_revision_id(repos.uuid, 1, "")), 
             inv[inv.path2id('bla')])

    def test_add_simple_rev(self):
        repos_url = self.make_client('d', 'dc')
        repos = Repository.open(repos_url)
        inv = Inventory(root_id='blabloe')
        mapping = repos.get_mapping()
        inventory_add_external(inv, 'blabloe', 'bla', 
            mapping.generate_revision_id(repos.uuid, 1, ""), 0, repos_url)
        expected_ie = TreeReference(mapping.generate_file_id(repos.uuid, 0, "", u""),
            'bla', 'blabloe', 
            revision=mapping.generate_revision_id(repos.uuid, 1, ""),
            reference_revision=NULL_REVISION)
        ie = inv[inv.path2id('bla')]
        self.assertEqual(NULL_REVISION, ie.reference_revision)
        self.assertEqual(mapping.generate_revision_id(repos.uuid, 1, ""), 
                         ie.revision)
        self.assertEqual(expected_ie, inv[inv.path2id('bla')])
