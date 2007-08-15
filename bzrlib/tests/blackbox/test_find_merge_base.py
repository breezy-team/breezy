# Copyright (C) 2005 Canonical Ltd
# -*- coding: utf-8 -*-
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
import os

from bzrlib.tests.blackbox import ExternalBase


class TestFindMergeBase(ExternalBase):

    def test_find_merge_base(self):
        a_tree = self.make_branch_and_tree('a')
        a_tree.commit(message='foo', allow_pointless=True)
        b_tree = a_tree.bzrdir.sprout('b').open_workingtree()
        q = self.run_bzr('find-merge-base a b')[0]
        a_tree.commit(message='bar', allow_pointless=True)
        b_tree.commit(message='baz', allow_pointless=True)
        r = self.run_bzr('find-merge-base b a')[0]
        self.assertEqual(q, r)
        
    def test_find_null_merge_base(self):
        tree = self.make_branch_and_tree('foo')
        tree.commit('message')
        tree2 = self.make_branch_and_tree('bar')
        r = self.run_bzr('find-merge-base foo bar')[0]
        self.assertEqual('merge base is revision null:\n', r)
