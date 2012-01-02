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

from bzrlib.plugins.builddeb.tests import ExecutableFeature
from bzrlib.plugins.builddeb.merge_quilt import quilt_pop_all

from bzrlib.tests import TestCaseWithTransport

quilt_feature = ExecutableFeature('quilt')


class QuiltTests(TestCaseWithTransport):

    _test_needs_features = [quilt_feature]

    def test_push_all_empty(self):
        source = self.make_branch_and_tree('source')
        self.build_tree(['source/debian/', 'source/debian/patches/'])
        self.build_tree_contents([
            ("test.recipe", "# bzr-builder format 0.3 "
             "deb-version 1\nsource 3\n"),
            ("source/debian/patches/series", "\n")])
        source.add(["debian", "debian/patches", "debian/patches/series"])
        quilt_pop_all("source", quiet=True)
