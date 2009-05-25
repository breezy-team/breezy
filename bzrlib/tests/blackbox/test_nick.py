# Copyright (C) 2005, 2006  Canonical Ltd
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

"""Black-box tests for bzr nick."""

import os

import bzrlib
from bzrlib import osutils
from bzrlib.tests.blackbox import ExternalBase


class TestNick(ExternalBase):

    def test_nick_command(self):
        """bzr nick for viewing, setting nicknames"""
        self.make_branch_and_tree('me.dev')
        os.chdir('me.dev')
        nick = self.run_bzr('nick')[0]
        self.assertEqual(nick, 'me.dev\n')
        # set the nickname
        self.run_bzr("nick moo")
        nick = self.run_bzr('nick')[0]
        self.assertEqual(nick, 'moo\n')

    def test_autonick_urlencoded(self):
        # https://bugs.launchpad.net/bzr/+bug/66857 -- nick was printed
        # urlencoded but shouldn't be
        self.make_branch_and_tree('!repo')
        os.chdir('!repo')
        nick = self.run_bzr('nick')[0]
        self.assertEqual(nick, '!repo\n')

    def test_bound_nick(self):
        """Check that nick works well for checkouts."""
        base = self.make_branch_and_tree('base')
        child = self.make_branch_and_tree('child')
        os.chdir('child')
        self.assertEqual(self.run_bzr('nick')[0][:-1], 'child')
        self.assertEqual(child.branch.get_config().has_explicit_nickname(),
            False)
        self.run_bzr('bind ../base')
        self.assertEqual(self.run_bzr('nick')[0][:-1], base.branch.nick)
        self.assertEqual(child.branch.get_config().has_explicit_nickname(),
            False)

        self.run_bzr('unbind')
        self.run_bzr("nick explicit_nick")
        self.assertEqual(self.run_bzr('nick')[0][:-1], "explicit_nick")
        self.assertEqual(child.branch.get_config()._get_explicit_nickname(),
            "explicit_nick")
        self.run_bzr('bind ../base')
        self.assertEqual(self.run_bzr('nick')[0][:-1], base.branch.nick)
        self.assertEqual(child.branch.get_config()._get_explicit_nickname(),
            base.branch.nick)

    def test_boundless_nick(self):
        """Nick defaults to implicit local nick when bound branch is AWOL"""
        base = self.make_branch_and_tree('base')
        child = self.make_branch_and_tree('child')
        os.chdir('child')
        self.run_bzr('bind ../base')
        self.assertEqual(self.run_bzr('nick')[0][:-1], base.branch.nick)
        self.assertEqual(child.branch.get_config().has_explicit_nickname(),
            False)
        osutils.rmtree('../base')
        self.assertEqual(self.run_bzr('nick')[0][:-1], 'child')
