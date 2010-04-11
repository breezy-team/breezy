# Copyright (C) 2010 Canonical Ltd
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

"""Tests for bzr directories that support colocated branches."""

import bzrlib.branch
from bzrlib import errors
from bzrlib.tests import (
    TestNotApplicable,
    )
from bzrlib.transport import (
    get_transport,
    )

from bzrlib.tests.per_bzrdir_colo import (
    TestCaseWithBzrDir,
    )


class TestColocatedBranchSupport(TestCaseWithBzrDir):

    def test_destroy_colocated_branch(self):
        branch = self.make_branch('branch')
        bzrdir = branch.bzrdir
        colo_branch = bzrdir.create_branch('colo')
        bzrdir.destroy_branch("colo")
        self.assertRaises(errors.NotBranchError, bzrdir.open_branch, 
                          "colo")

    def test_create_colo_branch(self):
        # a bzrdir can construct a branch and repository for itself.
        if not self.bzrdir_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            raise TestNotApplicable('Control dir format not supported')
        t = get_transport(self.get_url())
        made_control = self.bzrdir_format.initialize(t.base)
        made_repo = made_control.create_repository()
        made_branch = made_control.create_branch("colo")
        self.failUnless(isinstance(made_branch, bzrlib.branch.Branch))
        self.assertEqual(made_control, made_branch.bzrdir)
