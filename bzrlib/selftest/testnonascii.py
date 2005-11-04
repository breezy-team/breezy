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

from bzrlib.selftest import TestCaseInTempDir
from bzrlib.branch import Branch


class NonAsciiTest(TestCaseInTempDir):

    def test_add_in_nonascii_branch(self):
        """Test adding in a non-ASCII branch."""
        br_dir = u"\u1234"
        try:
            os.mkdir(br_dir)
            os.chdir(br_dir)
        except UnicodeEncodeError:
            self.log("filesystem can't accomodate nonascii names")
            return
        br = Branch.initialize(u".")
        file("a", "w").write("hello")
        br.add(["a"], ["a-id"])
