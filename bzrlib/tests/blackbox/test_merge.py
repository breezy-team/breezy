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


"""Black-box tests for bzr merge.
"""

import os

from bzrlib.branch import Branch
from bzrlib.tests.blackbox import ExternalBase
from bzrlib.osutils import abspath


class TestMerge(ExternalBase):

    def test_merge_remember(self):
        """Merge changes from one branch to another and test parent location."""
        tree_a = self.make_branch_and_tree('branch_a')
        branch_a = tree_a.branch
        self.build_tree(['branch_a/a'])
        tree_a.add('a')
        tree_a.commit('commit a')
        branch_b = branch_a.bzrdir.sprout('branch_b').open_branch()
        tree_b = branch_b.bzrdir.open_workingtree()
        branch_c = branch_a.bzrdir.sprout('branch_c').open_branch()
        tree_c = branch_c.bzrdir.open_workingtree()
        self.build_tree(['branch_a/b'])
        tree_a.add('b')
        tree_a.commit('commit b')
        self.build_tree(['branch_c/c'])
        tree_c.add('c')
        tree_c.commit('commit c')
        # reset parent
        parent = branch_b.get_parent()
        branch_b.set_parent(None)
        self.assertEqual(None, branch_b.get_parent())
        # test merge for failure without parent set
        os.chdir('branch_b')
        out = self.runbzr('merge', retcode=3)
        self.assertEquals(out,
                ('','bzr: ERROR: No merge branch known or specified.\n'))
        # test implicit --remember when no parent set, this merge conflicts
        self.build_tree(['d'])
        tree_b.add('d')
        out = self.runbzr('merge ../branch_a', retcode=3)
        self.assertEquals(out,
                ('','bzr: ERROR: Working tree has uncommitted changes.\n'))
        self.assertEquals(abspath(branch_b.get_parent()), abspath(parent))
        # test implicit --remember after resolving conflict
        tree_b.commit('commit d')
        out, err = self.runbzr('merge')
        self.assertEquals(out, 'Using saved branch: ../branch_a\n')
        self.assertEquals(err, 'All changes applied successfully.\n')
        self.assertEquals(abspath(branch_b.get_parent()), abspath(parent))
        # re-open tree as external runbzr modified it
        tree_b = branch_b.bzrdir.open_workingtree()
        tree_b.commit('merge branch_a')
        # test explicit --remember
        out, err = self.runbzr('merge ../branch_c --remember')
        self.assertEquals(out, '')
        self.assertEquals(err, 'All changes applied successfully.\n')
        self.assertEquals(abspath(branch_b.get_parent()),
                          abspath(branch_c.bzrdir.root_transport.base))
        # re-open tree as external runbzr modified it
        tree_b = branch_b.bzrdir.open_workingtree()
        tree_b.commit('merge branch_c')
