# Copyright (C) 2006 Canonical Ltd
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

"""Tests for bzr working tree performance."""

import os

from bzrlib import ignores
from bzrlib.benchmarks import Benchmark
from bzrlib.workingtree import WorkingTree


class WorkingTreeBenchmark(Benchmark):

    def test_list_files_kernel_like_tree(self):
        tree = self.make_kernel_like_added_tree()
        self.time(list, tree.list_files())

    def test_list_files_unknown_kernel_like_tree(self):
        tree = self.make_kernel_like_tree(link_working=True)
        tree = WorkingTree.open('.')
        # Bzr only traverses directories if they are versioned
        # So add all the directories, but not the files, yielding
        # lots of unknown files.
        for root, dirs, files in os.walk('.'):
            if '.bzr' in dirs:
                dirs.remove('.bzr')
            if root == '.':
                continue
            tree.add(root)
        self.time(list, tree.list_files())

    def test_is_ignored_single_call(self):
        """How long does is_ignored take to initialise and check one file."""
        t = self.make_branch_and_tree('.')
        self.time(t.is_ignored, "CVS")
        
    def test_is_ignored_10824_calls(self):
        """How long does is_ignored take to initialise and check one file."""
        t = self.make_branch_and_tree('.')
        def call_is_ignored_10824_not_ignored():
            for x in xrange(10824):
                t.is_ignored(str(x))
        self.time(call_is_ignored_10824_not_ignored)

    def test_is_ignored_10_patterns(self):
        t = self.make_branch_and_tree('.')
        ignores.add_runtime_ignores([u'*.%i' % i for i in range(1, 9)])
        ignores.add_runtime_ignores(['./foo', 'foo/bar'])
        self.time(t.is_ignored,'bar')
        ignores._runtime_ignores = set()

    def test_is_ignored_50_patterns(self):
        t = self.make_branch_and_tree('.')
        ignores.add_runtime_ignores([u'*.%i' % i for i in range(1, 49)])
        ignores.add_runtime_ignores(['./foo', 'foo/bar'])
        self.time(t.is_ignored,'bar')
        ignores._runtime_ignores = set()

    def test_is_ignored_100_patterns(self):
        t = self.make_branch_and_tree('.')
        ignores.add_runtime_ignores([u'*.%i' % i for i in range(1, 99)])
        ignores.add_runtime_ignores(['./foo', 'foo/bar'])
        self.time(t.is_ignored,'bar')
        ignores._runtime_ignores = set()

    def test_is_ignored_1000_patterns(self):
        t = self.make_branch_and_tree('.')
        ignores.add_runtime_ignores([u'*.%i' % i for i in range(1, 999)])
        ignores.add_runtime_ignores(['./foo', 'foo/bar'])
        self.time(t.is_ignored,'bar')
        ignores._runtime_ignores = set()


