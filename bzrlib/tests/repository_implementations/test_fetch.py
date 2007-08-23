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

"""Tests for fetch between repositories of the same type."""

from bzrlib import (
    bzrdir,
    errors,
    gpg,
    )
from bzrlib.tests import TestSkipped
from bzrlib.tests.repository_implementations import TestCaseWithRepository
from bzrlib.transport import get_transport


class TestFetchSameRepository(TestCaseWithRepository):

    def test_fetch(self):
        # smoke test fetch to ensure that the convenience function works.
        # it is defined as a convenience function with the underlying 
        # functionality provided by an InterRepository
        tree_a = self.make_branch_and_tree('a')
        self.build_tree(['a/foo'])
        tree_a.add('foo', 'file1')
        tree_a.commit('rev1', rev_id='rev1')
        # fetch with a default limit (grab everything)
        repo = self.make_repository('b')
        if (tree_a.branch.repository.supports_rich_root() and not
            repo.supports_rich_root()):
            raise TestSkipped('Cannot fetch from model2 to model1')
        repo.fetch(tree_a.branch.repository,
                   revision_id=None)
                   ## pb=bzrlib.progress.DummyProgress())

    def test_fetch_knit3(self):
        # create a repository of the sort we are testing.
        tree_a = self.make_branch_and_tree('a', '')
        self.build_tree(['a/foo'])
        tree_a.add('foo', 'file1')
        tree_a.commit('rev1', rev_id='rev1')
        # create a knit-3 based format to fetch into
        f = bzrdir.format_registry.make_bzrdir('dirstate-with-subtree')
        try:
            format = tree_a.branch.repository._format
            format.check_conversion_target(f.repository_format)
            # if we cannot convert data to knit3, skip the test.
        except errors.BadConversionTarget, e:
            raise TestSkipped(str(e))
        self.get_transport().mkdir('b')
        b_bzrdir = f.initialize(self.get_url('b'))
        knit3_repo = b_bzrdir.create_repository()
        # fetch with a default limit (grab everything)
        knit3_repo.fetch(tree_a.branch.repository, revision_id=None)
        # Reopen to avoid any in-memory caching - ensure its reading from
        # disk.
        knit3_repo = b_bzrdir.open_repository()
        rev1_tree = knit3_repo.revision_tree('rev1')
        lines = rev1_tree.get_file_lines(rev1_tree.inventory.root.file_id)
        self.assertEqual([], lines)
        b_branch = b_bzrdir.create_branch()
        b_branch.pull(tree_a.branch)
        try:
            tree_b = b_bzrdir.create_workingtree()
        except errors.NotLocalUrl:
            raise TestSkipped("cannot make working tree with transport %r"
                              % b_bzrdir.transport)
        tree_b.commit('no change', rev_id='rev2')
        rev2_tree = knit3_repo.revision_tree('rev2')
        self.assertEqual('rev1', rev2_tree.inventory.root.revision)

    def makeARepoWithSignatures(self):
        wt = self.make_branch_and_tree('a-repo-with-sigs')
        wt.commit('rev1', allow_pointless=True, rev_id='rev1')
        repo = wt.branch.repository
        repo.lock_write()
        repo.start_write_group()
        repo.sign_revision('rev1', gpg.LoopbackGPGStrategy(None))
        repo.commit_write_group()
        repo.unlock()
        return repo

    def test_fetch_copies_signatures(self):
        source_repo = self.makeARepoWithSignatures()
        target_repo = self.make_repository('target')
        target_repo.fetch(source_repo, revision_id=None)
        self.assertEqual(
            source_repo.get_signature_text('rev1'),
            target_repo.get_signature_text('rev1'))
