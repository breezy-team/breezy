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

"""Benchmarks of bzr commit."""


from bzrlib.benchmarks import Benchmark


class CommitBenchmark(Benchmark):

    def test_commit_kernel_like_tree(self):
        """Commit of a fresh import of a clean kernel sized tree."""
        self.make_kernel_like_tree()
        self.run_bzr('add')
        # on robertc's machine the first sample of this took 59750ms/77682ms
        self.time(self.run_bzr, 'commit', '-m', 'first post')
