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

import os
import shutil

from bzrlib import (
    add,
    bzrdir,
    osutils,
    plugin,
    workingtree,
    )
from bzrlib.tests.TestUtil import TestLoader
from bzrlib.tests.blackbox import ExternalBase


class Benchmark(ExternalBase):

    _cached_kernel_like_tree = None
    _cached_kernel_like_added_tree = None
    _cached_kernel_like_committed_tree = None

    def make_kernel_like_tree(self, url=None, root='.',
                              hardlink_working=False):
        """Setup a temporary tree roughly like a kernel tree.
        
        :param url: Creat the kernel like tree as a lightweight checkout
        of a new branch created at url.
        :param hardlink_working: instead of creating a new copy of all files
            just hardlink the working tree. Tests must request this, because
            they must break links if they want to change the files
        """
        if url is not None:
            b = bzrdir.BzrDir.create_branch_convenience(url)
            d = bzrdir.BzrDir.create(root)
            bzrlib.branch.BranchReferenceFormat().initialize(d, b)
            tree = d.create_workingtree()
        else:
            tree = bzrdir.BzrDir.create_standalone_workingtree(root)

        self._link_or_copy_kernel_files(root=root, do_link=hardlink_working)
        return tree

    def _make_kernel_files(self, root='.'):
        # a kernel tree has ~10000 and 500 directory, with most files around 
        # 3-4 levels deep. 
        # we simulate this by three levels of dirs named 0-7, givin 512 dirs,
        # and 20 files each.
        files = []
        for outer in range(8):
            files.append("%s/" % outer)
            for middle in range(8):
                files.append("%s/%s/" % (outer, middle))
                for inner in range(8):
                    prefix = "%s/%s/%s/" % (outer, middle, inner)
                    files.append(prefix)
                    files.extend([prefix + str(foo) for foo in range(20)])
        cwd = osutils.getcwd()
        os.chdir(root)
        self.build_tree(files)
        os.chdir(cwd)

    def _link_or_copy_kernel_files(self, root, do_link=True):
        """Hardlink the kernel files from the cached location.

        If the platform doesn't correctly support hardlinking files, it
        reverts to just creating new ones.
        """

        if not osutils.hardlinks_good() or not do_link:
            # Turns out that 'shutil.copytree()' is no faster than
            # just creating them. Probably the python overhead.
            # Plain _make_kernel_files takes 5s
            # cp -a takes 3s
            # using hardlinks takes < 1s.
            self._make_kernel_files(root=root)
            return

        if Benchmark._cached_kernel_like_tree is None:
            cache_dir = osutils.pathjoin(self.TEST_ROOT,
                                         'cached_kernel_like_tree')
            os.mkdir(cache_dir)
            self._make_kernel_files(root=cache_dir)
            self._protect_files(cache_dir)
            Benchmark._cached_kernel_like_tree = cache_dir

        # Hardlinking the target directory is *much* faster (7s => <1s).
        osutils.copy_tree(Benchmark._cached_kernel_like_tree, root,
                          handlers={'file':os.link})

    def _clone_tree(self, source, dest, link_bzr=False, link_working=True):
        """Copy the contents from a given location to another location.
        Optionally hardlink certain pieces of the tree.

        :param source: The directory to copy
        :param dest: The destination
        :param link_bzr: Should the .bzr/ files be hardlinked?
        :param link_working: Should the working tree be hardlinked?
        """
        # We use shutil.copyfile so that we don't copy permissions
        # because most of our source trees are marked readonly to
        # prevent modifying in the case of hardlinks
        handlers = {'file':shutil.copyfile}
        if osutils.hardlinks_good():
            if link_working:
                if link_bzr:
                    handlers = {'file':os.link}
                else:
                    # Don't hardlink files inside bzr
                    def file_handler(source, dest):
                        if '.bzr/' in source:
                            shutil.copyfile(source, dest)
                        else:
                            os.link(source, dest)
                    handlers = {'file':file_handler}
            elif link_bzr:
                # Only link files inside .bzr/
                def file_handler(source, dest):
                    if '.bzr/' in source:
                        os.link(source, dest)
                    else:
                        shutil.copyfile(source, dest)
                handlers = {'file':file_handler}
        osutils.copy_tree(source, dest, handlers=handlers)

    def _protect_files(self, root):
        """Chmod all files underneath 'root' to prevent writing

        :param root: The base directory to modify
        """
        for dirinfo, entries in osutils.walkdirs(root):
            for relpath, name, kind, st, abspath in entries:
                if kind == 'file':
                    os.chmod(abspath, 0440)

    def make_kernel_like_added_tree(self, root='.',
                                    hardlink_working=True):
        """Make a kernel like tree, with all files added

        :param root: Where to create the files
        :param hardlink_working: Instead of copying all of the working tree
            files, just hardlink them to the cached files. Tests can unlink
            files that they will change.
        """
        # There isn't much underneath .bzr, so we don't support hardlinking
        # it. Testing showed there wasn't much gain, and there is potentially
        # a problem if someone modifies something underneath us.
        if Benchmark._cached_kernel_like_added_tree is None:
            cache_dir = osutils.pathjoin(self.TEST_ROOT,
                                         'cached_kernel_like_added_tree')
            # Get a basic tree with working files
            tree = self.make_kernel_like_tree(root=cache_dir,
                                              hardlink_working=True)
            # Add everything to it
            add.smart_add_tree(tree, [cache_dir], recurse=True, save=True)

            self._protect_files(cache_dir+'/.bzr')
            Benchmark._cached_kernel_like_added_tree = cache_dir

        self._clone_tree(Benchmark._cached_kernel_like_added_tree, root,
                         link_working=hardlink_working)
        return workingtree.WorkingTree.open(root)

    def make_kernel_like_committed_tree(self, root='.',
                                    hardlink_working=True,
                                    hardlink_bzr=False):
        """Make a kernel like tree, with all files added and committed

        :param root: Where to create the files
        :param hardlink_working: Instead of copying all of the working tree
            files, just hardlink them to the cached files. Tests can unlink
            files that they will change.
        :param hardlink_bzr: Hardlink the .bzr directory. For readonly 
            operations this is safe, and shaves off a lot of setup time
        """
        if Benchmark._cached_kernel_like_committed_tree is None:
            cache_dir = osutils.pathjoin(self.TEST_ROOT,
                                         'cached_kernel_like_committed_tree')
            # Get a basic tree with working files
            tree = self.make_kernel_like_added_tree(root=cache_dir,
                                                    hardlink_working=True)
            tree.commit('first post', rev_id='r1')

            self._protect_files(cache_dir+'/.bzr')
            Benchmark._cached_kernel_like_committed_tree = cache_dir

        # Now we have a cached tree, just copy it
        self._clone_tree(Benchmark._cached_kernel_like_committed_tree, root,
                         link_bzr=hardlink_bzr,
                         link_working=hardlink_working)
        return workingtree.WorkingTree.open(root)

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
