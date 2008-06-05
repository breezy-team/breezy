# Copyright (C) 2007 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


"""Black-box tests for 'bzr unknowns', which shows unknown files."""

from bzrlib.tests.blackbox import ExternalBase


class TestUnknowns(ExternalBase):

    def test_unknowns(self):
        """Test that 'unknown' command reports unknown files"""

        # in empty directory, no unknowns
        tree = self.make_branch_and_tree('.')
        self.assertEquals(self.run_bzr('unknowns')[0], '')

        # single unknown file
        self.build_tree_contents([('a', 'contents of a\n')])
        self.assertEquals(self.run_bzr('unknowns')[0], 'a\n')

        # multiple unknown files, including one with a space in its name
        self.build_tree(['b', 'c', 'd e'])
        self.assertEquals(self.run_bzr('unknowns')[0], 'a\nb\nc\n"d e"\n')

        # after add, file no longer shown
        tree.add(['a', 'd e'])
        self.assertEquals(self.run_bzr('unknowns')[0], 'b\nc\n')

        # after all added, none shown
        tree.add(['b', 'c'])
        self.assertEquals(self.run_bzr('unknowns')[0], '')
