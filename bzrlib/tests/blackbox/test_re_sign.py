# Copyright (C) 2005-2010 Canonical Ltd
# -*- coding: utf-8 -*-
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA


"""Black-box tests for bzr re-sign.
"""

from bzrlib import (
    gpg,
    tests,
    )
from bzrlib.controldir import ControlDir
from bzrlib.testament import Testament


class ReSign(tests.TestCaseInTempDir):

    def monkey_patch_gpg(self):
        """Monkey patch the gpg signing strategy to be a loopback.

        This also registers the cleanup, so that we will revert to
        the original gpg strategy when done.
        """
        # monkey patch gpg signing mechanism
        self.overrideAttr(gpg, 'GPGStrategy', gpg.LoopbackGPGStrategy)

    def setup_tree(self):
        wt = ControlDir.create_standalone_workingtree('.')
        wt.commit("base A", allow_pointless=True, rev_id='A')
        wt.commit("base B", allow_pointless=True, rev_id='B')
        wt.commit("base C", allow_pointless=True, rev_id='C')

        return wt

    def assertEqualSignature(self, repo, revision_id):
        """Assert a signature is stored correctly in repository."""
        self.assertEqual(
            '-----BEGIN PSEUDO-SIGNED CONTENT-----\n' +
            Testament.from_revision(repo, revision_id).as_short_text() +
            '-----END PSEUDO-SIGNED CONTENT-----\n',
            repo.get_signature_text(revision_id))

    def test_resign(self):
        #Test re signing of data.
        wt = self.setup_tree()
        repo = wt.branch.repository

        self.monkey_patch_gpg()
        self.run_bzr('re-sign -r revid:A')

        self.assertEqualSignature(repo, 'A')

        self.run_bzr('re-sign B')
        self.assertEqualSignature(repo, 'B')

    def test_resign_range(self):
        wt = self.setup_tree()
        repo = wt.branch.repository

        self.monkey_patch_gpg()
        self.run_bzr('re-sign -r 1..')
        self.assertEqualSignature(repo, 'A')
        self.assertEqualSignature(repo, 'B')
        self.assertEqualSignature(repo, 'C')

    def test_resign_multiple(self):
        wt = self.setup_tree()
        repo = wt.branch.repository

        self.monkey_patch_gpg()
        self.run_bzr('re-sign A B C')
        self.assertEqualSignature(repo, 'A')
        self.assertEqualSignature(repo, 'B')
        self.assertEqualSignature(repo, 'C')

    def test_resign_directory(self):
        """Test --directory option"""
        wt = ControlDir.create_standalone_workingtree('a')
        wt.commit("base A", allow_pointless=True, rev_id='A')
        wt.commit("base B", allow_pointless=True, rev_id='B')
        wt.commit("base C", allow_pointless=True, rev_id='C')
        repo = wt.branch.repository
        self.monkey_patch_gpg()
        self.run_bzr('re-sign --directory=a -r revid:A')
        self.assertEqualSignature(repo, 'A')
        self.run_bzr('re-sign -d a B')
        self.assertEqualSignature(repo, 'B')
