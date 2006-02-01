# Copyright (C) 2005 by Canonical Ltd
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

"""Test that various operations work in a non-ASCII environment."""

import os

from bzrlib.osutils import pathjoin
from bzrlib.tests import TestCaseWithTransport, TestSkipped
from bzrlib.workingtree import WorkingTree


class NonAsciiTest(TestCaseWithTransport):

    def test_add_in_nonascii_branch(self):
        """Test adding in a non-ASCII branch."""
        br_dir = u"\u1234"
        try:
            wt = self.make_branch_and_tree(br_dir)
        except UnicodeEncodeError:
            raise TestSkipped("filesystem can't accomodate nonascii names")
            return
        file(pathjoin(br_dir, "a"), "w").write("hello")
        wt.add(["a"], ["a-id"])
