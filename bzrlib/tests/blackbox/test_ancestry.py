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
from bzrlib.tests import TestCaseInTempDir
from bzrlib.branch import Branch
from bzrlib.builtins import merge

class TestAncestry(TestCaseInTempDir):

    def test_ancestry(self):
        """Tests 'ancestry' command"""
        os.mkdir('A')
        a = Branch.initialize('A')
        a_wt = a.working_tree()
        open('A/foo', 'wb').write('1111\n')
        a_wt.add('foo')
        a_wt.commit('added foo',rev_id='A1')
        a.clone('B')
        b = Branch.open('B')
        b_wt = b.working_tree()
        open('B/foo','wb').write('1111\n22\n')
        b_wt.commit('modified B/foo',rev_id='B1')
        open('A/foo', 'wb').write('000\n1111\n')
        a_wt.commit('modified A/foo',rev_id='A2')
        merge(['B',-1],['B',1],this_dir='A')
        a_wt.commit('merged B into A',rev_id='A3')
        self.run_bzr('ancestry')
