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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA


import sys

import bzrlib
from bzrlib import (
    errors,
    inventory,
    osutils,
    repository,
    versionedfile,
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
from bzrlib.tests.interrepository_implementations.test_interrepository import (
    check_repo_format_for_funky_id_on_win32
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
            # fetch with a limit of NULL_REVISION
            repo.fetch(tree_a.branch.repository,
                       revision_id=NULL_REVISION)
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

    def test_fetch_inconsistent_last_changed_entries(self):
        """If an inventory has odd data we should still get what it references.

        This test tests that we do fetch a file text created in a revision not
        being fetched, but referenced from the revision we are fetching when the
        adjacent revisions to the one being fetched do not reference that text.
        """
        tree = self.make_branch_and_tree('source')
        revid = tree.commit('old')
        to_repo = self.make_to_repository('to_repo')
        to_repo.fetch(tree.branch.repository, revid)
        # Make a broken revision and fetch it.
        source = tree.branch.repository
        source.lock_write()
        self.addCleanup(source.unlock)
        source.start_write_group()
        try:
            # We need two revisions: OLD and NEW. NEW will claim to need a file
            # 'FOO' changed in 'OLD'. OLD will not have that file at all.
            source.texts.insert_record_stream([
                versionedfile.FulltextContentFactory(('foo', revid), (), None,
                'contents')])
            basis = source.revision_tree(revid)
            parent_id = basis.path2id('')
            entry = inventory.make_entry('file', 'foo-path', parent_id, 'foo')
            entry.revision = revid
            entry.text_size = len('contents')
            entry.text_sha1 = osutils.sha_string('contents')
            inv_sha1, _ = source.add_inventory_by_delta(revid, [
                (None, 'foo-path', 'foo', entry)], 'new', [revid])
            rev = Revision(timestamp=0,
                           timezone=None,
                           committer="Foo Bar <foo@example.com>",
                           message="Message",
                           inventory_sha1=inv_sha1,
                           revision_id='new',
                           parent_ids=[revid])
            source.add_revision(rev.revision_id, rev)
        except:
            source.abort_write_group()
            raise
        else:
            source.commit_write_group()
        to_repo.fetch(source, 'new')
        to_repo.lock_read()
        self.addCleanup(to_repo.unlock)
        self.assertEqual('contents',
            to_repo.texts.get_record_stream([('foo', revid)],
            'unordered', True).next().get_bytes_as('fulltext'))

    def test_fetch_parent_inventories_at_stacking_boundary(self):
        """Fetch to a stacked branch copies inventories for parents of
        revisions at the stacking boundary.

        This is necessary so that the server is able to determine the file-ids
        altered by all revisions it contains, which means that it needs both
        the inventory for any revision it has, and the inventories of all that
        revision's parents.
        """
        to_repo = self.make_to_repository('to')
        if not to_repo._format.supports_external_lookups:
            raise TestNotApplicable("Need stacking support in the target.")
        builder = self.make_branch_builder('branch')
        builder.start_series()
        builder.build_snapshot('base', None, [
            ('add', ('', 'root-id', 'directory', ''))])
        builder.build_snapshot('left', ['base'], [])
        builder.build_snapshot('right', ['base'], [])
        builder.build_snapshot('merge', ['left', 'right'], [])
        builder.finish_series()
        branch = builder.get_branch()
        repo = self.make_to_repository('trunk')
        trunk = repo.bzrdir.create_branch()
        trunk.repository.fetch(branch.repository, 'left')
        trunk.repository.fetch(branch.repository, 'right')
        repo = self.make_to_repository('stacked')
        stacked_branch = repo.bzrdir.create_branch()
        stacked_branch.set_stacked_on_url(trunk.base)
        stacked_branch.repository.fetch(branch.repository, 'merge')
        unstacked_repo = stacked_branch.bzrdir.open_repository()
        unstacked_repo.lock_read()
        self.addCleanup(unstacked_repo.unlock)
        self.assertFalse(unstacked_repo.has_revision('left'))
        self.assertFalse(unstacked_repo.has_revision('right'))
        self.assertEqual(
            set([('left',), ('right',), ('merge',)]),
            unstacked_repo.inventories.keys())

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
        except (errors.BzrCheckError, errors.RevisionNotPresent), e:
            # If an exception is raised, the revision should not be in the
            # target.
            #
            # Can also just raise a generic check errors; stream insertion
            # does this to include all the missing data
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
