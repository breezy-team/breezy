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

"""Tests for bzr benchmark utilities performance."""


from bzrlib.benchmarks import Benchmark


class MakeKernelLikeTreeBenchmark(Benchmark):

    def test_01_make_kernel_like_tree(self):
        """Making a kernel sized tree should be ~ 5seconds on modern disk.""" 
        # on roberts machine: this originally took:  7372ms/ 7479ms
        # with the LocalTransport._abspath call:     3730ms/ 3778ms
        self.time(self.make_kernel_like_tree)

    def test_02_make_kernel_like_tree(self):
        """Hardlinking a kernel-like working tree should be ~1s"""
        # Make sure we have populated the cache first
        self.make_kernel_like_tree(root='foo', hardlink_working=True)
        self.time(self.make_kernel_like_tree, root='bar',
                  hardlink_working=True)

    def test_03_make_kernel_like_added_tree(self):
        """Time the first creation of a kernel like added tree"""
        # This may not be an accurate test, in the case that the cached entry
        # has already been created
        self.time(self.make_kernel_like_added_tree, root='foo')

    def test_04_make_kernel_like_added_tree(self):
        """Time the second creation of a kernel like added tree 
        (this should be a clone)
        """
        # Call make_kernel_like_added_tree to make sure it is cached
        self.make_kernel_like_added_tree(root='foo')
        self.time(self.make_kernel_like_added_tree, root='bar')

    def test_05_make_kernel_like_committed_tree(self):
        """Time the first creation of a committed kernel like tree"""
        # This may not be an accurate test, in the case that the cached entry
        # has already been created
        self.time(self.make_kernel_like_committed_tree, root='foo')

    def test_06_make_kernel_like_committed_tree(self):
        """Time the second creation of a committed kernel like tree 
        (this should be a clone)
        """
        # Call make_kernel_like_committed_tree to make sure it is cached
        # we just throw it away, so hardlink the first bzr directory
        self.make_kernel_like_committed_tree(root='foo', hardlink_bzr=True)
        self.time(self.make_kernel_like_committed_tree, root='bar')

    def test_07_make_kernel_like_committed_tree_hardlink(self):
        """Time the creation of a committed kernel like tree 
        (this should also hardlink the .bzr/ directory)
        """
        # Call make_kernel_like_committed_tree to make sure it is cached
        self.make_kernel_like_committed_tree(root='foo', hardlink_bzr=True)
        self.time(self.make_kernel_like_committed_tree, root='bar',
                    hardlink_bzr=True)


