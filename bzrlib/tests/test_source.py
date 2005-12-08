# Copyright (C) 2005 by Canonical Ltd
#   Authors: Robert Collins <robert.collins@canonical.com>
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

"""These tests are tests about the source code of bzrlib itself.

They are useful for testing code quality, checking coverage metric etc.
"""

# import system imports here
import os
import sys

#import bzrlib specific imports here
from bzrlib.tests import TestCase
import bzrlib.branch


class TestApiUsage(TestCase):

    def test_branch_working_tree(self):
        """Test that the number of uses of working_tree in branch is stable."""
        occurences = 0
        source = file(bzrlib.branch.__file__[:-1], 'r')
        for line in source:
            if line.find('self.working_tree()') > -1:
                occurences += 1
        # do not even think of increasing this number. If you think you need to
        # increase it, then you almost certainly are doing something wrong as
        # the relationship from working_tree to branch is one way.
        # This number should be 0, but the basis_inventory merge was done
        # before this test was written.
        self.assertEqual(2, occurences)
