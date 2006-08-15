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
from bzrlib.benchmarks.tree_creator.kernel_like import (
    KernelLikeTreeCreator,
    KernelLikeAddedTreeCreator,
    KernelLikeCommittedTreeCreator,
    )
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
        creator = KernelLikeTreeCreator(self, link_working=True)
        if not creator.is_caching_enabled():
            raise TestSkipped('caching is disabled')
        creator.ensure_cached()
        self.time(creator.create, root='bar')

    def test_03_make_kernel_like_added_tree(self):
        """Time the first creation of a kernel like added tree"""
        creator = KernelLikeAddedTreeCreator(self)
        creator.disable_cache()
        self.time(creator.create, root='foo')

    def test_04_make_kernel_like_added_tree(self):
        """Time the second creation of a kernel like added tree 
        (this should be a clone)
        """
        # make sure kernel_like_added_tree is cached
        creator = KernelLikeAddedTreeCreator(self, link_working=True)
        if not creator.is_caching_enabled():
            # Caching is disabled, this test is meaningless
            raise TestSkipped('caching is disabled')
        creator.ensure_cached()
        self.time(creator.create, root='bar')

    def test_05_make_kernel_like_committed_tree(self):
        """Time the first creation of a committed kernel like tree"""
        creator = KernelLikeCommittedTreeCreator(self)
        creator.disable_cache()
        self.time(creator.create, root='foo')

    def test_06_make_kernel_like_committed_tree(self):
        """Time the second creation of a committed kernel like tree 
        (this should be a clone)
        """
        creator = KernelLikeCommittedTreeCreator(self,
                                                 link_working=True,
                                                 link_bzr=False)
        if not creator.is_caching_enabled():
            # Caching is disabled, this test is meaningless
            raise TestSkipped('caching is disabled')
        creator.ensure_cached()
        self.time(creator.create, root='bar')

    def test_07_make_kernel_like_committed_tree_hardlink(self):
        """Time the creation of a committed kernel like tree 
        (this should also hardlink the .bzr/ directory)
        """
        creator = KernelLikeCommittedTreeCreator(self,
                                                 link_working=True,
                                                 link_bzr=True)
        if not creator.is_caching_enabled():
            # Caching is disabled, this test is meaningless
            raise TestSkipped('caching is disabled')
        creator.ensure_cached()
        self.time(creator.create, root='bar')


