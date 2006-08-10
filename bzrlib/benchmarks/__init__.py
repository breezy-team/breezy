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

from bzrlib import bzrdir, plugin
from bzrlib.tests.TestUtil import TestLoader
from bzrlib.tests.blackbox import ExternalBase


class Benchmark(ExternalBase):

    def make_kernel_like_tree(self, url=None):
        """Setup a temporary tree roughly like a kernel tree.
        
        :param url: Creat the kernel like tree as a lightweight checkout
        of a new branch created at url.
        """
        # a kernel tree has ~10000 and 500 directory, with most files around 
        # 3-4 levels deep. 
        # we simulate this by three levels of dirs named 0-7, givin 512 dirs,
        # and 20 files each.
        if url is not None:
            b = bzrdir.BzrDir.create_branch_convenience(url)
            d = bzrdir.BzrDir.create('.')
            bzrlib.branch.BranchReferenceFormat().initialize(d, b)
            d.create_workingtree()
        else:
            self.run_bzr('init')
        files = []
        for outer in range(8):
            files.append("%s/" % outer)
            for middle in range(8):
                files.append("%s/%s/" % (outer, middle))
                for inner in range(8):
                    prefix = "%s/%s/%s/" % (outer, middle, inner)
                    files.append(prefix)
                    files.extend([prefix + str(foo) for foo in range(20)])
        self.build_tree(files)

    def make_many_commit_tree(self, directory_name='.'):
        """Create a tree with many commits.
        
        No files change are included.
        """
        tree = bzrdir.BzrDir.create_standalone_workingtree(directory_name)
        tree.lock_write()
        tree.branch.lock_write()
        tree.branch.repository.lock_write()
        try:
            for i in xrange(1000):
                tree.commit('no-changes commit %d' % i)
        finally:
            try:
                try:
                    tree.branch.repository.unlock()
                finally:
                    tree.branch.unlock()
            finally:
                tree.unlock()
        return tree

    def make_heavily_merged_tree(self, directory_name='.'):
        """Create a tree in which almost every commit is a merge.
       
        No files change are included.  This produces two trees, 
        one of which is returned.  Except for the first commit, every
        commit in its revision-history is a merge another commit in the other
        tree.
        """
        tree = bzrdir.BzrDir.create_standalone_workingtree(directory_name)
        tree.lock_write()
        try:
            tree2 = tree.bzrdir.sprout('tree2').open_workingtree()
            tree2.lock_write()
            try:
                for i in xrange(250):
                    revision_id = tree.commit('no-changes commit %d-a' % i)
                    tree2.branch.fetch(tree.branch, revision_id)
                    tree2.set_pending_merges([revision_id])
                    revision_id = tree2.commit('no-changes commit %d-b' % i)
                    tree.branch.fetch(tree2.branch, revision_id)
                    tree.set_pending_merges([revision_id])
                tree.set_pending_merges([])
            finally:
                tree.unlock()
        finally:
            tree2.unlock()
        return tree


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
