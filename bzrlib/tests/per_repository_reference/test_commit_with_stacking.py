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
        base_tree = self.make_branch_and_tree('base')
        self.build_tree(['base/f1.txt'])
        base_tree.add(['f1.txt'], ['f1.txt-id'])
        base_tree.commit('initial', rev_id='initial-rev-id')
        stacked_tree = base_tree.bzrdir.sprout('stacked',
            stacked=True).open_workingtree()
        return base_tree, stacked_tree

    def test_simple_commit(self):
        base_tree, stacked_tree = self.make_stacked_target()
        self.assertEqual(1,
                len(stacked_tree.branch.repository._fallback_repositories))
        self.build_tree_contents([('stacked/f1.txt', 'new content\n')])
        stacked_tree.commit('new content', rev_id='new-rev-id')
        # We open the repository without fallbacks to ensure the data is
        # locally true
        stacked_only_repo = stacked_tree.bzrdir.open_repository()
        r1_key = ('initial-rev-id',)
        self.assertEqual([r1_key],
            sorted(stacked_only_repo.inventories.get_parent_map([r1_key])))
        # And we should be able to pull this revision into another stacked
        # branch
        stacked2_branch = base_tree.bzrdir.sprout('stacked2',
                                                  stacked=True).open_branch()
        stacked2_branch.repository.fetch(stacked_only_repo,
                                         revision_id='new-rev-id')

    def test_merge_commit(self):
        base_tree, stacked_tree = self.make_stacked_target()
        self.build_tree_contents([('base/f1.txt', 'new content\n')])
        base_tree.commit('second base', 'base2-rev-id')
        to_be_merged_tree = base_tree.bzrdir.sprout('merged')
        self.build_tree(['merged/f2.txt'])
        to_be_merged_tree.add(['f2.txt'], ['f2.txt-id'])
        to_be_merged_tree.commit('new-to-be-merged', rev_id='to-merge-rev-id')
        stacked_tree.merge_from_branch(to_be_merged_tree.branch)
        stacked_tree.commit('merge', rev_id='merged-rev-id')
        # Since to-merge-rev-id isn't in base, it should be in stacked.
        # 'base2-rev-id' shouldn't have the revision, but we should have the
        # inventory. Also, 'merged-rev-id' has a parent of 'initial-rev-id',
        # which is in base. So we should have its inventory, but not its
        # revision-id.
        stacked_only_repo = stacked_tree.bzrdir.open_repository()
        r1_key = ('initial-rev-id',)
        r2_key = ('base2-rev-id',)
        r3_key = ('to-merge-rev-id',)
        r4_key = ('merged-rev-id',)
        all_keys = [r1_key, r2_key, r3_key, r4_key]
        self.assertEqual(sorted([r3_key, r4_key]),
            sorted(stacked_only_repo.revisions.get_parent_map(all_keys)))
        self.assertEqual(sorted(all_keys),
            sorted(stacked_only_repo.inventories.get_parent_map(all_keys)))

    def test_multi_stack(self):
        """base + stacked + stacked-on-stacked"""
        base_tree, stacked_tree = self.make_stacked_target()
        self.build_tree(['stacked/f2.txt'])
        stacked_tree.add(['f2.txt'], ['f2.txt-id'])
        stacked_tree.commit('add f2', rev_id='stacked-rev-id')
        stacked2_tree = stacked_tree.bzrdir.sprout('stacked2',
                            stacked=True).open_workingtree()
        # stacked2 is stacked on stacked, but we revert its content to rev1, so
        # that it needs to pull the basis information from a
        # fallback-of-fallback.
        stacked2_tree.update(revision='initial-rev-id')
        self.build_tree(['stacked2/f3.txt'])
        stacked2_tree.add(['f3.txt'], ['f3.txt-id'])
        stacked_tree.commit('add f3', rev_id='stacked2-rev-id')
        stacked2_only_repo = stacked2_tree.bzrdir.open_repository()
        r1_key = ('initial-rev-id',)
        self.assertEqual([r1_key],
            sorted(stacked2_only_repo.inventories.get_parent_map([r1_key])))
