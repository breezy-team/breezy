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


class Status(Benchmark):

    def test_clean_kernel_like_tree(self):
        """Status in a clean kernel sized tree should be bearable (<2secs) fast.""" 
        self.make_kernel_tree()
        self.run_bzr('add')
        # on robertc's machine the first sample of this took 1687ms/15994ms
        self.time(self.run_bzr, 'status')
