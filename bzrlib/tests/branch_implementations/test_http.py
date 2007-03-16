# Copyright (C) 2006 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Test branch responses when accessed over http"""

import os

from bzrlib import branch, errors
from bzrlib.tests.branch_implementations.test_branch import TestCaseWithBranch
from bzrlib.tests.HttpServer import HttpServer


class HTTPBranchTests(TestCaseWithBranch):
    """Tests that use an HTTP server against each branch implementation"""

    def setUp(self):
        super(HTTPBranchTests, self).setUp()
        self.transport_readonly_server = HttpServer

    def get_parent_and_child(self):
        os.makedirs('parent/path/to')
        wt_a = self.make_branch_and_tree('parent/path/to/a')
        self.build_tree(['parent/path/to/a/one'])
        wt_a.add(['one'])
        wt_a.commit('commit one', rev_id='1')

        os.makedirs('child/path/to')
        branch_b = wt_a.bzrdir.sprout('child/path/to/b', revision_id='1').open_branch()
        self.assertEqual(wt_a.branch.base, branch_b.get_parent())

        return wt_a.branch, branch_b

    def test_get_parent_invalid(self):
        self.get_parent_and_child()

        # Now change directory, and access the child through http
        os.chdir('child/path/to')
        branch_b = branch.Branch.open(self.get_readonly_url('b'))
        self.assertRaises(errors.InaccessibleParent, branch_b.get_parent)

    def test_clone_invalid_parent(self):
        self.get_parent_and_child()

        # Now change directory, and access the child through http
        os.chdir('child/path/to')
        branch_b = branch.Branch.open(self.get_readonly_url('b'))

        branch_c = branch_b.bzrdir.clone('c').open_branch()
        self.assertEqual(None, branch_c.get_parent())

    def test_sprout_invalid_parent(self):
        self.get_parent_and_child()

        # Now change directory, and access the child through http
        os.chdir('child/path/to')
        branch_b = branch.Branch.open(self.get_readonly_url('b'))

        branch_c = branch_b.bzrdir.sprout('c').open_branch()
        self.assertEqual(branch_b.base, branch_c.get_parent())
