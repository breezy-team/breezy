# Copyright (C) 2005 by Canonical Development Ltd
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


from StringIO import StringIO

from bzrlib.bzrdir import BzrDir
from bzrlib.status import show_pending_merges
from bzrlib.tests import TestCaseInTempDir


class TestStatus(TestCaseInTempDir):

    def test_pending_none(self):
        # Test whether show_pending_merges works in a tree with no commits
        tree = BzrDir.create_standalone_workingtree('a')
        tree.commit('empty commit')
        tree2 = BzrDir.create_standalone_workingtree('b')
        tree2.branch.fetch(tree.branch)
        tree2.set_pending_merges([tree.last_revision()])
        output = StringIO()
        show_pending_merges(tree2, output)
        self.assertContainsRe(output.getvalue(), 'empty commit')
