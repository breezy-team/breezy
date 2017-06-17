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

from __future__ import absolute_import

import os
import shutil

from .... import (
    config,
    errors,
    trace,
    )
from ....merge import Merger
from ....mutabletree import MutableTree

from .. import (
    pre_merge_quilt,
    post_build_tree_quilt,
    post_merge_quilt_cleanup,
    start_commit_check_quilt,
    )
from ..quilt import quilt_push_all
from ..merge_quilt import tree_unapply_patches
from ..util import FORMAT_3_0_QUILT

from .test_quilt import quilt_feature

from ....tests import (
    TestCaseWithTransport,
    TestSkipped,
    )

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

    def test_unapply_nothing_applied(self):
        orig_tree = self.make_branch_and_tree('source')
        self.build_tree(["source/debian/", "source/debian/patches/"])
        self.build_tree_contents([
            ("source/debian/patches/series", "patch1.diff\n"),
            ("source/debian/patches/patch1.diff", TRIVIAL_PATCH)])
        orig_tree.smart_add([orig_tree.basedir])
        tree, target_dir = tree_unapply_patches(orig_tree)
        self.assertIs(tree, orig_tree)
        self.assertIs(None, target_dir)


class TestMergeHook(TestCaseWithTransport):

    _test_needs_features = [quilt_feature]

    def enable_hooks(self):
        try:
            Merger.hooks.install_named_hook(
                'pre_merge', pre_merge_quilt,
                'Debian quilt patch (un)applying and ancestry fixing')
        except errors.UnknownHook:
            raise TestSkipped("pre_merge hook not available")
        Merger.hooks.install_named_hook(
            'post_merge', post_merge_quilt_cleanup,
            'Cleaning up quilt temporary directories')
        MutableTree.hooks.install_named_hook(
            "post_build_tree", post_build_tree_quilt,
            "Apply quilt trees.")

    def test_diverged_patches(self):
        self.enable_hooks()

        tree_a = self.make_branch_and_tree('a')
        self.build_tree(['a/debian/', 'a/debian/patches/', 'a/debian/source/'])
        self.build_tree_contents([
            ('a/debian/source/format', FORMAT_3_0_QUILT),
            ('a/debian/patches/series', 'patch1\n'),
            ('a/debian/patches/patch1', TRIVIAL_PATCH)])
        tree_a.smart_add([tree_a.basedir])
        tree_a.commit('initial')

        tree_b = tree_a.controldir.sprout('b').open_workingtree()
        self.build_tree_contents([
            ('a/debian/patches/patch1', 
                "\n".join(TRIVIAL_PATCH.splitlines()[:-1] + ["+d\n"]))])
        quilt_push_all(tree_a.basedir)
        tree_a.smart_add([tree_a.basedir])
        tree_a.commit('apply patches')
        self.build_tree_contents([
            ('b/debian/patches/patch1', 
                "\n".join(TRIVIAL_PATCH.splitlines()[:-1] + ["+c\n"]))])
        quilt_push_all(tree_b.basedir)
        tree_b.commit('apply patches')
        conflicts = tree_a.merge_from_branch(tree_b.branch)
        self.assertFileEqual("""\
--- /dev/null\t2012-01-02 01:09:10.986490031 +0100
+++ base/a\t2012-01-02 20:03:59.710666215 +0100
@@ -0,0 +1 @@
<<<<<<< TREE
+d
=======
+c
>>>>>>> MERGE-SOURCE
""", "a/debian/patches/patch1")
        # "a" should be unapplied again
        self.assertPathDoesNotExist("a/a")
        self.assertEquals(1, conflicts)

    def test_auto_apply_patches_after_checkout(self):
        self.enable_hooks()

        tree_a = self.make_branch_and_tree('a')

        self.build_tree(['a/debian/', 'a/debian/patches/'])
        self.build_tree_contents([
            ('a/debian/patches/series', 'patch1\n'),
            ('a/debian/patches/patch1', TRIVIAL_PATCH)])
        tree_a.smart_add([tree_a.basedir])
        tree_a.commit('initial')

        config.ensure_config_dir_exists()
        self.build_tree_contents([
            (os.path.join(config.config_dir(), "builddeb.conf"),
                "[BUILDDEB]\nquilt-tree-policy = applied\n")])

        tree_b = tree_a.branch.create_checkout("b")
        self.assertFileEqual("a\n", "b/a")

    def test_auto_apply_patches_after_update_format_1(self):
        self.enable_hooks()

        tree_a = self.make_branch_and_tree('a')
        tree_b = tree_a.branch.create_checkout("b")

        self.build_tree(['a/debian/', 'a/debian/patches/'])
        self.build_tree_contents([
            ('a/debian/patches/series', 'patch1\n'),
            ('a/debian/patches/patch1', TRIVIAL_PATCH)])
        tree_a.smart_add([tree_a.basedir])
        tree_a.commit('initial')

        self.build_tree(["b/.bzr-builddeb/", "b/debian/", "b/debian/source/"])
        self.build_tree_contents([
            ("b/.bzr-builddeb/local.conf", "[BUILDDEB]\nquilt-tree-policy = applied\n"),
            ("b/debian/source/format", "1.0")])

        tree_b.update()
        self.assertPathDoesNotExist("b/a")

    def test_auto_apply_patches_after_update(self):
        self.enable_hooks()

        tree_a = self.make_branch_and_tree('a')
        tree_b = tree_a.branch.create_checkout("b")

        self.build_tree(['a/debian/', 'a/debian/patches/', 'a/debian/source/'])
        self.build_tree_contents([
            ('a/debian/source/format', FORMAT_3_0_QUILT),
            ('a/debian/patches/series', 'patch1\n'),
            ('a/debian/patches/patch1', TRIVIAL_PATCH)])
        tree_a.smart_add([tree_a.basedir])
        tree_a.commit('initial')

        self.build_tree(["b/.bzr-builddeb/", "b/debian/", "b/debian/source/"])
        self.build_tree_contents([
            ("b/.bzr-builddeb/local.conf", "[BUILDDEB]\nquilt-tree-policy = applied\n"),
            ('b/debian/source/format', FORMAT_3_0_QUILT),
            ])

        tree_b.update()
        self.assertFileEqual("a\n", "b/a")

    def test_auto_unapply_patches_after_update(self):
        self.enable_hooks()

        tree_a = self.make_branch_and_tree('a')
        tree_b = tree_a.branch.create_checkout("b")

        self.build_tree(['a/debian/', 'a/debian/patches/', 'a/debian/source/'])
        self.build_tree_contents([
            ('a/debian/source/format', FORMAT_3_0_QUILT),
            ('a/debian/patches/series', 'patch1\n'),
            ('a/debian/patches/patch1', TRIVIAL_PATCH)])
        tree_a.smart_add([tree_a.basedir])
        tree_a.commit('initial')

        self.build_tree(["b/.bzr-builddeb/"])
        self.build_tree_contents([("b/.bzr-builddeb/local.conf", "[BUILDDEB]\nquilt-tree-policy = unapplied\n")])

        tree_b.update()
        self.assertPathDoesNotExist("b/a")

    def test_disabled_hook(self):
        self.enable_hooks()

        tree_a = self.make_branch_and_tree('a')
        self.build_tree(['a/debian/', 'a/debian/patches/'])
        self.build_tree_contents([
            ('a/debian/patches/series', 'patch1\n'),
            ('a/debian/patches/patch1', TRIVIAL_PATCH),
            ("a/debian/bzr-builddeb.conf", "[BUILDDEB]\n"
                "quilt-smart-merge = False\n"),
            ("a/a", "")])
        tree_a.smart_add([tree_a.basedir])
        tree_a.commit('initial')

        tree_b = tree_a.controldir.sprout('b').open_workingtree()
        self.build_tree_contents([
            ('a/debian/patches/patch1', 
                "\n".join(TRIVIAL_PATCH.splitlines()[:-1] + ["+d\n"]))])
        quilt_push_all(tree_a.basedir)
        tree_a.smart_add([tree_a.basedir])
        tree_a.commit('apply patches')
        self.assertFileEqual("d\n", "a/a")
        self.build_tree_contents([
            ('b/debian/patches/patch1', 
                "\n".join(TRIVIAL_PATCH.splitlines()[:-1] + ["+c\n"]))])
        quilt_push_all(tree_b.basedir)
        tree_b.commit('apply patches')
        self.assertFileEqual("c\n", "b/a")
        conflicts = tree_a.merge_from_branch(tree_b.branch)
        self.assertFileEqual("""\
--- /dev/null\t2012-01-02 01:09:10.986490031 +0100
+++ base/a\t2012-01-02 20:03:59.710666215 +0100
@@ -0,0 +1 @@
<<<<<<< TREE
+d
=======
+c
>>>>>>> MERGE-SOURCE
""", "a/debian/patches/patch1")
        self.assertFileEqual("""\
<<<<<<< TREE
d
=======
c
>>>>>>> MERGE-SOURCE
""", "a/a")
        self.assertEquals(2, conflicts)



class StartCommitMergeHookTests(TestCaseWithTransport):

    def enable_hooks(self):
        MutableTree.hooks.install_named_hook(
            'start_commit', start_commit_check_quilt,
            'Check for (un)applied quilt patches')

    def test_applied(self):
        self.enable_hooks()
        tree = self.make_branch_and_tree('source')
        self.build_tree(['source/debian/', 'source/debian/patches/',
            'source/debian/source/'])
        self.build_tree_contents([
            ('source/debian/source/format', FORMAT_3_0_QUILT),
            ('source/debian/patches/series', 'patch1\n'),
            ('source/debian/patches/patch1', TRIVIAL_PATCH),
            ('source/debian/bzr-builddeb.conf',
                "[BUILDDEB]\n"
                "quilt-commit-policy = applied\n")])
        self.assertPathDoesNotExist("source/.pc/applied-patches")
        self.assertPathDoesNotExist("source/a")
        tree.smart_add([tree.basedir])
        tree.commit("foo")
        self.assertPathExists("source/.pc/applied-patches")
        self.assertPathExists("source/a")

    def test_unapplied(self):
        self.enable_hooks()
        tree = self.make_branch_and_tree('source')
        self.build_tree(['source/debian/', 'source/debian/patches/',
            'source/debian/source/'])
        self.build_tree_contents([
            ('source/debian/patches/series', 'patch1\n'),
            ('source/debian/patches/patch1', TRIVIAL_PATCH),
            ('source/debian/source/format', FORMAT_3_0_QUILT),
            ('source/debian/bzr-builddeb.conf',
                "[BUILDDEB]\n"
                "quilt-commit-policy = unapplied\n")])
        quilt_push_all(tree.basedir)
        self.assertPathExists("source/.pc/applied-patches")
        self.assertPathExists("source/a")
        tree.smart_add([tree.basedir])
        tree.commit("foo")
        self.assertPathDoesNotExist("source/.pc/applied-patches")
        self.assertPathDoesNotExist("source/a")

    def test_warning(self):
        self.enable_hooks()
        warnings = []
        def warning(*args):
            if len(args) > 1:
                warnings.append(args[0] % args[1:])
            else:
                warnings.append(args[0])
        _warning = trace.warning
        trace.warning = warning
        self.addCleanup(setattr, trace, "warning", _warning)
        tree = self.make_branch_and_tree('source')
        self.build_tree(['source/debian/', 'source/debian/patches/', 'source/debian/source/'])
        self.build_tree_contents([
            ('source/debian/patches/series', 'patch1\n'),
            ('source/debian/patches/patch1', TRIVIAL_PATCH)])
        quilt_push_all(tree.basedir)
        tree.smart_add([tree.basedir])
        tree.commit("initial")
        self.assertEquals([], warnings)
        self.assertPathExists("source/.pc/applied-patches")
        self.assertPathExists("source/a")
        self.build_tree_contents([
            ('source/debian/source/format', FORMAT_3_0_QUILT),
            ('source/debian/patches/series', 'patch1\npatch2\n'),
            ('source/debian/patches/patch2',
                """--- /dev/null	2012-01-02 01:09:10.986490031 +0100
+++ base/b	2012-01-02 20:03:59.710666215 +0100
@@ -0,0 +1 @@
+a
""")])
        tree.smart_add([tree.basedir])
        tree.commit("foo")
        self.assertEquals(['Committing with 1 patches applied and 1 patches unapplied.'], warnings)
        self.assertPathExists("source/.pc/applied-patches")
        self.assertPathExists("source/a")
        self.assertPathDoesNotExist("source/b")
