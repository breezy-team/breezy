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
    repository,
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
        tree_a = self.make_branch_and_tree('a')
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
        rev1_tree.lock_read()
        try:
            lines = rev1_tree.get_file_lines(rev1_tree.get_root_id())
        finally:
            rev1_tree.unlock()
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

    def test_fetch_all_from_self(self):
        tree = self.make_branch_and_tree('.')
        rev_id = tree.commit('one')
        # This needs to be a new copy of the repository, if this changes, the
        # test needs to be rewritten
        repo = tree.branch.repository.bzrdir.open_repository()
        # This fetch should be a no-op see bug #158333
        tree.branch.repository.fetch(repo, None)

    def test_fetch_from_self(self):
        tree = self.make_branch_and_tree('.')
        rev_id = tree.commit('one')
        repo = tree.branch.repository.bzrdir.open_repository()
        # This fetch should be a no-op see bug #158333
        tree.branch.repository.fetch(repo, rev_id)

    def test_fetch_missing_from_self(self):
        tree = self.make_branch_and_tree('.')
        rev_id = tree.commit('one')
        # Even though the fetch() is a NO-OP it should assert the revision id
        # is present
        repo = tree.branch.repository.bzrdir.open_repository()
        self.assertRaises(errors.NoSuchRevision, tree.branch.repository.fetch,
                          repo, 'no-such-revision')

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

    def make_repository_with_one_revision(self):
        wt = self.make_branch_and_tree('source')
        wt.commit('rev1', allow_pointless=True, rev_id='rev1')
        return wt.branch.repository

    def test_fetch_revision_already_exists(self):
        # Make a repository with one revision.
        source_repo = self.make_repository_with_one_revision()
        # Fetch that revision into a second repository.
        target_repo = self.make_repository('target')
        target_repo.fetch(source_repo, revision_id='rev1')
        # Now fetch again; there will be nothing to do.  This should work
        # without causing any errors.
        target_repo.fetch(source_repo, revision_id='rev1')

    def test_fetch_all_same_revisions_twice(self):
        # Blind-fetching all the same revisions twice should succeed and be a
        # no-op the second time.
        repo = self.make_repository('repo')
        tree = self.make_branch_and_tree('tree')
        revision_id = tree.commit('test')
        repo.fetch(tree.branch.repository)
        repo.fetch(tree.branch.repository)
