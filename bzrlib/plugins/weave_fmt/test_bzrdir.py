# Copyright (C) 2006-2010 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Tests for the weave-era BzrDir formats.

For interface contract tests, see tests/per_bzr_dir.
"""

from bzrlib import (
    bzrdir,
    )

from bzrlib.tests import TestCaseWithTransport

from bzrlib.plugins.weave_fmt.bzrdir import (
    BzrDirFormat5,
    BzrDirFormat6,
    )


class TestFormat5(TestCaseWithTransport):
    """Tests specific to the version 5 bzrdir format."""

    def test_same_lockfiles_between_tree_repo_branch(self):
        # this checks that only a single lockfiles instance is created
        # for format 5 objects
        dir = BzrDirFormat5().initialize(self.get_url())
        def check_dir_components_use_same_lock(dir):
            ctrl_1 = dir.open_repository().control_files
            ctrl_2 = dir.open_branch().control_files
            ctrl_3 = dir.open_workingtree()._control_files
            self.assertTrue(ctrl_1 is ctrl_2)
            self.assertTrue(ctrl_2 is ctrl_3)
        check_dir_components_use_same_lock(dir)
        # and if we open it normally.
        dir = bzrdir.BzrDir.open(self.get_url())
        check_dir_components_use_same_lock(dir)

    def test_can_convert(self):
        # format 5 dirs are convertable
        dir = BzrDirFormat5().initialize(self.get_url())
        self.assertTrue(dir.can_convert_format())

    def test_needs_conversion(self):
        # format 5 dirs need a conversion if they are not the default,
        # and they aren't
        dir = BzrDirFormat5().initialize(self.get_url())
        # don't need to convert it to itself
        self.assertFalse(dir.needs_format_conversion(BzrDirFormat5()))
        # do need to convert it to the current default
        self.assertTrue(dir.needs_format_conversion(
            bzrdir.BzrDirFormat.get_default_format()))


class TestFormat6(TestCaseWithTransport):
    """Tests specific to the version 6 bzrdir format."""

    def test_same_lockfiles_between_tree_repo_branch(self):
        # this checks that only a single lockfiles instance is created
        # for format 6 objects
        dir = BzrDirFormat6().initialize(self.get_url())
        def check_dir_components_use_same_lock(dir):
            ctrl_1 = dir.open_repository().control_files
            ctrl_2 = dir.open_branch().control_files
            ctrl_3 = dir.open_workingtree()._control_files
            self.assertTrue(ctrl_1 is ctrl_2)
            self.assertTrue(ctrl_2 is ctrl_3)
        check_dir_components_use_same_lock(dir)
        # and if we open it normally.
        dir = bzrdir.BzrDir.open(self.get_url())
        check_dir_components_use_same_lock(dir)

    def test_can_convert(self):
        # format 6 dirs are convertable
        dir = BzrDirFormat6().initialize(self.get_url())
        self.assertTrue(dir.can_convert_format())

    def test_needs_conversion(self):
        # format 6 dirs need an conversion if they are not the default.
        dir = BzrDirFormat6().initialize(self.get_url())
        self.assertTrue(dir.needs_format_conversion(
            bzrdir.BzrDirFormat.get_default_format()))
