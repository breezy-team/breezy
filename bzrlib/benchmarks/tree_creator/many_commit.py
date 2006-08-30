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

"""Tree creator for many commits, including file changes."""

from bzrlib import (
    bzrdir,
    )

from bzrlib.benchmarks.tree_creator import TreeCreator


class ManyCommitTreeCreator(TreeCreator):
    """Create an tree many files and many commits."""

    def __init__(self, test, link_bzr=False, num_files=10, num_commits=10):
        tree_name = 'many_files_many_commit_tree_%d_%d' % (
            num_files, num_commits)
        super(ManyCommitTreeCreator, self).__init__(test,
            tree_name=tree_name,
            link_bzr=link_bzr,
            link_working=False,
            hot_cache=True)
        self.files = ["%s" % (i, ) for i in range(num_files)]
        self.num_files = num_files
        self.num_commits = num_commits

    def _create_tree(self, root, in_cache=False):
        num_files = self.num_files
        num_commits = self.num_commits
        files = ["%s/%s" % (root, fn) for fn in self.files]
        for fn in files:
            f = open(fn, "wb")
            try:
                f.write("some content\n")
            finally:
                f.close()
        tree = bzrdir.BzrDir.create_standalone_workingtree(root)
        tree.add(self.files)
        tree.lock_write()
        try:
            tree.commit('initial commit')
            for i in range(num_commits):
                fn = files[i % len(files)]
                content = range(i) + [i, i, i, ""]
                f = open(fn, "wb")
                try:
                    f.write("\n".join([str(i) for i in content]))
                finally:
                    f.close()
                tree.commit("changing file %s" % fn)
        finally:
            tree.unlock()
        return tree

