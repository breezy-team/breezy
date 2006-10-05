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

"""Tests for tree transform performance"""

import os

from bzrlib.benchmarks import Benchmark
from bzrlib.osutils import pathjoin
from bzrlib.transform import TreeTransform
from bzrlib.workingtree import WorkingTree

class TransformBenchmark(Benchmark):

    def test_canonicalize_path(self):
        """Canonicalizing paths should be fast.""" 
        wt = self.make_kernel_like_tree(link_working=True)
        paths = []
        for dirpath, dirnames, filenames in os.walk('.'):
            paths.extend(pathjoin(dirpath, d) for d in dirnames)
            paths.extend(pathjoin(dirpath, f) for f in filenames)
        tt = TreeTransform(wt)
        self.time(self.canonicalize_paths, tt, paths)
        tt.finalize()

    def canonicalize_paths(self, tt, paths):
        for path in paths:
            tt.canonical_path(path)
