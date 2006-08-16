# Copyright (C) 2006 by Canonical Ltd
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

"""Benchmark test suite for bzr."""

from bzrlib import (
    plugin,
    )
from bzrlib.tests.TestUtil import TestLoader
from bzrlib.tests.blackbox import ExternalBase


class Benchmark(ExternalBase):

    def make_kernel_like_tree(self, url=None, root='.',
                              link_working=False):
        """Setup a temporary tree roughly like a kernel tree.
        
        :param url: Creat the kernel like tree as a lightweight checkout
        of a new branch created at url.
        :param link_working: instead of creating a new copy of all files
            just hardlink the working tree. Tests must request this, because
            they must break links if they want to change the files
        """
        from bzrlib.benchmarks.tree_creator.kernel_like import (
            KernelLikeTreeCreator,
            )
        creator = KernelLikeTreeCreator(self, link_working=link_working,
                                        url=url)
        return creator.create(root=root)

    def make_kernel_like_added_tree(self, root='.',
                                    link_working=True,
                                    hot_cache=True):
        """Make a kernel like tree, with all files added

        :param root: Where to create the files
        :param link_working: Instead of copying all of the working tree
            files, just hardlink them to the cached files. Tests can unlink
            files that they will change.
        :param hot_cache: Run through the newly created tree and make sure
            the stat-cache is correct. The old way of creating a freshly
            added tree always had a hot cache.
        """
        from bzrlib.benchmarks.tree_creator.kernel_like import (
            KernelLikeAddedTreeCreator,
            )
        creator = KernelLikeAddedTreeCreator(self, link_working=link_working,
                                             hot_cache=hot_cache)
        return creator.create(root=root)

    def make_kernel_like_committed_tree(self, root='.',
                                    link_working=True,
                                    link_bzr=False,
                                    hot_cache=True):
        """Make a kernel like tree, with all files added and committed

        :param root: Where to create the files
        :param link_working: Instead of copying all of the working tree
            files, just hardlink them to the cached files. Tests can unlink
            files that they will change.
        :param link_bzr: Hardlink the .bzr directory. For readonly 
            operations this is safe, and shaves off a lot of setup time
        """
        from bzrlib.benchmarks.tree_creator.kernel_like import (
            KernelLikeCommittedTreeCreator,
            )
        creator = KernelLikeCommittedTreeCreator(self,
                                                 link_working=link_working,
                                                 link_bzr=link_bzr,
                                                 hot_cache=hot_cache)
        return creator.create(root=root)

    def make_many_commit_tree(self, directory_name='.',
                              hardlink=False):
        """Create a tree with many commits.
        
        No file changes are included. Not hardlinking the working tree, 
        because there are no working tree files.
        """
        from bzrlib.benchmarks.tree_creator.simple_many_commit import (
            SimpleManyCommitTreeCreator,
            )
        creator = SimpleManyCommitTreeCreator(self, link_bzr=hardlink)
        return creator.create(root=directory_name)

    def make_heavily_merged_tree(self, directory_name='.',
                                 hardlink=False):
        """Create a tree in which almost every commit is a merge.
       
        No file changes are included.  This produces two trees, 
        one of which is returned.  Except for the first commit, every
        commit in its revision-history is a merge another commit in the other
        tree.  Not hardlinking the working tree, because there are no working 
        tree files.
        """
        from bzrlib.benchmarks.tree_creator.heavily_merged import (
            HeavilyMergedTreeCreator,
            )
        creator = HeavilyMergedTreeCreator(self, link_bzr=hardlink)
        return creator.create(root=directory_name)


def test_suite():
    """Build and return a TestSuite which contains benchmark tests only."""
    testmod_names = [ \
                   'bzrlib.benchmarks.bench_add',
                   'bzrlib.benchmarks.bench_bench',
                   'bzrlib.benchmarks.bench_cache_utf8',
                   'bzrlib.benchmarks.bench_checkout',
                   'bzrlib.benchmarks.bench_commit',
                   'bzrlib.benchmarks.bench_inventory',
                   'bzrlib.benchmarks.bench_log',
                   'bzrlib.benchmarks.bench_osutils',
                   'bzrlib.benchmarks.bench_rocks',
                   'bzrlib.benchmarks.bench_status',
                   'bzrlib.benchmarks.bench_transform',
                   'bzrlib.benchmarks.bench_workingtree',
                   ]
    suite = TestLoader().loadTestsFromModuleNames(testmod_names) 

    # Load any benchmarks from plugins
    for name, module in plugin.all_plugins().items():
        if getattr(module, 'bench_suite', None) is not None:
            suite.addTest(module.bench_suite())

    return suite
