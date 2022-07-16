# Copyright (C) 2010, 2011, 2012, 2016 Canonical Ltd
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

"""Tests for bazaar control directories that do not support colocated branches.

Colocated branch support is optional, and when it is not supported the methods
and attributes colocated branch support added should fail in known ways.
"""

from breezy import (
    controldir,
    errors,
    tests,
    )
from breezy.tests import (
    per_controldir,
    )


class TestNoColocatedSupport(per_controldir.TestCaseWithControlDir):

    def make_controldir_with_repo(self):
        # a bzrdir can construct a branch and repository for itself.
        if not self.bzrdir_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            raise tests.TestNotApplicable('Control dir format not supported')
        t = self.get_transport()
        try:
            made_control = self.make_controldir('.', format=self.bzrdir_format)
        except errors.UninitializableFormat:
            raise tests.TestNotApplicable(
                'Control dir format not initializable')
        self.assertEqual(made_control._format, self.bzrdir_format)
        made_repo = made_control.create_repository()
        return made_control

    def test_destroy_colocated_branch(self):
        branch = self.make_branch('branch')
        # Colocated branches should not be supported *or*
        # destroy_branch should not be supported at all
        self.assertRaises(
            (controldir.NoColocatedBranchSupport, errors.UnsupportedOperation),
            branch.controldir.destroy_branch, 'colo')

    def test_create_colo_branch(self):
        made_control = self.make_controldir_with_repo()
        self.assertRaises(controldir.NoColocatedBranchSupport,
                          made_control.create_branch, "colo")

    def test_open_branch(self):
        made_control = self.make_controldir_with_repo()
        self.assertRaises(controldir.NoColocatedBranchSupport,
                          made_control.open_branch, name="colo")

    def test_get_branch_reference(self):
        made_control = self.make_controldir_with_repo()
        self.assertRaises(controldir.NoColocatedBranchSupport,
                          made_control.get_branch_reference, "colo")

    def test_set_branch_reference(self):
        referenced = self.make_branch('referenced')
        made_control = self.make_controldir_with_repo()
        self.assertRaises(controldir.NoColocatedBranchSupport,
                          made_control.set_branch_reference, referenced, name="colo")

    def test_get_branches(self):
        made_control = self.make_controldir_with_repo()
        made_control.create_branch()
        self.assertEqual(list(made_control.get_branches()), [""])
