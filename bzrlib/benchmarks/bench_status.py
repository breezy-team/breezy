# Copyright (C) 2006 Canonical Ltd
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

"""Tests for bzr status performance."""


from bzrlib.benchmarks import Benchmark


class StatusBenchmark(Benchmark):

    def test_no_ignored_unknown_kernel_like_tree(self):
        """Status in a kernel sized tree with no ignored or unknowns.
        
        This should be bearable (<2secs) fast.
        """ 
        self.make_kernel_like_added_tree()
        # on robertc's machine the first sample of this took 1687ms/15994ms
        self.time(self.run_bzr, 'status')

    def test_no_changes_known_kernel_like_tree(self):
        """Status in a kernel sized tree with no ignored, unknowns, or added.""" 
        self.make_kernel_like_committed_tree(link_bzr=True)
        self.time(self.run_bzr, 'status')
