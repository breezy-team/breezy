# Copyright (C) 2013, 2016 Canonical Ltd
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

"""Black-box tests for brz verify-signatures."""

from breezy import (
    gpg,
    tests,
    )


class TestVerifySignatures(tests.TestCaseWithTransport):

    def monkey_patch_gpg(self):
        """Monkey patch the gpg signing strategy to be a loopback.

        This also registers the cleanup, so that we will revert to
        the original gpg strategy when done.
        """
        # monkey patch gpg signing mechanism
        self.overrideAttr(gpg, 'GPGStrategy', gpg.LoopbackGPGStrategy)

    def setup_tree(self, location='.'):
        wt = self.make_branch_and_tree(location)
        wt.commit("base A", allow_pointless=True, rev_id=b'A')
        wt.commit("base B", allow_pointless=True, rev_id=b'B')
        wt.commit("base C", allow_pointless=True, rev_id=b'C')
        wt.commit("base D", allow_pointless=True, rev_id=b'D',
                  committer='Alternate <alt@foo.com>')
        wt.add_parent_tree_id(b"aghost")
        wt.commit("base E", allow_pointless=True, rev_id=b'E')
        return wt

    def test_verify_signatures(self):
        wt = self.setup_tree()
        self.monkey_patch_gpg()
        self.run_bzr('sign-my-commits')
        out = self.run_bzr('verify-signatures', retcode=1)
        self.assertEqual(('4 commits with valid signatures\n'
                          '0 commits with key now expired\n'
                          '0 commits with unknown keys\n'
                          '0 commits not valid\n'
                          '1 commit not signed\n', ''), out)

    def test_verify_signatures_acceptable_key(self):
        wt = self.setup_tree()
        self.monkey_patch_gpg()
        self.run_bzr('sign-my-commits')
        out = self.run_bzr(['verify-signatures', '--acceptable-keys=foo,bar'],
                           retcode=1)
        self.assertEqual(('4 commits with valid signatures\n'
                          '0 commits with key now expired\n'
                          '0 commits with unknown keys\n'
                          '0 commits not valid\n'
                          '1 commit not signed\n', ''), out)

    def test_verify_signatures_verbose(self):
        wt = self.setup_tree()
        self.monkey_patch_gpg()
        self.run_bzr('sign-my-commits')
        out = self.run_bzr('verify-signatures --verbose', retcode=1)
        self.assertEqual(
            ('4 commits with valid signatures\n'
             '  None signed 4 commits\n'
             '0 commits with key now expired\n'
             '0 commits with unknown keys\n'
             '0 commits not valid\n'
             '1 commit not signed\n'
             '  1 commit by author Alternate <alt@foo.com>\n', ''), out)

    def test_verify_signatures_verbose_all_valid(self):
        wt = self.setup_tree()
        self.monkey_patch_gpg()
        self.run_bzr('sign-my-commits')
        self.run_bzr(['sign-my-commits', '.', 'Alternate <alt@foo.com>'])
        out = self.run_bzr('verify-signatures --verbose')
        self.assertEqual(('All commits signed with verifiable keys\n'
                          '  None signed 5 commits\n', ''), out)
