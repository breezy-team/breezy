#    Copyright (C) 2011 Canonical Ltd
#    Copyright (C) 2019 Jelmer Vernooij <jelmer@jelmer.uk>
#
#    Breezy is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    Breezy is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with Breezy; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

"""Tests for the quilt code."""

import os

from ..wrapper import (
    quilt_delete,
    quilt_pop_all,
    quilt_applied,
    quilt_unapplied,
    quilt_push_all,
    quilt_series,
    )

from ....tests import TestCaseWithTransport
from ....tests.features import ExecutableFeature

quilt_feature = ExecutableFeature('quilt')

TRIVIAL_PATCH = """--- /dev/null	2012-01-02 01:09:10.986490031 +0100
+++ base/a	2012-01-02 20:03:59.710666215 +0100
@@ -0,0 +1 @@
+a
"""

class QuiltTests(TestCaseWithTransport):

    _test_needs_features = [quilt_feature]

    def make_empty_quilt_dir(self, path):
        source = self.make_branch_and_tree(path)
        self.build_tree(
            [os.path.join(path, n) for n in ['patches/']])
        self.build_tree_contents([
            (os.path.join(path, "patches/series"), "\n")])
        source.add(["patches", "patches/series"])
        return source

    def test_series_all_empty(self):
        source = self.make_empty_quilt_dir("source")
        self.assertEquals([], quilt_series(source, 'patches/series'))

    def test_series_all(self):
        source = self.make_empty_quilt_dir("source")
        self.build_tree_contents([
            ("source/patches/series", "patch1.diff\n"),
            ("source/patches/patch1.diff", TRIVIAL_PATCH)])
        source.smart_add(["source"])
        self.assertEquals(
            ["patch1.diff"], quilt_series(source, 'patches/series'))

    def test_push_all_empty(self):
        self.make_empty_quilt_dir("source")
        quilt_push_all("source", quiet=True)

    def test_pop_all_empty(self):
        self.make_empty_quilt_dir("source")
        quilt_pop_all("source", quiet=True)

    def test_applied_empty(self):
        source = self.make_empty_quilt_dir("source")
        self.build_tree_contents([
            ("source/patches/series", "patch1.diff\n"),
            ("source/patches/patch1.diff", "foob ar")])
        self.assertEquals([], quilt_applied(source))

    def test_unapplied(self):
        self.make_empty_quilt_dir("source")
        self.build_tree_contents([
            ("source/patches/series", "patch1.diff\n"),
            ("source/patches/patch1.diff", "foob ar")])
        self.assertEquals(["patch1.diff"], quilt_unapplied("source"))

    def test_unapplied_dir(self):
        self.make_empty_quilt_dir("source")
        self.build_tree_contents([
            ("source/patches/series", "debian/patch1.diff\n"),
            ("source/patches/debian/", ),
            ("source/patches/debian/patch1.diff", "foob ar")])
        self.assertEquals(["debian/patch1.diff"], quilt_unapplied("source"))

    def test_unapplied_multi(self):
        self.make_empty_quilt_dir("source")
        self.build_tree_contents([
            ("source/patches/series", "patch1.diff\npatch2.diff"),
            ("source/patches/patch1.diff", "foob ar"),
            ("source/patches/patch2.diff", "bazb ar")])
        self.assertEquals(["patch1.diff", "patch2.diff"],
                          quilt_unapplied("source", "patches"))

    def test_delete(self):
        source = self.make_empty_quilt_dir("source")
        self.build_tree_contents([
            ("source/patches/series", "patch1.diff\npatch2.diff"),
            ("source/patches/patch1.diff", "foob ar"),
            ("source/patches/patch2.diff", "bazb ar")])
        quilt_delete("source", "patch1.diff", "patches", remove=False)
        self.assertEqual(
            ['patch2.diff'],
            quilt_series(source, 'patches/series'))
        quilt_delete("source", "patch2.diff", "patches", remove=True)
        self.assertTrue(os.path.exists('source/patches/patch1.diff'))
        self.assertFalse(os.path.exists('source/patches/patch2.diff'))
        self.assertEqual([], quilt_series(source, 'patches/series'))
