# Copyright (C) 2005-2010  Canonical Ltd
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
from bzrlib.tests import TestCaseWithTransport


class TestNick(TestCaseWithTransport):

    def test_nick_command(self):
        """bzr nick for viewing, setting nicknames"""
        self.make_branch_and_tree('me.dev')
        os.chdir('me.dev')
        nick = self.run_bzr('nick')[0]
        self.assertEqual('me.dev\n', nick)
        # set the nickname
        self.run_bzr("nick moo")
        nick = self.run_bzr('nick')[0]
        self.assertEqual('moo\n', nick)

    def test_autonick_urlencoded(self):
        # https://bugs.launchpad.net/bzr/+bug/66857 -- nick was printed
        # urlencoded but shouldn't be
        self.make_branch_and_tree('!repo')
        os.chdir('!repo')
        nick = self.run_bzr('nick')[0]
        self.assertEqual('!repo\n', nick)

    def test_bound_nick(self):
        """Check that nick works well for checkouts."""
        base = self.make_branch_and_tree('base')
        child = self.make_branch_and_tree('child')
        os.chdir('child')
        self.assertEqual('child', self.run_bzr('nick')[0][:-1])
        self.assertEqual(False,
                         child.branch.get_config().has_explicit_nickname())
        self.run_bzr('bind ../base')
        self.assertEqual(base.branch.nick, self.run_bzr('nick')[0][:-1])
        self.assertEqual(False,
                         child.branch.get_config().has_explicit_nickname())

        self.run_bzr('unbind')
        self.run_bzr("nick explicit_nick")
        self.assertEqual("explicit_nick", self.run_bzr('nick')[0][:-1])
        self.assertEqual("explicit_nick",
                         child.branch.get_config()._get_explicit_nickname())
        self.run_bzr('bind ../base')
        self.assertEqual(base.branch.nick, self.run_bzr('nick')[0][:-1])
        self.assertEqual(base.branch.nick,
                         child.branch.get_config()._get_explicit_nickname())

    def test_boundless_nick(self):
        """Nick defaults to implicit local nick when bound branch is AWOL"""
        base = self.make_branch_and_tree('base')
        child = self.make_branch_and_tree('child')
        os.chdir('child')
        self.run_bzr('bind ../base')
        self.assertEqual(base.branch.nick, self.run_bzr('nick')[0][:-1])
        self.assertEqual(False,
                         child.branch.get_config().has_explicit_nickname())
        osutils.rmtree('../base')
        self.assertEqual('child', self.run_bzr('nick')[0][:-1])

    def test_nick_directory(self):
        """Test --directory option"""
        self.make_branch_and_tree('me.dev')
        nick = self.run_bzr(['nick', '--directory=me.dev'])[0]
        self.assertEqual('me.dev\n', nick)
        self.run_bzr(['nick', '-d', 'me.dev', 'moo'])
        nick = self.run_bzr(['nick', '--directory', 'me.dev'])[0]
        self.assertEqual('moo\n', nick)
