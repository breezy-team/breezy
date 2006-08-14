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

from bzrlib import (
    osutils,
    )
from bzrlib.benchmarks import Benchmark
from bzrlib.tests import TestSkipped


class MakeKernelLikeTreeBenchmark(Benchmark):

    def test_make_kernel_like_tree(self):
        """Making a kernel sized tree should be ~ 5seconds on modern disk.""" 
        # on roberts machine: this originally took:  7372ms/ 7479ms
        # with the LocalTransport._abspath call:     3730ms/ 3778ms
        # with AtomicFile tuning:                    2888ms/ 2926ms
        # switching to transport.append:             1468ms/ 2849ms
        self.time(self.make_kernel_like_tree)

    def test_02_make_kernel_like_tree(self):
        """Hardlinking a kernel-like working tree should be ~1s"""
        # make sure kernel_like_tree is cached
        cache_dir, is_cached = self.get_cache_dir('kernel_like_tree')
        if cache_dir is None:
            # Caching is disabled, this test is meaningless
            raise TestSkipped('caching is disabled')
        if not is_cached:
            # If it has not been cached yet, create it
            self.make_kernel_like_tree(root='foo', link_working=True)
        self.time(self.make_kernel_like_tree, root='bar',
                  link_working=True)

    def test_03_make_kernel_like_added_tree(self):
        """Time the first creation of a kernel like added tree"""
        orig_cache = Benchmark.CACHE_ROOT
        try:
            # Change to a local cache directory so we know this
            # really creates the files
            Benchmark.CACHE_ROOT = None
            self.time(self.make_kernel_like_added_tree, root='foo')
        finally:
            Benchmark.CACHE_ROOT = orig_cache

    def test_04_make_kernel_like_added_tree(self):
        """Time the second creation of a kernel like added tree 
        (this should be a clone)
        """
        # make sure kernel_like_added_tree is cached
        cache_dir, is_cached = self.get_cache_dir('kernel_like_added_tree')
        if cache_dir is None:
            # Caching is disabled, this test is meaningless
            raise TestSkipped('caching is disabled')
        if not is_cached:
            # If it has not been cached yet, create it
            self.make_kernel_like_added_tree(root='foo')
        self.time(self.make_kernel_like_added_tree, root='bar')

    def test_05_make_kernel_like_committed_tree(self):
        """Time the first creation of a committed kernel like tree"""
        orig_cache = Benchmark.CACHE_ROOT
        try:
            # Change to a local cache directory so we know this
            # really creates the files
            Benchmark.CACHE_ROOT = None
            self.time(self.make_kernel_like_committed_tree, root='foo')
        finally:
            Benchmark.CACHE_ROOT = orig_cache

    def test_06_make_kernel_like_committed_tree(self):
        """Time the second creation of a committed kernel like tree 
        (this should be a clone)
        """
        # Call make_kernel_like_committed_tree to make sure it is cached
        cache_dir, is_cached = self.get_cache_dir('kernel_like_committed_tree')
        if cache_dir is None:
            raise TestSkipped('caching is disabled')
        if not is_cached:
            self.make_kernel_like_committed_tree(root='foo')
        self.time(self.make_kernel_like_committed_tree, root='bar')

    def test_07_make_kernel_like_committed_tree_hardlink(self):
        """Time the creation of a committed kernel like tree 
        (this should also hardlink the .bzr/ directory)
        """
        # make sure kernel_like_committed_tree is cached
        cache_dir, is_cached = self.get_cache_dir('kernel_like_committed_tree')
        if cache_dir is None:
            raise TestSkipped('caching is disabled')
        if not is_cached:
            self.make_kernel_like_committed_tree(root='foo')
        self.time(self.make_kernel_like_committed_tree, root='bar',
                    link_bzr=True)


