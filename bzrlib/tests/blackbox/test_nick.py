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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Black-box tests for bzr nick."""

import os

import bzrlib
from bzrlib.tests.blackbox import ExternalBase


class TestNick(ExternalBase):

    def test_nick_command(self):
        """bzr nick for viewing, setting nicknames"""
        os.mkdir('me.dev')
        os.chdir('me.dev')
        self.runbzr('init')
        nick = self.runbzr("nick",backtick=True)
        self.assertEqual(nick, 'me.dev\n')
        nick = self.runbzr("nick moo")
        nick = self.runbzr("nick",backtick=True)
        self.assertEqual(nick, 'moo\n')

    def test_autonick_urlencoded(self):
        os.mkdir('!repo')
        os.chdir('!repo')
        self.runbzr('init')
        nick = self.runbzr("nick",backtick=True)
        self.assertEqual(nick, '!repo\n')
