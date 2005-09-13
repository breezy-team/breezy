# Copyright (C) 2005 by Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

import sys
import os

from cStringIO import StringIO

from bzrlib.selftest import TestCase, TestCaseInTempDir
from bzrlib.branch import Branch


class TestAncestry(TestCaseInTempDir):
    def test_straightline_ancestry(self):
        """Test ancestry file when just committing."""
        b = Branch('.', init=True)

        b.commit(message='one',
                 allow_pointless=True,
                 rev_id='tester@foo--1')

        b.commit(message='two',
                 allow_pointless=True,
                 rev_id='tester@foo--2')

        ancs = b.get_ancestry('tester@foo--2')



# TODO: check that ancestry is updated to include indirectly merged revisions
        
        

if __name__ == '__main__':
    import unittest
    sys.exit(unittest.main())
