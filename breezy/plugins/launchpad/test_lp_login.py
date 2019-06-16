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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Tests for the launchpad-login command."""

from . import account
from ...tests import TestCaseWithTransport


class TestLaunchpadLogin(TestCaseWithTransport):
    """Tests for launchpad-login."""

    def test_login_without_name_when_not_logged_in(self):
        # lp-login without a 'name' parameter returns the user ID of the
        # logged in user. If no one is logged in, we tell the user as much.
        out, err = self.run_bzr(['launchpad-login', '--no-check'], retcode=1)
        self.assertEqual('No Launchpad user ID configured.\n', out)
        self.assertEqual('', err)

    def test_login_with_name_sets_login(self):
        # lp-login with a 'name' parameter sets the Launchpad login.
        self.run_bzr(['launchpad-login', '--no-check', 'foo'])
        self.assertEqual('foo', account.get_lp_login())

    def test_login_without_name_when_logged_in(self):
        # lp-login without a 'name' parameter returns the user ID of the
        # logged in user.
        account.set_lp_login('foo')
        out, err = self.run_bzr(['launchpad-login', '--no-check'])
        self.assertEqual('foo\n', out)
        self.assertEqual('', err)

    def test_login_with_name_no_output_by_default(self):
        # lp-login with a 'name' parameter produces no output by default.
        out, err = self.run_bzr(['launchpad-login', '--no-check', 'foo'])
        self.assertEqual('', out)
        self.assertEqual('', err)

    def test_login_with_name_verbose(self):
        # lp-login with a 'name' parameter and a verbose flag produces some
        # information about what Bazaar just did.
        out, err = self.run_bzr(
            ['launchpad-login', '-v', '--no-check', 'foo'])
        self.assertEqual("Launchpad user ID set to 'foo'.\n", out)
        self.assertEqual('', err)

    def test_logout(self):
        out, err = self.run_bzr(
            ['launchpad-login', '-v', '--no-check', 'foo'])
        self.assertEqual("Launchpad user ID set to 'foo'.\n", out)
        self.assertEqual('', err)

        out, err = self.run_bzr(['launchpad-logout', '-v'])
        self.assertEqual("Launchpad user ID foo logged out.\n", out)
        self.assertEqual('', err)

    def test_logout_not_logged_in(self):
        out, err = self.run_bzr(['launchpad-logout', '-v'], retcode=1)
        self.assertEqual('Not logged into Launchpad.\n', out)
        self.assertEqual("", err)
