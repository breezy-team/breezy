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

from bzrlib.tests import TestCaseWithTransport


class TestLaunchpadLogin(TestCaseWithTransport):
    """Tests for launchpad-login."""

    def test_login_when_not_logged_in(self):
        # lp-login without a 'name' parameter returns the user ID of the
        # logged in user. If no one is logged in, we tell the user as much.
        out, err = self.run_bzr(['launchpad-login'], retcode=1)
        self.assertEqual('No Launchpad user ID configured.\n', out)
        self.assertEqual('', err)
