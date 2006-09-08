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

"""Benchmarks of bzr commit."""

import os

from bzrlib.benchmarks import Benchmark
from bzrlib.transport.memory import MemoryServer
from bzrlib.transport import get_transport


class CommitBenchmark(Benchmark):

    def test_commit_kernel_like_tree(self):
        """Commit of a fresh import of a clean kernel sized tree."""
        # uncomment this to run the benchmark with the repository in memory
        # not disk
        # self.transport_server = MemoryServer
        # self.make_kernel_like_tree(self.get_url())
        tree = self.make_kernel_like_added_tree()
        self.time(self.run_bzr, 'commit', '-m', 'first post')

    def test_partial_commit_kernel_like_tree(self):
        """Commit of 1/8th of a fresh import of a clean kernel sized tree."""
        tree = self.make_kernel_like_added_tree()
        self.time(self.run_bzr, 'commit', '-m', 'first post', '1')

    def test_no_op_commit_in_kernel_like_tree(self):
        """Run commit --unchanged in a kernel sized tree"""
        tree = self.make_kernel_like_committed_tree()
        self.time(self.run_bzr, 'commit', '-m', 'no changes', '--unchanged')

    def test_commit_one_in_kernel_like_tree(self):
        """Time committing a single change, when not directly specified"""
        tree = self.make_kernel_like_committed_tree()

        # working-tree is hardlinked, so replace a file and commit the change
        os.remove('4/4/4/4')
        open('4/4/4/4', 'wb').write('new contents\n')
        self.time(self.run_bzr, 'commit', '-m', 'second')

    def test_partial_commit_one_in_kernel_like_tree(self):
        """Time committing a single change when it is directly specified"""
        tree = self.make_kernel_like_committed_tree()

        # working-tree is hardlinked, so replace a file and commit the change
        os.remove('4/4/4/4')
        open('4/4/4/4', 'wb').write('new contents\n')
        self.time(self.run_bzr, 'commit', '-m', 'second', '4/4/4/4')

    def make_simple_tree(self):
        """A small, simple tree. No caching needed"""
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/', 'b/c'])
        tree.add(['a', 'b', 'b/c'])
        return tree

    def test_cmd_commit(self):
        """Test execution of simple commit"""
        tree = self.make_simple_tree()
        self.time(self.run_bzr, 'commit', '-m', 'init simple tree')

    def test_cmd_commit_subprocess(self):
        """Text startup and execution of a simple commit.""" 
        tree = self.make_simple_tree()
        self.time(self.run_bzr_subprocess, 'commit', '-m', 'init simple tree')
