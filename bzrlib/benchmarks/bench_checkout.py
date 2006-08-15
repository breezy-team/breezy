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

"""Tests for bzr tree building (checkout) performance."""


from bzrlib.benchmarks import Benchmark
from bzrlib.benchmarks.tree_creator.kernel_like import (
    make_kernel_like_committed_tree,
    )


class CheckoutBenchmark(Benchmark):

    def test_build_kernel_like_tree(self):
        """Checkout of a clean kernel sized tree should be (<10secs)."""
        make_kernel_like_committed_tree(self, '.', link_bzr=True)
        self.time(self.run_bzr, 'checkout', '--lightweight', '.', 'acheckout')
