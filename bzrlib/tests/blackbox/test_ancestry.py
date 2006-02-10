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

import os

from bzrlib.builtins import merge
from bzrlib.tests import TestCaseWithTransport
from bzrlib.workingtree import WorkingTree


class TestAncestry(TestCaseWithTransport):

    def test_ancestry(self):
        """Tests 'ancestry' command"""
        a_wt = self.make_branch_and_tree('A')
        open('A/foo', 'wb').write('1111\n')
        a_wt.add('foo')
        a_wt.commit('added foo',rev_id='A1')
        self.run_bzr_captured(['branch', 'A', 'B'])
        b_wt = WorkingTree.open('B')
        open('B/foo','wb').write('1111\n22\n')
        b_wt.commit('modified B/foo',rev_id='B1')
        open('A/foo', 'wb').write('000\n1111\n')
        a_wt.commit('modified A/foo',rev_id='A2')
        merge(['B',-1],['B',1],this_dir='A')
        a_wt.commit('merged B into A',rev_id='A3')
        self.run_bzr('ancestry')
