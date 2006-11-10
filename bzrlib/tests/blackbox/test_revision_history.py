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

import os
from bzrlib.tests import TestCaseWithTransport
from bzrlib.branch import Branch


class TestRevisionHistory(TestCaseWithTransport):

    def _build_branch(self):
        # setup a standalone branch with three commits
        tree = self.make_branch_and_tree('test')
        open('test/foo', 'wb').write('1111\n')
        tree.add('foo')
        tree.commit('added foo',rev_id='revision_1')
        open('test/foo', 'wb').write('2222\n')
        tree.commit('updated foo',rev_id='revision_2')
        open('test/foo', 'wb').write('3333\n')
        tree.commit('updated foo again',rev_id='revision_3')
        return tree

    def _check_revision_history(self, location=''):
        rh = self.capture('revision-history ' + location)
        self.assertEqual(rh, 'revision_1\nrevision_2\nrevision_3\n')

    def test_revision_history(self):
        """Tests 'revision_history' command"""
        self._build_branch()
        os.chdir('test')
        self._check_revision_history()

    def test_revision_history_with_location(self):
        """Tests 'revision_history' command with a specified location."""
        self._build_branch()
        self._check_revision_history('test')

    def test_revision_history_with_repo_branch(self):
        """Tests 'revision_history' command with a location that is a
        repository branch."""
        self._build_branch()
        self.run_bzr('init-repo', 'repo')
        self.run_bzr('branch', 'test', 'repo/test')
        self._check_revision_history('repo/test')

    def test_revision_history_with_checkout(self):
        """Tests 'revision_history' command with a location that is a
        checkout of a repository branch."""
        self._build_branch()
        self.run_bzr('init-repo', 'repo')
        self.run_bzr('branch', 'test', 'repo/test')
        self.run_bzr('checkout', 'repo/test', 'test-checkout')
        self._check_revision_history('test-checkout')

    def test_revision_history_with_lightweight_checkout(self):
        """Tests 'revision_history' command with a location that is a
        lightweight checkout of a repository branch."""
        self._build_branch()
        self.run_bzr('init-repo', 'repo')
        self.run_bzr('branch', 'test', 'repo/test')
        self.run_bzr('checkout', '--lightweight', 'repo/test', 'test-checkout')
        self._check_revision_history('test-checkout')
