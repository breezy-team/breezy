# Copyright (C) 2005 Aaron Bentley
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
#

"""Tests of the 'brz fetch-ghosts' command."""

from .. import TestCaseWithTransport


class TestFetchGhosts(TestCaseWithTransport):

    def test_fetch_ghosts(self):
        self.run_bzr('init')
        self.run_bzr('fetch-ghosts .')

    def test_fetch_ghosts_with_saved(self):
        wt = self.make_branch_and_tree('.')
        wt.branch.set_parent('.')
        self.run_bzr('fetch-ghosts')

    def test_fetch_ghosts_more(self):
        self.run_bzr('init')
        with open('myfile', 'wb') as f:
            f.write(b'hello')
        self.run_bzr('add')
        self.run_bzr('commit -m hello')
        self.run_bzr('branch . my_branch')
        self.run_bzr('fetch-ghosts my_branch')
