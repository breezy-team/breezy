#    test_tree_patcher.py -- Tests for the TreePatcher.
#    Copyright (C) 2008 Canonical Limited.
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

import os

from bzrlib.tests import TestCaseWithTransport

from bzrlib.plugins.builddeb.tree_patcher import TreePatcher


def write_to_file(filename, contents):
  f = open(filename, 'wb')
  try:
    f.write(contents)
  finally:
    f.close()


class TreePatcherTests(TestCaseWithTransport):

    def assertContentsAre(self, filename, expected_contents):
        f = open(filename)
        try:
          contents = f.read()
        finally:
          f.close()
        self.assertEqual(contents, expected_contents,
                         "Contents of %s are not as expected" % filename)

    def make_simple_patch_base(self):
        basedir = "base"
        os.mkdir(basedir)
        write_to_file(os.path.join(basedir, "a"), "a\na\na\n")
        write_to_file(os.path.join(basedir, "b"), "b\nb\nb\n")
        write_to_file(os.path.join(basedir, "c"), "c\nc\nc\n")
        write_to_file(os.path.join(basedir, "d"), "d\nd\nd\n")
        write_to_file(os.path.join(basedir, "e"), "")
        write_to_file(os.path.join(basedir, ".bzr"), "a\na\na\n")

    def test__patch_tree(self):
        tree = self.make_simple_patch_base()
        tp = TreePatcher(tree)
        tp._patch_tree(simple_test_patch, "base")
        self.failIfExists("base/a")
        self.assertContentsAre("base/b", "")
        self.assertContentsAre("base/c", "c\n")
        self.assertContentsAre("base/d", "d\nd\nd\nd\n")
        self.assertContentsAre("base/e", "e\ne\ne\n")
        self.assertContentsAre("base/f", "f\nf\nf\n")
        # .bzr and .git shouldn't be changed
        self.assertContentsAre("base/.bzr", "a\na\na\n")
        self.failIfExists("base/.git")

    def test__get_touched_paths(self):
        tree = self.make_simple_patch_base()
        tp = TreePatcher(tree)
        touched_paths = tp._get_touched_paths(simple_test_patch)
        self.assertEqual(touched_paths, ["a", "b", "c", "d", "e", "f"])

    def test__update_path_info(self):
        tree = self.make_branch_and_tree(".")
        os.mkdir("base")
        write_to_file("a", "")
        write_to_file("base/a", "")
        tree.add(["a", "base", "base/a"], ["a-1", "base-1", "base-a-1"])
        revid1 = tree.commit("one")
        write_to_file("b", "")
        write_to_file("base/b", "")
        tree.remove(["base/a"])
        tree.add(["b", "base/b"], ["b-2", "base-b-2"])
        revid2 = tree.commit("two")
        os.unlink("base/b")
        os.mkdir("base2")
        write_to_file("base2/c", "")
        write_to_file("base/a", "")
        tp = TreePatcher(tree)
        tp._update_path_info(["base/b", "base2/c", "base/a", "b"],
                [revid2, revid1])
        self.assertNotEqual(tree.path2id("base2"), None)
        self.assertNotEqual(tree.path2id("base2/c"), None)
        self.assertEqual(tree.path2id("base/a"), "base-a-1")
        self.assertEqual(tree.path2id("base/b"), None)
        self.assertEqual(tree.path2id("a"), "a-1")
        self.assertEqual(tree.path2id("b"), "b-2")

    def test_patch_tree(self):
        self.make_simple_patch_base()
        os.unlink("base/.bzr")
        tree = self.make_branch_and_tree('base')
        tp = TreePatcher(tree)
        tp.set_patch(simple_test_patch)
        tp.patch_tree([])

simple_test_patch_without_bzr = """diff -Nru base.old/a base/a
--- base.old/a  2008-05-14 19:53:53.000000000 +0100
+++ base/a  1970-01-01 01:00:00.000000000 +0100
@@ -1,3 +0,0 @@
-a
-a
-a
diff -Nru base.old/b base/b
--- base.old/b  2008-05-14 19:53:53.000000000 +0100
+++ base/b  2008-05-14 19:54:33.000000000 +0100
@@ -1,3 +0,0 @@
-b
-b
-b
diff -Nru base.old/c base/c
--- base.old/c  2008-05-14 19:53:53.000000000 +0100
+++ base/c  2008-05-14 19:54:42.000000000 +0100
@@ -1,3 +1,1 @@
 c
-c
-c
diff -Nru base.old/d base/d
--- base.old/d  2008-05-14 19:53:53.000000000 +0100
+++ base/d  2008-05-14 19:54:50.000000000 +0100
@@ -1,3 +1,4 @@
 d
 d
 d
+d
diff -Nru base.old/e base/e
--- base.old/e  2008-05-14 19:53:53.000000000 +0100
+++ base/e  2008-05-14 19:54:59.000000000 +0100
@@ -0,0 +1,3 @@
+e
+e
+e
diff -Nru base.old/f base/f
--- base.old/f  1970-01-01 01:00:00.000000000 +0100
+++ base/f  2008-05-14 19:55:06.000000000 +0100
@@ -0,0 +1,3 @@
+f
+f
+f
diff -Nru base.old/.git base/.git
--- base.old/.git   1970-01-01 01:00:00.000000000 +0100
+++ base/.git   2008-05-14 19:55:36.000000000 +0100
@@ -0,0 +1,3 @@
+a
+a
+a
"""

simple_test_patch = simple_test_patch_without_bzr + \
"""diff -Nru base.old/.bzr base/.bzr
--- base.old/.bzr   2008-05-14 19:53:53.000000000 +0100
+++ base/.bzr   2008-05-14 19:55:29.000000000 +0100
@@ -1,3 +1,4 @@
 a
 a
 a
+a
"""

