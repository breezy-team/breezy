# Copyright (C) 2010 Canonical Ltd
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


"""Black-box tests for brz lookup-revision.
"""

from breezy import tests


class TestLookupRevision(tests.TestCaseWithTransport):

    def test_lookup_revison_directory(self):
        """Test --directory option"""
        tree = self.make_branch_and_tree('a')
        tree.commit('This revision', rev_id=b'abcd')
        out, err = self.run_bzr(['lookup-revision', '-d', 'a', '1'])
        self.assertEqual('abcd\n', out)
        self.assertEqual('', err)
