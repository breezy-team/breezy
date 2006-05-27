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

"""Tests for bzr working tree performance."""


from bzrlib.benchmarks import Benchmark
from bzrlib.workingtree import WorkingTree


class WorkingTreeBenchmark(Benchmark):

    def test_list_files_kernel_like_tree(self):
        self.make_kernel_like_tree()
        self.run_bzr('add')
        tree = WorkingTree.open('.')
        self.time(list, tree.list_files())

