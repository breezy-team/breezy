# Copyright (C) 2010 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA


from bzrlib.tests.per_repository import TestCaseWithRepository


class TestCommitWithStacking(TestCaseWithRepository):

    def make_stacked_target(self):
        base = self.make_branch_and_tree('base')
        self.build_tree(['base/f1.txt'])
        base.add(['f1.txt'], ['f1.txt-id'])
        stacked = base.bzrdir.sprout('stacked',
                                     stacked=True).open_workingtree()
        return base, stacked

    def test_simple_commit(self):
        base, stacked = self.make_stacked_target()
        self.assertEqual(1,
                len(stacked.branch.repository._fallback_repositories))
