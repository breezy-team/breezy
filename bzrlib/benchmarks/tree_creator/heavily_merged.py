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

"""Tree creator for many commits, but no changes"""

import errno
import os

from bzrlib import (
    bzrdir,
    )

from bzrlib.benchmarks.tree_creator import TreeCreator


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
                    tree2.add_parent_tree_id(revision_id)
                    revision_id = tree2.commit('no-changes commit %d-b' % i)
                    tree.branch.fetch(tree2.branch, revision_id)
                    tree.add_parent_tree_id(revision_id)
                tree.set_parent_ids(tree.get_parent_ids()[:1])
            finally:
                tree2.unlock()
        finally:
            tree.unlock()
        if in_cache:
            self._protect_files(root+'/.bzr')
        return tree


