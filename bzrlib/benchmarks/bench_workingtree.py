# Copyright (C) 2006 by Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as published by
# the Free Software Foundation.
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

    def test_walkdirs_kernel_like_tree(self):
        """Walking a kernel sized tree is fast!(150ms)."""
        self.make_kernel_like_tree()
        self.run_bzr('add')
        tree = WorkingTree.open('.')
        # on roberts machine: this originally took:  157ms/4177ms
        # plain os.walk takes 213ms on this tree
        self.time(list, tree.walkdirs())

    def test_walkdirs_kernel_like_tree_unknown(self):
        """Walking a kernel sized tree is fast!(150ms)."""
        self.make_kernel_like_tree()
        tree = WorkingTree.open('.')
        # on roberts machine: this originally took:  157ms/4177ms
        # plain os.walk takes 213ms on this tree
        self.time(list, tree.walkdirs())
