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

import errno
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

    def make_kernel_like_tree(self, url=None, root='.',
                              link_working=False):
        """Setup a temporary tree roughly like a kernel tree.
        
        :param url: Creat the kernel like tree as a lightweight checkout
        of a new branch created at url.
        :param link_working: instead of creating a new copy of all files
            just hardlink the working tree. Tests must request this, because
            they must break links if they want to change the files
        """
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
        creator = HeavilyMergedTreeCreator(self, link_bzr=hardlink)
        return creator.create(root=directory_name)


class TreeCreator(object):
    """Just a basic class which is used to create various test trees"""

    CACHE_ROOT = None

    def __init__(self, test, tree_name,
                 link_bzr=False,
                 link_working=False,
                 hot_cache=True):
        """Instantiate a new creator object, supply the id of the tree"""

        self._cache_root = TreeCreator.CACHE_ROOT
        self._test = test
        self._tree_name = tree_name
        self._link_bzr = link_bzr
        self._link_working = link_working
        self._hot_cache = hot_cache
        if not osutils.hardlinks_good():
            self._link_working = self._link_bzr = False

    def is_caching_enabled(self):
        """Will we try to cache the tree we create?"""
        return self._cache_root is not None

    def is_cached(self):
        """Is this tree already cached?"""
        cache_dir = self._get_cache_dir()
        if cache_dir is None:
            return False
        return os.path.exists(cache_dir)
        
    def disable_cache(self):
        """Do not use the cache"""
        self._cache_root = None

    def ensure_cached(self):
        """If caching, make sure the cached copy exists"""
        cache_dir = self._get_cache_dir()
        if cache_dir is None:
            return

        if not self.is_cached():
            self._create_tree(root=cache_dir, in_cache=True)

    def create(self, root):
        """Create a new tree at 'root'.

        :return: A WorkingTree object.
        """
        cache_dir = self._get_cache_dir()
        if cache_dir is None:
            # Not caching
            return self._create_tree(root, in_cache=False)

        self.ensure_cached()

        return self._clone_cached_tree(root)

    def _get_cache_dir(self):
        """Get the directory to use for caching this tree

        :return: The path to use for caching. If None, caching is disabled
        """
        if self._cache_root is None:
            return None
        return osutils.pathjoin(self._cache_root, self._tree_name)

    def _create_tree(self, root, in_cache=False):
        """Create the desired tree in the given location.

        Children should override this function to provide the actual creation
        of the desired tree. This will be called by 'create()'. If it is
        building a tree in the cache, before copying it to the real target,
        it will pass in_cache=True
        """
        raise NotImplemented(self._create_tree)

    def _clone_cached_tree(self, dest):
        """Copy the contents of the cached dir into the destination
        Optionally hardlink certain pieces of the tree.

        This is just meant as a helper function for child classes

        :param dest: The destination to copy things to
        """
        # We use shutil.copyfile so that we don't copy permissions
        # because most of our source trees are marked readonly to
        # prevent modifying in the case of hardlinks
        handlers = {'file':shutil.copyfile}
        if osutils.hardlinks_good():
            if self._link_working:
                if self._link_bzr:
                    handlers = {'file':os.link}
                else:
                    # Don't hardlink files inside bzr
                    def file_handler(source, dest):
                        if '.bzr/' in source:
                            shutil.copyfile(source, dest)
                        else:
                            os.link(source, dest)
                    handlers = {'file':file_handler}
            elif self._link_bzr:
                # Only link files inside .bzr/
                def file_handler(source, dest):
                    if '.bzr/' in source:
                        os.link(source, dest)
                    else:
                        shutil.copyfile(source, dest)
                handlers = {'file':file_handler}

        source = self._get_cache_dir()
        osutils.copy_tree(source, dest, handlers=handlers)
        tree = workingtree.WorkingTree.open(dest)
        if self._hot_cache:
            tree.lock_write()
            try:
                # tree._hashcache.scan() just checks and removes
                # entries that are out of date
                # we need to actually store new ones
                for path, ie in tree.inventory.iter_entries_by_dir():
                    tree.get_file_sha1(ie.file_id, path)
            finally:
                tree.unlock()
        # If we didn't iterate the tree, the hash cache is technically
        # invalid, and it would be better to remove it, but there is
        # no public api for that.
        return tree

    def _protect_files(self, root):
        """Chmod all files underneath 'root' to prevent writing

        This is a helper function for child classes.

        :param root: The base directory to modify
        """
        for dirinfo, entries in osutils.walkdirs(root):
            for relpath, name, kind, st, abspath in entries:
                if kind == 'file':
                    os.chmod(abspath, 0440)


class KernelLikeTreeCreator(TreeCreator):
    """Create a basic tree with ~10k unversioned files""" 

    def __init__(self, test, link_working=False, url=None):
        super(KernelLikeTreeCreator, self).__init__(test,
            tree_name='kernel_like_tree',
            link_working=link_working,
            link_bzr=False)

        self._url = url

    def create(self, root):
        """Create all the kernel files in the given location.

        This is overloaded for compatibility reasons.
        """
        if self._url is not None:
            b = bzrdir.BzrDir.create_branch_convenience(self._url)
            d = bzrdir.BzrDir.create(root)
            bzrlib.branch.BranchReferenceFormat().initialize(d, b)
            tree = d.create_workingtree()
        else:
            tree = bzrdir.BzrDir.create_standalone_workingtree(root)

        if not self._link_working or not self.is_caching_enabled():
            # Turns out that 'shutil.copytree()' is no faster than
            # just creating them. Probably the python overhead.
            # Plain _make_kernel_files takes 3-5s
            # cp -a takes 3s
            # using hardlinks takes < 1s.
            self._create_tree(root=root, in_cache=False)
            return tree

        self.ensure_cached()
        cache_dir = self._get_cache_dir()
        osutils.copy_tree(cache_dir, root,
                          handlers={'file':os.link})
        return tree

    def _create_tree(self, root, in_cache=False):
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
        self._test.build_tree(files)
        os.chdir(cwd)
        if in_cache:
            self._protect_files(root)


class KernelLikeAddedTreeCreator(TreeCreator):

    def __init__(self, test, link_working=False, hot_cache=True):
        super(KernelLikeAddedTreeCreator, self).__init__(test,
            tree_name='kernel_like_added_tree',
            link_working=link_working,
            link_bzr=False,
            hot_cache=hot_cache)

    def _create_tree(self, root, in_cache=False):
        """Create a kernel-like tree with the all files added

        :param root: The root directory to create the files
        :param in_cache: Is this being created in the cache dir?
        """
        kernel_creator = KernelLikeTreeCreator(self._test,
                                               link_working=in_cache)
        tree = kernel_creator.create(root=root)

        # Add everything to it
        tree.lock_write()
        try:
            add.smart_add_tree(tree, [root], recurse=True, save=True)
            if in_cache:
                self._protect_files(root+'/.bzr')
        finally:
            tree.unlock()
        return tree


class KernelLikeCommittedTreeCreator(TreeCreator):
    """Create a tree with ~10K files, and a single commit adding all of them"""

    def __init__(self, test, link_working=False, link_bzr=False,
                 hot_cache=True):
        super(KernelLikeCommittedTreeCreator, self).__init__(test,
            tree_name='kernel_like_committed_tree',
            link_working=link_working,
            link_bzr=link_bzr,
            hot_cache=hot_cache)

    def _create_tree(self, root, in_cache=False):
        """Create a kernel-like tree with all files committed

        :param root: The root directory to create the files
        :param in_cache: Is this being created in the cache dir?
        """
        kernel_creator = KernelLikeAddedTreeCreator(self._test,
                                                    link_working=in_cache,
                                                    hot_cache=(not in_cache))
        tree = kernel_creator.create(root=root)
        tree.commit('first post', rev_id='r1')

        if in_cache:
            self._protect_files(root+'/.bzr')
        return tree


class SimpleManyCommitTreeCreator(TreeCreator):
    """Create an empty tree with lots of commits"""

    def __init__(self, test, link_bzr=False):
        super(SimpleManyCommitTreeCreator, self).__init__(test,
            tree_name='many_commit_tree',
            link_bzr=link_bzr,
            link_working=False,
            hot_cache=True)

    def _create_tree(self, root, in_cache=False):
        tree = bzrdir.BzrDir.create_standalone_workingtree(root)
        tree.lock_write()
        try:
            for i in xrange(1000):
                tree.commit('no-changes commit %d' % i)
        finally:
            tree.unlock()
        if in_cache:
            self._protect_files(root+'/.bzr')

        return tree


class HeavilyMergedTreeCreator(TreeCreator):
    """Create a tree in which almost every commit is a merge.
   
    No file changes are included.  This produces two trees, 
    one of which is returned.  Except for the first commit, every
    commit in its revision-history is a merge of another commit in the other
    tree.  
    Not hardlinking the working tree, because there are no working tree files.
    """

    def __init__(self, test, link_bzr=True):
        super(HeavilyMergedTreeCreator, self).__init__(test,
            tree_name='heavily_merged_tree',
            link_bzr=link_bzr,
            link_working=False,
            hot_cache=True)

    def _create_tree(self, root, in_cache=False):
        try:
            os.mkdir(root)
        except (IOError, OSError), e:
            if e.errno not in (errno.EEXIST,):
                raise

        tree = bzrdir.BzrDir.create_standalone_workingtree(root)
        tree.lock_write()
        try:
            tree2 = tree.bzrdir.sprout(root + '/tree2').open_workingtree()
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
                tree2.unlock()
        finally:
            tree.unlock()
        if in_cache:
            self._protect_files(root+'/.bzr')
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
