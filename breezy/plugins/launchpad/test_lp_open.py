# Copyright (C) 2009, 2010, 2012 Canonical Ltd
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

"""Tests for the launchpad-open command."""

from ...tests import TestCaseWithTransport


class TestLaunchpadOpen(TestCaseWithTransport):

    def run_open(self, location, retcode=0, working_dir='.'):
        out, err = self.run_bzr(['launchpad-open', '--dry-run', location],
                                retcode=retcode,
                                working_dir=working_dir)
        return err.splitlines()

    def test_non_branch(self):
        # If given a branch with no public or push locations, lp-open will try
        # to guess the Launchpad page for the given URL / path. If it cannot
        # find one, it will raise an error.
        self.assertEqual(
            ['brz: ERROR: . is not registered on Launchpad.'],
            self.run_open('.', retcode=3))

    def test_no_public_location_no_push_location(self):
        self.make_branch('not-public')
        self.assertEqual(
            ['brz: ERROR: not-public is not registered on Launchpad.'],
            self.run_open('not-public', retcode=3))

    def test_non_launchpad_branch(self):
        branch = self.make_branch('non-lp')
        url = 'http://example.com/non-lp'
        branch.set_public_branch(url)
        self.assertEqual(
            ['brz: ERROR: %s is not registered on Launchpad.' %
                url],
            self.run_open('non-lp', retcode=3))

    def test_launchpad_branch_with_public_location(self):
        branch = self.make_branch('lp')
        branch.set_public_branch('bzr+ssh://bazaar.launchpad.net/~foo/bar/baz')
        self.assertEqual(
            ['Opening https://code.launchpad.net/~foo/bar/baz in web '
             'browser'],
            self.run_open('lp'))

    def test_launchpad_branch_with_public_and_push_location(self):
        branch = self.make_branch('lp')
        with branch.lock_write():
            branch.set_public_branch(
                'bzr+ssh://bazaar.launchpad.net/~foo/bar/public')
            branch.set_push_location(
                'bzr+ssh://bazaar.launchpad.net/~foo/bar/push')
        self.assertEqual(
            ['Opening https://code.launchpad.net/~foo/bar/public in web '
             'browser'],
            self.run_open('lp'))

    def test_launchpad_branch_with_no_public_but_with_push(self):
        # lp-open falls back to the push location if it cannot find a public
        # location.
        branch = self.make_branch('lp')
        branch.set_push_location('bzr+ssh://bazaar.launchpad.net/~foo/bar/baz')
        self.assertEqual(
            ['Opening https://code.launchpad.net/~foo/bar/baz in web '
             'browser'],
            self.run_open('lp'))

    def test_launchpad_branch_with_no_public_no_push(self):
        # If lp-open is given a branch URL and that branch has no public
        # location and no push location, then just try to look up the
        # Launchpad page for that URL.
        self.assertEqual(
            ['Opening https://code.launchpad.net/~foo/bar/baz in web '
             'browser'],
            self.run_open('bzr+ssh://bazaar.launchpad.net/~foo/bar/baz'))

    def test_launchpad_branch_subdirectory(self):
        # lp-open in a subdirectory of a registered branch should work
        wt = self.make_branch_and_tree('lp')
        wt.branch.set_push_location(
            'bzr+ssh://bazaar.launchpad.net/~foo/bar/baz')
        self.build_tree(['lp/a/'])
        self.assertEqual(
            ['Opening https://code.launchpad.net/~foo/bar/baz in web '
             'browser'],
            self.run_open('.', working_dir='lp/a'))
