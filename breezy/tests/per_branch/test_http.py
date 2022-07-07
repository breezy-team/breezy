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

"""Test branches with inaccessible parents."""

from breezy import (
    branch,
    errors,
    )
from breezy.tests import (
    per_branch,
    test_server,
    )


class InaccessibleParentTests(per_branch.TestCaseWithBranch):
    """Tests with branches with "inaccessible" parents.

    An "inaccessible" parent location is one that cannot be represented, e.g. if
    a child branch says its parent is at "../../my-parent", but that child is at
    "http://host/one" then that parent location is inaccessible.  These
    branches' get_parent method will raise InaccessibleParent.
    """

    def setUp(self):
        super(InaccessibleParentTests, self).setUp()
        if self.transport_server in (test_server.LocalURLServer, None):
            self.transport_readonly_server = test_server.TestingChrootServer

    def get_branch_with_invalid_parent(self):
        """Get a branch whose get_parent will raise InaccessibleParent."""
        self.build_tree(
            ['parent/', 'parent/path/', 'parent/path/to/',
             'child/', 'child/path/', 'child/path/to/'],
            transport=self.get_transport())
        self.make_branch(
            'parent/path/to/a').controldir.sprout(self.get_url('child/path/to/b'))

        # The child branch internally will have recorded that its parent is at
        # "../../../../parent/path/to/a" or similar.  So we move the child
        # branch up several directories, so that its parent path will point to
        # somewhere outside the directory served by the HTTP server.  Thus its
        # parent is now inaccessible.
        self.get_transport().rename('child/path/to/b', 'b')
        branch_b = branch.Branch.open(self.get_readonly_url('b'))
        return branch_b

    def test_get_parent_invalid(self):
        # When you have a branch whose parent URL cannot be calculated, this
        # exception will be raised.
        branch_b = self.get_branch_with_invalid_parent()
        self.assertRaises(errors.InaccessibleParent, branch_b.get_parent)

    def test_clone_invalid_parent(self):
        # If clone can't determine the location of the parent of the branch
        # being cloned, then the new branch will have no parent set.
        branch_b = self.get_branch_with_invalid_parent()
        branch_c = branch_b.controldir.clone('c').open_branch()
        self.assertEqual(None, branch_c.get_parent())

    def test_sprout_invalid_parent(self):
        # A sprouted branch will have a parent of the branch it was sprouted
        # from, even if that branch has an invalid parent.
        branch_b = self.get_branch_with_invalid_parent()
        branch_c = branch_b.controldir.sprout('c').open_branch()
        self.assertEqual(branch_b.base, branch_c.get_parent())
