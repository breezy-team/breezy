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


"""Black-box tests for bzr re-sign.
"""

import os

import bzrlib.gpg
from bzrlib.bzrdir import BzrDir
from bzrlib.testament import Testament
from bzrlib.tests import TestCaseInTempDir


class ReSign(TestCaseInTempDir):

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

    def setup_tree(self):
        wt = BzrDir.create_standalone_workingtree('.')
        wt.commit("base A", allow_pointless=True, rev_id='A')
        wt.commit("base B", allow_pointless=True, rev_id='B')
        wt.commit("base C", allow_pointless=True, rev_id='C')

        return wt

    def test_resign(self):
        #Test re signing of data.
        wt = self.setup_tree()
        repo = wt.branch.repository

        self.monkey_patch_gpg()
        self.run_bzr('re-sign', '-r', 'revid:A')

        self.assertEqual(
            Testament.from_revision(repo, 'A').as_short_text(),
            repo.revision_store.get('A', 'sig').read())

        self.run_bzr('re-sign', 'B')
        self.assertEqual(
            Testament.from_revision(repo, 'B').as_short_text(),
            repo.revision_store.get('B', 'sig').read())
            
    def test_resign_range(self):
        wt = self.setup_tree()
        repo = wt.branch.repository

        self.monkey_patch_gpg()
        self.run_bzr('re-sign', '-r', '1..')
        self.assertEqual(
            Testament.from_revision(repo, 'A').as_short_text(),
            repo.revision_store.get('A', 'sig').read())
        self.assertEqual(
            Testament.from_revision(repo, 'B').as_short_text(),
            repo.revision_store.get('B', 'sig').read())
        self.assertEqual(
            Testament.from_revision(repo, 'C').as_short_text(),
            repo.revision_store.get('C', 'sig').read())

    def test_resign_multiple(self):
        wt = self.setup_tree()
        repo = wt.branch.repository

        self.monkey_patch_gpg()
        self.run_bzr('re-sign', 'A', 'B', 'C')
        self.assertEqual(
            Testament.from_revision(repo, 'A').as_short_text(),
            repo.revision_store.get('A', 'sig').read())
        self.assertEqual(
            Testament.from_revision(repo, 'B').as_short_text(),
            repo.revision_store.get('B', 'sig').read())
        self.assertEqual(
            Testament.from_revision(repo, 'C').as_short_text(),
            repo.revision_store.get('C', 'sig').read())


