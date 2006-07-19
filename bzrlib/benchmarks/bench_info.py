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


class InfoBenchmark(Benchmark):
    """This is a stub. Use this benchmark with a network transport.
    Currently "bzr info sftp://..." takes > 4 min"""

    def test_no_ignored_unknown_kernel_like_tree(self):
        """Info in a kernel sized tree with no ignored or unknowns. """
        self.make_kernel_like_tree()
        self.run_bzr('add')
        self.time(self.run_bzr, 'info')

    def test_no_changes_known_kernel_like_tree(self):
        """Info in a kernel sized tree with no ignored, unknowns, or added.""" 
        self.make_kernel_like_tree()
        self.run_bzr('add')
        self.run_bzr('commit', '-m', 'initial import')
        self.time(self.run_bzr, 'info')

 
