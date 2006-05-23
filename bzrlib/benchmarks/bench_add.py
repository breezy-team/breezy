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

"""Tests for bzr add performance."""


from bzrlib.benchmarks import Benchmark


class AddBenchmark(Benchmark):

    def test_one_add_kernel_like_tree(self):
        """Adding a kernel sized tree should be bearable (<5secs) fast.""" 
        self.make_kernel_like_tree()
        # on roberts machine this originally took:  25936ms/32244ms
        # after making smart_add use the parent_ie:  5033ms/ 9368ms
        self.time(self.run_bzr, 'add')
