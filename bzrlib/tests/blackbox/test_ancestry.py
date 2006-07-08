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
from bzrlib.branch import Branch


class TestAncestry(TestCaseWithTransport):

    def _build_branches(self):
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

    def _check_ancestry(self, location='', result=None):
        out = self.capture('ancestry ' + location)
        if result is None:
            result = "A1\nB1\nA2\nA3\n"
        self.assertEqualDiff(out, result)

    def test_ancestry(self):
        """Tests 'ancestry' command"""
        self._build_branches()
        os.chdir('A')
        self._check_ancestry()

    def test_ancestry_with_location(self):
        """Tests 'ancestry' command with a specified location."""
        self._build_branches()
        self._check_ancestry('A')

    def test_ancestry_with_repo_branch(self):
        """Tests 'ancestry' command with a location that is a
        repository branch."""
        self._build_branches()
        self.run_bzr('init-repo', 'repo')
        self.run_bzr('branch', 'A', 'repo/A')
        self._check_ancestry('repo/A')

    def test_ancestry_with_checkout(self):
        """Tests 'ancestry' command with a location that is a
        checkout of a repository branch."""
        self._build_branches()
        self.run_bzr('init-repo', 'repo')
        self.run_bzr('branch', 'A', 'repo/A')
        self.run_bzr('checkout', 'repo/A', 'A-checkout')
        self._check_ancestry('A-checkout')

    def test_ancestry_with_lightweight_checkout(self):
        """Tests 'ancestry' command with a location that is a
        lightweight checkout of a repository branch."""
        self._build_branches()
        self.run_bzr('init-repo', 'repo')
        self.run_bzr('branch', 'A', 'repo/A')
        self.run_bzr('checkout', '--lightweight', 'repo/A', 'A-checkout')
        self._check_ancestry('A-checkout')

    def test_ancestry_with_truncated_checkout(self):
        """Tests 'ancestry' command with a location that is a
        checkout of a repository branch with a shortened revision history."""
        self._build_branches()
        self.run_bzr('init-repo', 'repo')
        self.run_bzr('branch', 'A', 'repo/A')
        self.run_bzr('checkout', '-r', '2', 'repo/A', 'A-checkout')
        self._check_ancestry('A-checkout', "A1\nA2\n")

    def test_ancestry_with_truncated_lightweight_checkout(self):
        """Tests 'ancestry' command with a location that is a lightweight
        checkout of a repository branch with a shortened revision history."""
        self._build_branches()
        self.run_bzr('init-repo', 'repo')
        self.run_bzr('branch', 'A', 'repo/A')
        self.run_bzr('checkout', '-r', '2', '--lightweight',
                'repo/A', 'A-checkout')
        self._check_ancestry('A-checkout', "A1\nA2\n")
