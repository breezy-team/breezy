# Copyright (C) 2008 Canonical Ltd
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

"""Tests that an enabled view is reported and impacts expected commands."""

from bzrlib import bzrdir
from bzrlib.tests import TestCaseWithTransport
from bzrlib.workingtree import WorkingTree


class TestViewOps(TestCaseWithTransport):

    def make_abc_tree_with_ab_view(self):
        # we need to use a specific format because the default format
        # doesn't support views yet
        format = bzrdir.format_registry.make_bzrdir('1.7preview')
        wt = TestCaseWithTransport.make_branch_and_tree(self, '.',
            format=format)
        self.build_tree(['a', 'b', 'c'])
        wt.views.set_view(['a', 'b'])
        return wt

    def test_view_on_status(self):
        wt = self.make_abc_tree_with_ab_view()
        out, err = self.run_bzr('status')
        self.assertEquals('ignoring files outside view: a, b', out[0])
