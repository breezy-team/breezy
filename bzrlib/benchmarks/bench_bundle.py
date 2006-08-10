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

"""Tests for bzr bundle performance."""


from bzrlib.benchmarks import Benchmark


class BundleBenchmark(Benchmark):
    """
    The bundle tests should (also) be done at a lower level with
    direct call to the bzrlib."""
    

    def test_create_bundle_known_kernel_like_tree(self):
        """
        Create a bundle for a kernel sized tree with no ignored, unknowns,
        or added and one commit.""" 
        self.make_kernel_like_tree()
        self.run_bzr('add')
        self.run_bzr('commit', '-m', 'initial import')
        self.time(self.run_bzr, 'bundle', '--revision', '..-1')

    def test_create_bundle_many_commit_tree (self):
        """
        Create a bundle for a tree with many commits but no changes.""" 
        self.make_many_commit_tree()
        self.time(self.run_bzr, 'bundle', '--revision', '..-1')

    def test_create_bundle_heavily_merged_tree(self):
        """
        Create a bundle for a heavily merged tree.""" 
        self.make_heavily_merged_tree()
        self.time(self.run_bzr, 'bundle', '--revision', '..-1')

    #XXX tests for applying a bundle are still missing

        
 
