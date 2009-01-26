# Copyright (C) 2009 Jelmer Vernooij <jelmer@samba.org>
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

from bzrlib.plugins.git.fetch import BzrFetchGraphWalker
from bzrlib.plugins.git.mapping import default_mapping

from bzrlib.tests import TestCaseWithTransport

class FetchGraphWalkerTests(TestCaseWithTransport):

    def setUp(self):
        TestCaseWithTransport.setUp(self)
        self.mapping = default_mapping

    def test_empty(self):
        tree = self.make_branch_and_tree("wt")
        graphwalker = BzrFetchGraphWalker(tree.branch.repository, self.mapping)
        self.assertEquals(None, graphwalker.next())


