# Copyright (C) 2005, 2006, 2008 Canonical Ltd
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


import sys

import bzrlib
from bzrlib import (
    errors,
    repository,
    osutils,
    )
from bzrlib.errors import (
    NoSuchRevision,
    )
from bzrlib.revision import (
    NULL_REVISION,
    Revision,
    )
from bzrlib.tests import (
    TestNotApplicable,
    )
from bzrlib.tests.interrepository_implementations import (
    TestCaseWithInterRepository,
    )


class TestInterRepository(TestCaseWithInterRepository):

    def test_fetch(self):
        tree_a = self.make_branch_and_tree('a')
        self.build_tree(['a/foo'])
        tree_a.add('foo', 'file1')
        tree_a.commit('rev1', rev_id='rev1')
        def check_push_rev1(repo):
            # ensure the revision is missing.
            self.assertRaises(NoSuchRevision, repo.get_revision, 'rev1')
            # fetch with a limit of NULL_REVISION and an explicit progress bar.
            repo.fetch(tree_a.branch.repository,
                       revision_id=NULL_REVISION,
                       pb=bzrlib.progress.DummyProgress())
            # nothing should have been pushed
            self.assertFalse(repo.has_revision('rev1'))
            # fetch with a default limit (grab everything)
            repo.fetch(tree_a.branch.repository)
            # check that b now has all the data from a's first commit.
            rev = repo.get_revision('rev1')
            tree = repo.revision_tree('rev1')
            tree.lock_read()
            self.addCleanup(tree.unlock)
            tree.get_file_text('file1')
            for file_id in tree:
                if tree.inventory[file_id].kind == "file":
                    tree.get_file(file_id).read()

        # makes a target version repo 
        repo_b = self.make_to_repository('b')
        check_push_rev1(repo_b)

    def test_fetch_missing_basis_text(self):
        """If fetching a delta, we should die if a basis is not present."""
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/a'])
        tree.add(['a'], ['a-id'])
        tree.commit('one', rev_id='rev-one')
        self.build_tree_contents([('tree/a', 'new contents\n')])
        tree.commit('two', rev_id='rev-two')

        to_repo = self.make_to_repository('to_repo')
        # We build a broken revision so that we can test the fetch code dies
        # properly. So copy the inventory and revision, but not the text.
        to_repo.lock_write()
        try:
            to_repo.start_write_group()
            inv = tree.branch.repository.get_inventory('rev-one')
            to_repo.add_inventory('rev-one', inv, [])
            rev = tree.branch.repository.get_revision('rev-one')
            to_repo.add_revision('rev-one', rev, inv=inv)
            to_repo.commit_write_group()
        finally:
            to_repo.unlock()

        # Implementations can either ensure that the target of the delta is
        # reconstructable, or raise an exception (which stream based copies
        # generally do).
        try:
            to_repo.fetch(tree.branch.repository, 'rev-two')
        except errors.RevisionNotPresent, e:
            # If an exception is raised, the revision should not be in the
            # target.
            self.assertRaises((errors.NoSuchRevision, errors.RevisionNotPresent),
                              to_repo.revision_tree, 'rev-two')
        else:
            # If not exception is raised, then the text should be
            # available.
            to_repo.lock_read()
            try:
                rt = to_repo.revision_tree('rev-two')
                self.assertEqual('new contents\n',
                                 rt.get_file_text('a-id'))
            finally:
                to_repo.unlock()

    def test_fetch_missing_revision_same_location_fails(self):
        repo_a = self.make_repository('.')
        repo_b = repository.Repository.open('.')
        try:
            self.assertRaises(errors.NoSuchRevision, repo_b.fetch, repo_a, revision_id='XXX')
        except errors.LockError, e:
            check_old_format_lock_error(self.repository_format)

    def test_fetch_same_location_trivial_works(self):
        repo_a = self.make_repository('.')
        repo_b = repository.Repository.open('.')
        try:
            repo_a.fetch(repo_b)
        except errors.LockError, e:
            check_old_format_lock_error(self.repository_format)

    def test_fetch_missing_text_other_location_fails(self):
        source_tree = self.make_branch_and_tree('source')
        source = source_tree.branch.repository
        target = self.make_to_repository('target')
    
        # start by adding a file so the data knit for the file exists in
        # repositories that have specific files for each fileid.
        self.build_tree(['source/id'])
        source_tree.add(['id'], ['id'])
        source_tree.commit('a', rev_id='a')
        # now we manually insert a revision with an inventory referencing
        # 'id' at revision 'b', but we do not insert revision b.
        # this should ensure that the new versions of files are being checked
        # for during pull operations
        inv = source.get_inventory('a')
        source.lock_write()
        self.addCleanup(source.unlock)
        source.start_write_group()
        inv['id'].revision = 'b'
        inv.revision_id = 'b'
        sha1 = source.add_inventory('b', inv, ['a'])
        rev = Revision(timestamp=0,
                       timezone=None,
                       committer="Foo Bar <foo@example.com>",
                       message="Message",
                       inventory_sha1=sha1,
                       revision_id='b')
        rev.parent_ids = ['a']
        source.add_revision('b', rev)
        source.commit_write_group()
        self.assertRaises(errors.RevisionNotPresent, target.fetch, source)
        self.assertFalse(target.has_revision('b'))

    def test_fetch_funky_file_id(self):
        from_tree = self.make_branch_and_tree('tree')
        if sys.platform == 'win32':
            from_repo = from_tree.branch.repository
            check_repo_format_for_funky_id_on_win32(from_repo)
        self.build_tree(['tree/filename'])
        from_tree.add('filename', 'funky-chars<>%&;"\'')
        from_tree.commit('commit filename')
        to_repo = self.make_to_repository('to')
        to_repo.fetch(from_tree.branch.repository, from_tree.get_parent_ids()[0])

    def test_fetch_revision_hash(self):
        """Ensure that inventory hashes are updated by fetch"""
        from_tree = self.make_branch_and_tree('tree')
        from_tree.commit('foo', rev_id='foo-id')
        to_repo = self.make_to_repository('to')
        to_repo.fetch(from_tree.branch.repository)
        recorded_inv_sha1 = to_repo.get_inventory_sha1('foo-id')
        xml = to_repo.get_inventory_xml('foo-id')
        computed_inv_sha1 = osutils.sha_string(xml)
        self.assertEqual(computed_inv_sha1, recorded_inv_sha1)


class TestFetchDependentData(TestCaseWithInterRepository):

    def test_reference(self):
        from_tree = self.make_branch_and_tree('tree')
        to_repo = self.make_to_repository('to')
        if (not from_tree.supports_tree_reference() or
            not from_tree.branch.repository._format.supports_tree_reference or
            not to_repo._format.supports_tree_reference):
            raise TestNotApplicable("Need subtree support.")
        subtree = self.make_branch_and_tree('tree/subtree')
        subtree.commit('subrev 1')
        from_tree.add_reference(subtree)
        tree_rev = from_tree.commit('foo')
        # now from_tree has a last-modified of subtree of the rev id of the
        # commit for foo, and a reference revision of the rev id of the commit
        # for subrev 1
        to_repo.fetch(from_tree.branch.repository, tree_rev)
        # to_repo should have a file_graph for from_tree.path2id('subtree') and
        # revid tree_rev.
        file_id = from_tree.path2id('subtree')
        to_repo.lock_read()
        try:
            self.assertEqual({(file_id, tree_rev):()},
                to_repo.texts.get_parent_map([(file_id, tree_rev)]))
        finally:
            to_repo.unlock()
