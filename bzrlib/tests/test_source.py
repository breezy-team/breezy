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

    def find_occurences(self, rule, filename):
        """Find the number of occurences of rule in a file."""
        occurences = 0
        source = file(filename, 'r')
        for line in source:
            if line.find(rule) > -1:
                occurences += 1
        return occurences

    def source_file_name(self, package):
        """Return the path of the .py file for package."""
        path = package.__file__
        if path[-1] in 'co':
            return path[:-1]
        else:
            return path

    def test_branch_working_tree(self):
        """Test that the number of uses of working_tree in branch is stable."""
        occurences = self.find_occurences('self.working_tree()',
                                          self.source_file_name(bzrlib.branch))
        # do not even think of increasing this number. If you think you need to
        # increase it, then you almost certainly are doing something wrong as
        # the relationship from working_tree to branch is one way.
        # This number should be 0, but the basis_inventory merge was done
        # before this test was written. Note that this is an exact equality
        # so that when the number drops, it is not given a buffer but rather
        # this test updated immediately.
        self.assertEqual(1, occurences)

    def test_branch_WorkingTree(self):
        """Test that the number of uses of working_tree in branch is stable."""
        occurences = self.find_occurences('WorkingTree',
                                          self.source_file_name(bzrlib.branch))
        # do not even think of increasing this number. If you think you need to
        # increase it, then you almost certainly are doing something wrong as
        # the relationship from working_tree to branch is one way.
        # This number should be 4 (import NoWorkingTree and WorkingTree, 
        # raise NoWorkingTree from working_tree(), and construct a working tree
        # there) but a merge that regressed this was done before this test was
        # written. Note that this is an exact equality so that when the number
        # drops, it is not given a buffer but rather this test updated
        # immediately.
        self.assertEqual(9, occurences)
