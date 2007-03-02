# Copyright (C) 2007 Canonical Ltd
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

"""Test iter_reverse_revision_history."""

from bzrlib import (
    errors,
    osutils,
    tests,
    )
from bzrlib.tests.repository_implementations.test_repository import TestCaseWithRepository


class TestIterReverseRevisionHistory(TestCaseWithRepository):

    def create_linear_history(self):
        tree = self.make_branch_and_memory_tree('tree')
        tree.lock_write()
        try:
            tree.add('')
            tree.commit('1', rev_id='rev1')
            tree.commit('2', rev_id='rev2')
            tree.commit('3', rev_id='rev3')
            tree.commit('4', rev_id='rev4')
        finally:
            tree.unlock()
        return tree

    def create_linear_history_with_utf8(self):
        tree = self.make_branch_and_memory_tree('tree')
        tree.lock_write()
        try:
            tree.add('') # needed for MemoryTree
            try:
                tree.commit(u'F\xb5', rev_id=u'rev-\xb5'.encode('utf8'))
            except errors.NonAsciiRevisionId:
                raise tests.TestSkipped("%s doesn't support non-ascii"
                                        " revision ids."
                                        % self.repository_format)
            tree.commit(u'B\xe5r', rev_id=u'rev-\xe5'.encode('utf8'))
        finally:
            tree.unlock()
        return tree

    def create_merged_history(self):
        # TODO: jam 20070216 MutableTree doesn't yet have the pull() or
        #       merge_from_branch() apis. So we have to use real trees for
        #       this.
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_branch_and_tree('tree2')
        tree1.lock_write()
        tree2.lock_write()
        try:
            tree1.add('')
            tree1.commit('rev-1-1', rev_id='rev-1-1')
            tree2.pull(tree1.branch)
            tree2.commit('rev-2-2', rev_id='rev-2-2')
            tree2.commit('rev-2-3', rev_id='rev-2-3')
            tree2.commit('rev-2-4', rev_id='rev-2-4')

            tree1.commit('rev-1-2', rev_id='rev-1-2')
            tree1.merge_from_branch(tree2.branch)
            tree1.commit('rev-1-3', rev_id='rev-1-3')

            tree2.commit('rev-2-5', rev_id='rev-2-5')
            # Make sure both repositories have all revisions
            tree1.branch.repository.fetch(tree2.branch.repository,
                                          revision_id='rev-2-5')
            tree2.branch.repository.fetch(tree1.branch.repository,
                                          revision_id='rev-1-3')
        finally:
            tree2.unlock()
            tree1.unlock()
        return tree1, tree2

    def test_is_generator(self):
        tree = self.create_linear_history()
        repo = tree.branch.repository

        rev_history = repo.iter_reverse_revision_history('rev4')
        self.assertEqual('rev4', rev_history.next())
        self.assertEqual('rev3', rev_history.next())
        self.assertEqual('rev2', rev_history.next())
        self.assertEqual('rev1', rev_history.next())
        self.assertRaises(StopIteration, rev_history.next)

    def assertRevHistoryList(self, expected, repo, revision_id):
        """Assert the return values of iter_reverse_revision_history."""
        actual = list(repo.iter_reverse_revision_history(revision_id))
        self.assertEqual(expected, actual)

    def test_linear_history(self):
        tree = self.create_linear_history()
        repo = tree.branch.repository

        self.assertRevHistoryList(['rev4', 'rev3', 'rev2', 'rev1'],
                                  repo, 'rev4')

    def test_partial_history(self):
        tree = self.create_linear_history()
        repo = tree.branch.repository

        self.assertRevHistoryList(['rev3', 'rev2', 'rev1'], repo, 'rev3')

    def test_revision_ids_are_utf8(self):
        tree = self.create_linear_history_with_utf8()
        repo = tree.branch.repository

        self.assertRevHistoryList(['rev-\xc3\xa5', 'rev-\xc2\xb5'],
                                  repo, 'rev-\xc3\xa5')

        self.callDeprecated([osutils._revision_id_warning],
                            self.assertRevHistoryList,
                                ['rev-\xc3\xa5', 'rev-\xc2\xb5'],
                                repo, u'rev-\xe5')

    def test_merged_history(self):
        tree1, tree2 = self.create_merged_history()
        repo = tree1.branch.repository

        self.assertRevHistoryList(['rev-1-1'],
                                  repo, 'rev-1-1')
        self.assertRevHistoryList(['rev-1-2', 'rev-1-1'],
                                  repo, 'rev-1-2')
        self.assertRevHistoryList(['rev-1-3', 'rev-1-2', 'rev-1-1'],
                                  repo, 'rev-1-3')
        self.assertRevHistoryList(['rev-2-2', 'rev-1-1'],
                                  repo, 'rev-2-2')
        self.assertRevHistoryList(['rev-2-3', 'rev-2-2', 'rev-1-1'],
                                  repo, 'rev-2-3')
        self.assertRevHistoryList(['rev-2-4', 'rev-2-3', 'rev-2-2', 'rev-1-1'],
                                  repo, 'rev-2-4')
        self.assertRevHistoryList(['rev-2-5', 'rev-2-4', 'rev-2-3', 'rev-2-2',
                                   'rev-1-1'], repo, 'rev-2-5')
