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

"""Tests for bzr status performance."""


from bzrlib.benchmarks import Benchmark


class StatusBenchmark(Benchmark):

    def test_no_ignored_unknown_kernel_like_tree(self):
        """Status in a kernel sized tree with no ignored or unknowns.
        
        This should be bearable (<2secs) fast.""" 
        self.make_kernel_like_tree()
        self.run_bzr('add')
        # on robertc's machine the first sample of this took 1687ms/15994ms
        self.time(self.run_bzr, 'status')

    def test_no_changes_known_kernel_like_tree(self):
        """Status in a kernel sized tree with no ignored, unknowns, or added.""" 
        self.make_kernel_like_tree()
        self.run_bzr('add')
        self.run_bzr('commit', '-m', 'initial import')
        self.time(self.run_bzr, 'status')

    def test_status_one_added_file_kernel_like_tree(self):
        """Status of a single added file in our stock large tree."""
        self.make_kernel_like_tree()
        self.run_bzr('add')
        self.run_bzr('commit', '-m', 'initial import')
        self.time(self.run_bzr, 'status', '3/3/3/10')
