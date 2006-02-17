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

"""Black-box tests for bzr sign-my-commits."""

import os

import bzrlib.gpg
from bzrlib.testament import Testament
from bzrlib.tests import TestCaseWithTransport
from bzrlib.workingtree import WorkingTree


class SignMyCommits(TestCaseWithTransport):

    def monkey_patch_gpg(self):
        """Monkey patch the gpg signing strategy to be a loopback.

        This also registers the cleanup, so that we will revert to
        the original gpg strategy when done.
        """
        self._oldstrategy = bzrlib.gpg.GPGStrategy

        # monkey patch gpg signing mechanism
        bzrlib.gpg.GPGStrategy = bzrlib.gpg.LoopbackGPGStrategy

        self.addCleanup(self._fix_gpg_strategy)

    def _fix_gpg_strategy(self):
        bzrlib.gpg.GPGStrategy = self._oldstrategy

    def setup_tree(self, location='.'):
        wt = self.make_branch_and_tree(location)
        wt.commit("base A", allow_pointless=True, rev_id='A')
        wt.commit("base B", allow_pointless=True, rev_id='B')
        wt.commit("base C", allow_pointless=True, rev_id='C')
        wt.commit("base D", allow_pointless=True, rev_id='D',
                committer='Alternate <alt@foo.com>')

        return wt

    def test_sign_my_commits(self):
        #Test re signing of data.
        wt = self.setup_tree()
        repo = wt.branch.repository

        self.monkey_patch_gpg()

        self.assertFalse(repo.revision_store.has_id('A', 'sig'))
        self.assertFalse(repo.revision_store.has_id('B', 'sig'))
        self.assertFalse(repo.revision_store.has_id('C', 'sig'))
        self.assertFalse(repo.revision_store.has_id('D', 'sig'))

        self.run_bzr('sign-my-commits')

        self.assertTrue(repo.revision_store.has_id('A', 'sig'))
        self.assertTrue(repo.revision_store.has_id('B', 'sig'))
        self.assertTrue(repo.revision_store.has_id('C', 'sig'))
        self.assertFalse(repo.revision_store.has_id('D', 'sig'))
            
    def test_sign_my_commits_location(self):
        wt = self.setup_tree('other')
        repo = wt.branch.repository

        self.monkey_patch_gpg()

        self.run_bzr('sign-my-commits', 'other')

        self.assertTrue(repo.revision_store.has_id('A', 'sig'))
        self.assertTrue(repo.revision_store.has_id('B', 'sig'))
        self.assertTrue(repo.revision_store.has_id('C', 'sig'))
        self.assertFalse(repo.revision_store.has_id('D', 'sig'))

    def test_sign_diff_committer(self):
        wt = self.setup_tree()
        repo = wt.branch.repository

        self.monkey_patch_gpg()

        self.run_bzr('sign-my-commits', '.', 'Alternate <alt@foo.com>')

        self.assertFalse(repo.revision_store.has_id('A', 'sig'))
        self.assertFalse(repo.revision_store.has_id('B', 'sig'))
        self.assertFalse(repo.revision_store.has_id('C', 'sig'))
        self.assertTrue(repo.revision_store.has_id('D', 'sig'))

    def test_sign_dry_run(self):
        wt = self.setup_tree()
        repo = wt.branch.repository

        self.monkey_patch_gpg()

        out = self.run_bzr('sign-my-commits', '--dry-run')[0]

        self.assertEquals('A\nB\nC\nSigned 3 revisions\n', out)
        self.assertFalse(repo.revision_store.has_id('A', 'sig'))
        self.assertFalse(repo.revision_store.has_id('B', 'sig'))
        self.assertFalse(repo.revision_store.has_id('C', 'sig'))
        self.assertFalse(repo.revision_store.has_id('D', 'sig'))

