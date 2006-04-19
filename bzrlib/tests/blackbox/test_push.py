# Copyright (C) 2005 by Canonical Ltd
# -*- coding: utf-8 -*-

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


"""Black-box tests for bzr push.
"""

import os

from bzrlib.branch import Branch
from bzrlib.osutils import abspath
from bzrlib.tests.blackbox import ExternalBase
from bzrlib.uncommit import uncommit


class TestPush(ExternalBase):

    def test_push_remember(self):
        """Push changes from one branch to another and test push location."""
        transport = self.get_transport()
        tree_a = self.make_branch_and_tree('branch_a')
        branch_a = tree_a.branch
        self.build_tree(['branch_a/a'])
        tree_a.add('a')
        tree_a.commit('commit a')
        tree_b = branch_a.bzrdir.sprout('branch_b').open_workingtree()
        branch_b = tree_b.branch
        tree_c = branch_a.bzrdir.sprout('branch_c').open_workingtree()
        branch_c = tree_c.branch
        self.build_tree(['branch_a/b'])
        tree_a.add('b')
        tree_a.commit('commit b')
        self.build_tree(['branch_b/c'])
        tree_b.add('c')
        tree_b.commit('commit c')
        # initial push location must be empty
        self.assertEqual(None, branch_b.get_push_location())
        # test push for failure without push location set
        os.chdir('branch_a')
        out = self.runbzr('push', retcode=3)
        self.assertEquals(out,
                ('','bzr: ERROR: No push location known or specified.\n'))
        # test implicit --remember when no push location set, push fails
        out = self.runbzr('push ../branch_b', retcode=3)
        self.assertEquals(out,
                ('','bzr: ERROR: These branches have diverged.  '
                    'Try a merge then push with overwrite.\n'))
        self.assertEquals(abspath(branch_a.get_push_location()),
                          abspath(branch_b.bzrdir.root_transport.base))
        # test implicit --remember after resolving previous failure
        uncommit(branch=branch_b, tree=tree_b)
        transport.delete('branch_b/c')
        self.runbzr('push')
        self.assertEquals(abspath(branch_a.get_push_location()),
                          abspath(branch_b.bzrdir.root_transport.base))
        # test explicit --remember
        self.runbzr('push ../branch_c --remember')
        self.assertEquals(abspath(branch_a.get_push_location()),
                          abspath(branch_c.bzrdir.root_transport.base))
