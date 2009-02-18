# Copyright (C) 2009 Canonical Ltd
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

"""Tests for the launchpad-open command."""

from bzrlib.osutils import abspath

from bzrlib.tests import TestCaseWithTransport


class TestLaunchpadOpen(TestCaseWithTransport):

    def run_open(self, location, retcode=0):
        out, err = self.run_bzr(
            ['launchpad-open', '--dry-run', location], retcode=retcode)
        return err.splitlines()

    def test_non_branch(self):
        # Running lp-open on a non-branch prints a simple error.
        self.assertEqual(
            ['bzr: ERROR: Not a branch: "%s/".' % abspath('.')],
            self.run_open('.', retcode=3))

    def test_no_public_location(self):
        self.make_branch('not-public')
        self.assertEqual(
            ['bzr: ERROR: There is no public branch set for "%s/".'
             % abspath('not-public')],
            self.run_open('not-public', retcode=3))

    def test_non_launchpad_branch(self):
        branch = self.make_branch('non-lp')
        url = 'http://example.com/non-lp'
        branch.set_public_branch(url)
        self.assertEqual(
            ['bzr: ERROR: %s is not hosted on Launchpad.' % url],
            self.run_open('non-lp', retcode=3))

    def test_launchpad_branch(self):
        branch = self.make_branch('lp')
        branch.set_public_branch(
            'bzr+ssh://bazaar.launchpad.net/~foo/bar/baz')
        self.assertEqual(
            ['Opening https://code.edge.launchpad.net/~foo/bar/baz in web '
             'browser'],
            self.run_open('lp'))
