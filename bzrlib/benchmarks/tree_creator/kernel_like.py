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

"""Tree creators for kernel-like trees"""

import errno
import os

from bzrlib import (
    add,
    bzrdir,
    osutils,
    workingtree,
    xml5,
    )

from bzrlib.benchmarks.tree_creator import TreeCreator


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
        try:
            os.mkdir(root)
        except OSError, e:
            if e.errno not in (errno.EEXIST,):
                raise
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


class KernelLikeInventoryCreator(TreeCreator):
    """Return just the memory representation of a committed kernel-like tree"""

    def __init__(self, test):
        super(KernelLikeInventoryCreator, self).__init__(test,
            tree_name='kernel_like_inventory',
            link_working=True,
            link_bzr=True,
            hot_cache=True)

    def ensure_cached(self):
        """Make sure we have a cached version of the kernel-like inventory"""
        cache_dir = self._get_cache_dir()
        if cache_dir is None:
            return

        if self.is_cached():
            return

        committed_creator = KernelLikeCommittedTreeCreator(self._test,
                                                           link_working=True,
                                                           link_bzr=True,
                                                           hot_cache=False)
        committed_creator.ensure_cached()
        committed_cache_dir = committed_creator._get_cache_dir()
        committed_tree = workingtree.WorkingTree.open(committed_cache_dir)
        rev_tree = committed_tree.basis_tree()
        os.mkdir(cache_dir)
        f = open(cache_dir+'/inventory', 'wb')
        try:
            xml5.serializer_v5.write_inventory(rev_tree.inventory, f)
        finally:
            f.close()

    def create(self):
        """Create a kernel like inventory

        :return: An Inventory object.
        """
        cache_dir = self._get_cache_dir()
        if cache_dir is None:
            return self._create_and_return()

        self.ensure_cached()
        return self._open_cached(cache_dir)

    def _create_and_return(self):
        """Create a kernel-like tree, and return its inventory"""
        creator = KernelLikeCommittedTreeCreator(self._test,
                                                 link_working=True,
                                                 link_bzr=True,
                                                 hot_cache=False)
        tree = creator.create('.')
        return tree.basis_tree().inventory

    def _open_cached(self, cache_dir):
        f = open(cache_dir + '/inventory', 'rb')
        try:
            return xml5.serializer_v5.read_inventory(f)
        finally:
            f.close()
