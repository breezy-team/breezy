#    Copyright (C) 2011 Canonical Ltd
#
#    This file is part of bzr-builddeb.
#
#    bzr-builddeb is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    bzr-builddeb is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with bzr-builddeb; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

"""Tests for the merge_quilt code."""

import shutil

from bzrlib.plugins.builddeb.quilt import quilt_push_all
from bzrlib.plugins.builddeb.merge_quilt import tree_unapply_patches

from bzrlib.plugins.builddeb.tests.test_quilt import quilt_feature

from bzrlib.tests import TestCaseWithTransport

TRIVIAL_PATCH = """--- /dev/null	2012-01-02 01:09:10.986490031 +0100
+++ base/a	2012-01-02 20:03:59.710666215 +0100
@@ -0,0 +1 @@
+a
"""

class TestTreeUnapplyPatches(TestCaseWithTransport):

    _test_needs_features = [quilt_feature]

    def test_no_patches(self):
        tree = self.make_branch_and_tree('.')
        new_tree, target_dir = tree_unapply_patches(tree)
        self.assertIs(tree, new_tree)
        self.assertIs(None, target_dir)

    def test_unapply(self):
        orig_tree = self.make_branch_and_tree('source')
        self.build_tree(["source/debian/", "source/debian/patches/"])
        self.build_tree_contents([
            ("source/debian/patches/series", "patch1.diff\n"),
            ("source/debian/patches/patch1.diff", TRIVIAL_PATCH)])
        quilt_push_all(orig_tree.basedir)
        orig_tree.smart_add([orig_tree.basedir])
        tree, target_dir = tree_unapply_patches(orig_tree)
        self.addCleanup(shutil.rmtree, target_dir)
        self.assertPathExists("source/a")
        self.assertNotEqual(tree.basedir, orig_tree.basedir)
        self.assertPathDoesNotExist(tree.abspath("a"))
        self.assertPathExists(tree.abspath("debian/patches/series"))
