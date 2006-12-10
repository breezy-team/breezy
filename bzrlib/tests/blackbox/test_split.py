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


import os

from bzrlib import bzrdir, tests


class TestSplit(tests.TestCaseWithTransport):

    def test_split(self):
        self.build_tree(['a/', 'a/b/', 'a/b/c'])
        wt = self.make_branch_and_tree('a')
        wt.add(['b', 'b/c'])
        wt.commit('rev1')
        self.run_bzr('split', 'a/b')
        self.run_bzr_error(('.* is not versioned',), 'split', 'q')

    def test_split_repo_failure(self):
        repo = self.make_repository('branch', shared=True, 
                                    format=bzrdir.get_knit1_format())
        a_branch = repo.bzrdir.create_branch()
        self.build_tree(['a/', 'a/b/', 'a/b/c/', 'a/b/c/d'])
        wt = a_branch.create_checkout('a', lightweight=True)
        wt.add(['b', 'b/c', 'b/c/d'], ['b-id', 'c-id', 'd-id'])
        wt.commit('added files')
        self.run_bzr_error(('must upgrade your branch at .*a',), 'split', 
                            'a/b')
