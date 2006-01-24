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


from cStringIO import StringIO
import os
import sys

from bzrlib.tests import TestCase, TestCaseWithTransport
from bzrlib.branch import Branch
from bzrlib.revision import is_ancestor


class TestAncestry(TestCaseWithTransport):

    def test_straightline_ancestry(self):
        """Test ancestry file when just committing."""
        wt = self.make_branch_and_tree('.')
        b = wt.branch

        wt.commit(message='one',
                  allow_pointless=True,
                  rev_id='tester@foo--1')

        wt.commit(message='two',
                  allow_pointless=True,
                  rev_id='tester@foo--2')

        ancs = b.get_ancestry('tester@foo--2')
        self.assertEqual([None, 'tester@foo--1', 'tester@foo--2'], ancs)
        self.assertEqual([None, 'tester@foo--1'], 
                         b.get_ancestry('tester@foo--1'))

    def test_none_is_always_an_ancestor(self):
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        # note this is tested before any commits are done.
        self.assertEqual(True, is_ancestor(None, None, b))
        wt.commit(message='one',
                  allow_pointless=True,
                  rev_id='tester@foo--1')
        self.assertEqual(True, is_ancestor(None, None, b))
        self.assertEqual(True, is_ancestor('tester@foo--1', None, b))
        self.assertEqual(False, is_ancestor(None, 'tester@foo--1', b))


# TODO: check that ancestry is updated to include indirectly merged revisions
