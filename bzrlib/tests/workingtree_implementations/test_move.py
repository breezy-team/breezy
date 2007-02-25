# Copyright (C) 2006 Canonical Ltd
# Authors:  Robert Collins <robert.collins@canonical.com>
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

"""Tests for interface conformance of 'workingtree.put_mkdir'"""

from bzrlib.workingtree_4 import WorkingTreeFormat4
from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree


class TestMove(TestCaseWithWorkingTree):

    def test_move_correct_call_named(self):
        """tree.move has the deprecated parameter 'to_name'.
        It has been replaced by 'to_dir' for consistency.
        Test the new API using named parameter
        """
        self.build_tree(['a1', 'sub1/'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a1', 'sub1'])
        tree.commit('initial commit')
        tree.move(['a1'], to_dir='sub1', after=False)

    def test_move_correct_call_unnamed(self):
        """tree.move has the deprecated parameter 'to_name'.
        It has been replaced by 'to_dir' for consistency.
        Test the new API using unnamed parameter
        """
        self.build_tree(['a1', 'sub1/'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a1', 'sub1'])
        tree.commit('initial commit')
        tree.move(['a1'], 'sub1', after=False)

    def test_move_deprecated_wrong_call(self):
        """tree.move has the deprecated parameter 'to_name'.
        It has been replaced by 'to_dir' for consistency.
        Test the new API using wrong parameter
        """
        self.build_tree(['a1', 'sub1/'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a1', 'sub1'])
        tree.commit('initial commit')
        self.assertRaises(TypeError, tree.move, ['a1'],
                          to_this_parameter_does_not_exist='sub1',
                          after=False)

    def test_move_deprecated_call(self):
        """tree.move has the deprecated parameter 'to_name'.
        It has been replaced by 'to_dir' for consistency.
        Test the new API using deprecated parameter
        """
        self.build_tree(['a1', 'sub1/'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a1', 'sub1'])
        tree.commit('initial commit')

        try:
            self.callDeprecated(['The parameter to_name was deprecated'
                                 ' in version 0.13. Use to_dir instead'],
                                tree.move, ['a1'], to_name='sub1',
                                after=False)
        except TypeError:
            # WorkingTreeFormat4 doesn't have to maintain api compatibility
            # since it was deprecated before the class was introduced.
            if not isinstance(self.workingtree_format, WorkingTreeFormat4):
                raise

