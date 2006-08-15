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

"""Base implementation of TreeCreator classes

These are classes that are used to easily create test trees.
"""

import os
import shutil

from bzrlib import (
    osutils,
    workingtree,
    )


class TreeCreator(object):
    """Just a basic class which is used to create various test trees"""

    CACHE_ROOT = None

    def __init__(self, test, tree_name,
                 link_bzr=False,
                 link_working=False,
                 hot_cache=True):
        """Instantiate a new creator object, supply the id of the tree

        :param test: A TestCaseWithTransport object (most creators need 
            we need the build_tree functionality)
        """

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


