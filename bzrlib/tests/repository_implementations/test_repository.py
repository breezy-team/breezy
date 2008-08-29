# Copyright (C) 2005, 2006, 2007 Canonical Ltd
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

"""Tests for bzrdir implementations - tests a bzrdir format."""

from cStringIO import StringIO
import re

import bzrlib
from bzrlib import (
    bzrdir,
    errors,
    graph,
    osutils,
    remote,
    repository,
    )
from bzrlib.delta import TreeDelta
from bzrlib.inventory import Inventory, InventoryDirectory
from bzrlib.repofmt.weaverepo import (
    RepositoryFormat5,
    RepositoryFormat6,
    RepositoryFormat7,
    )
from bzrlib.revision import NULL_REVISION, Revision
from bzrlib.smart import server
from bzrlib.symbol_versioning import one_two, one_three, one_four
from bzrlib.tests import (
    KnownFailure,
    TestCaseWithTransport,
    TestNotApplicable,
    TestSkipped,
    )
from bzrlib.tests.repository_implementations import TestCaseWithRepository
from bzrlib.transport import get_transport
from bzrlib.upgrade import upgrade
from bzrlib.workingtree import WorkingTree


class TestRepositoryMakeBranchAndTree(TestCaseWithRepository):

    def test_repository_format(self):
        # make sure the repository on tree.branch is of the desired format,
        # because developers use this api to setup the tree, branch and 
        # repository for their tests: having it now give the right repository
        # type would invalidate the tests.
        tree = self.make_branch_and_tree('repo')
        self.assertIsInstance(tree.branch.repository._format,
            self.repository_format.__class__)


class TestRepository(TestCaseWithRepository):

    def test_attribute__fetch_order(self):
        """Test the the _fetch_order attribute."""
        tree = self.make_branch_and_tree('tree')
        repo = tree.branch.repository
        self.assertTrue(repo._fetch_order in ('topological', 'unordered'))

    def test_attribute__fetch_uses_deltas(self):
        """Test the the _fetch_uses_deltas attribute."""
        tree = self.make_branch_and_tree('tree')
        repo = tree.branch.repository
        self.assertTrue(repo._fetch_uses_deltas in (True, False))

    def test_attribute__fetch_reconcile(self):
        """Test the the _fetch_reconcile attribute."""
        tree = self.make_branch_and_tree('tree')
        repo = tree.branch.repository
        self.assertTrue(repo._fetch_reconcile in (True, False))

    def test_attribute_inventories_store(self):
        """Test the existence of the inventories attribute."""
        tree = self.make_branch_and_tree('tree')
        repo = tree.branch.repository
        self.assertIsInstance(repo.inventories,
            bzrlib.versionedfile.VersionedFiles)

    def test_attribute_inventories_basics(self):
        """Test basic aspects of the inventories attribute."""
        tree = self.make_branch_and_tree('tree')
        repo = tree.branch.repository
        rev_id = (tree.commit('a'),)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual(set([rev_id]), set(repo.inventories.keys()))

    def test_attribute_revision_store(self):
        """Test the existence of the revisions attribute."""
        tree = self.make_branch_and_tree('tree')
        repo = tree.branch.repository
        self.assertIsInstance(repo.revisions,
            bzrlib.versionedfile.VersionedFiles)

    def test_attribute_revision_store_basics(self):
        """Test the basic behaviour of the revisions attribute."""
        tree = self.make_branch_and_tree('tree')
        repo = tree.branch.repository
        repo.lock_write()
        try:
            self.assertEqual(set(), set(repo.revisions.keys()))
            revid = (tree.commit("foo"),)
            self.assertEqual(set([revid]), set(repo.revisions.keys()))
            self.assertEqual({revid:()},
                repo.revisions.get_parent_map([revid]))
        finally:
            repo.unlock()
        tree2 = self.make_branch_and_tree('tree2')
        tree2.pull(tree.branch)
        left_id = (tree2.commit('left'),)
        right_id = (tree.commit('right'),)
        tree.merge_from_branch(tree2.branch)
        merge_id = (tree.commit('merged'),)
        repo.lock_read()
        self.addCleanup(repo.unlock)
        self.assertEqual(set([revid, left_id, right_id, merge_id]),
            set(repo.revisions.keys()))
        self.assertEqual({revid:(), left_id:(revid,), right_id:(revid,),
             merge_id:(right_id, left_id)},
            repo.revisions.get_parent_map(repo.revisions.keys()))

    def test_attribute_signature_store(self):
        """Test the existence of the signatures attribute."""
        tree = self.make_branch_and_tree('tree')
        repo = tree.branch.repository
        self.assertIsInstance(repo.signatures,
            bzrlib.versionedfile.VersionedFiles)

    def test_attribute_text_store_basics(self):
        """Test the basic behaviour of the text store."""
        tree = self.make_branch_and_tree('tree')
        repo = tree.branch.repository
        file_id = ("Foo:Bar",)
        tree.lock_write()
        try:
            self.assertEqual(set(), set(repo.texts.keys()))
            tree.add(['foo'], file_id, ['file'])
            tree.put_file_bytes_non_atomic(file_id[0], 'content\n')
            revid = (tree.commit("foo"),)
            if repo._format.rich_root_data:
                root_commit = (tree.get_root_id(),) + revid
                keys = set([root_commit])
                parents = {root_commit:()}
            else:
                keys = set()
                parents = {}
            keys.add(file_id + revid)
            parents[file_id + revid] = ()
            self.assertEqual(keys, set(repo.texts.keys()))
            self.assertEqual(parents,
                repo.texts.get_parent_map(repo.texts.keys()))
        finally:
            tree.unlock()
        tree2 = self.make_branch_and_tree('tree2')
        tree2.pull(tree.branch)
        tree2.put_file_bytes_non_atomic('Foo:Bar', 'right\n')
        right_id = (tree2.commit('right'),)
        keys.add(file_id + right_id)
        parents[file_id + right_id] = (file_id + revid,)
        tree.put_file_bytes_non_atomic('Foo:Bar', 'left\n')
        left_id = (tree.commit('left'),)
        keys.add(file_id + left_id)
        parents[file_id + left_id] = (file_id + revid,)
        tree.merge_from_branch(tree2.branch)
        tree.put_file_bytes_non_atomic('Foo:Bar', 'merged\n')
        try:
            tree.auto_resolve()
        except errors.UnsupportedOperation:
            pass
        merge_id = (tree.commit('merged'),)
        keys.add(file_id + merge_id)
        parents[file_id + merge_id] = (file_id + left_id, file_id + right_id)
        repo.lock_read()
        self.addCleanup(repo.unlock)
        self.assertEqual(keys, set(repo.texts.keys()))
        self.assertEqual(parents, repo.texts.get_parent_map(repo.texts.keys()))

    def test_attribute_text_store(self):
        """Test the existence of the texts attribute."""
        tree = self.make_branch_and_tree('tree')
        repo = tree.branch.repository
        self.assertIsInstance(repo.texts,
            bzrlib.versionedfile.VersionedFiles)

    def test_exposed_versioned_files_are_marked_dirty(self):
        repo = self.make_repository('.')
        repo.lock_write()
        signatures = repo.signatures
        revisions = repo.revisions
        inventories = repo.inventories
        repo.unlock()
        self.assertRaises(errors.ObjectNotLocked,
            signatures.keys)
        self.assertRaises(errors.ObjectNotLocked,
            revisions.keys)
        self.assertRaises(errors.ObjectNotLocked,
            inventories.keys)
        self.assertRaises(errors.ObjectNotLocked,
            signatures.add_lines, ('foo',), [], [])
        self.assertRaises(errors.ObjectNotLocked,
            revisions.add_lines, ('foo',), [], [])
        self.assertRaises(errors.ObjectNotLocked,
            inventories.add_lines, ('foo',), [], [])

    def test_clone_to_default_format(self):
        #TODO: Test that cloning a repository preserves all the information
        # such as signatures[not tested yet] etc etc.
        # when changing to the current default format.
        tree_a = self.make_branch_and_tree('a')
        self.build_tree(['a/foo'])
        tree_a.add('foo', 'file1')
        tree_a.commit('rev1', rev_id='rev1')
        bzrdirb = self.make_bzrdir('b')
        repo_b = tree_a.branch.repository.clone(bzrdirb)
        tree_b = repo_b.revision_tree('rev1')
        tree_b.lock_read()
        self.addCleanup(tree_b.unlock)
        tree_b.get_file_text('file1')
        rev1 = repo_b.get_revision('rev1')

    def test_iter_inventories_is_ordered(self):
        # just a smoke test
        tree = self.make_branch_and_tree('a')
        first_revision = tree.commit('')
        second_revision = tree.commit('')
        tree.lock_read()
        self.addCleanup(tree.unlock)
        revs = (first_revision, second_revision)
        invs = tree.branch.repository.iter_inventories(revs)
        for rev_id, inv in zip(revs, invs):
            self.assertEqual(rev_id, inv.revision_id)
            self.assertIsInstance(inv, Inventory)

    def test_supports_rich_root(self):
        tree = self.make_branch_and_tree('a')
        tree.commit('')
        second_revision = tree.commit('')
        inv = tree.branch.repository.revision_tree(second_revision).inventory
        rich_root = (inv.root.revision != second_revision)
        self.assertEqual(rich_root,
                         tree.branch.repository.supports_rich_root())

    def test_clone_specific_format(self):
        """todo"""

    def test_format_initialize_find_open(self):
        # loopback test to check the current format initializes to itself.
        if not self.repository_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            return
        # supported formats must be able to init and open
        t = get_transport(self.get_url())
        readonly_t = get_transport(self.get_readonly_url())
        made_control = self.bzrdir_format.initialize(t.base)
        made_repo = self.repository_format.initialize(made_control)
        self.assertEqual(made_control, made_repo.bzrdir)

        # find it via bzrdir opening:
        opened_control = bzrdir.BzrDir.open(readonly_t.base)
        direct_opened_repo = opened_control.open_repository()
        self.assertEqual(direct_opened_repo.__class__, made_repo.__class__)
        self.assertEqual(opened_control, direct_opened_repo.bzrdir)

        self.assertIsInstance(direct_opened_repo._format,
                              self.repository_format.__class__)
        # find it via Repository.open
        opened_repo = repository.Repository.open(readonly_t.base)
        self.failUnless(isinstance(opened_repo, made_repo.__class__))
        self.assertEqual(made_repo._format.__class__,
                         opened_repo._format.__class__)
        # if it has a unique id string, can we probe for it ?
        try:
            self.repository_format.get_format_string()
        except NotImplementedError:
            return
        self.assertEqual(self.repository_format,
                         repository.RepositoryFormat.find_format(opened_control))

    def test_create_repository(self):
        # bzrdir can construct a repository for itself.
        if not self.bzrdir_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            return
        t = get_transport(self.get_url())
        made_control = self.bzrdir_format.initialize(t.base)
        made_repo = made_control.create_repository()
        # Check that we have a repository object.
        made_repo.has_revision('foo')
        self.assertEqual(made_control, made_repo.bzrdir)
        
    def test_create_repository_shared(self):
        # bzrdir can construct a shared repository.
        if not self.bzrdir_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            return
        t = get_transport(self.get_url())
        made_control = self.bzrdir_format.initialize(t.base)
        try:
            made_repo = made_control.create_repository(shared=True)
        except errors.IncompatibleFormat:
            # not all repository formats understand being shared, or
            # may only be shared in some circumstances.
            return
        # Check that we have a repository object.
        made_repo.has_revision('foo')
        self.assertEqual(made_control, made_repo.bzrdir)
        self.assertTrue(made_repo.is_shared())

    def test_revision_tree(self):
        wt = self.make_branch_and_tree('.')
        wt.set_root_id('fixed-root')
        wt.commit('lala!', rev_id='revision-1', allow_pointless=True)
        tree = wt.branch.repository.revision_tree('revision-1')
        self.assertEqual('revision-1', tree.inventory.root.revision) 
        expected = InventoryDirectory('fixed-root', '', None)
        expected.revision = 'revision-1'
        self.assertEqual([('', 'V', 'directory', 'fixed-root', expected)],
                         list(tree.list_files(include_root=True)))
        tree = wt.branch.repository.revision_tree(None)
        self.assertEqual([], list(tree.list_files(include_root=True)))
        tree = wt.branch.repository.revision_tree(NULL_REVISION)
        self.assertEqual([], list(tree.list_files(include_root=True)))

    def test_get_revision_delta(self):
        tree_a = self.make_branch_and_tree('a')
        self.build_tree(['a/foo'])
        tree_a.add('foo', 'file1')
        tree_a.commit('rev1', rev_id='rev1')
        self.build_tree(['a/vla'])
        tree_a.add('vla', 'file2')
        tree_a.commit('rev2', rev_id='rev2')

        delta = tree_a.branch.repository.get_revision_delta('rev1')
        self.assertIsInstance(delta, TreeDelta)
        self.assertEqual([('foo', 'file1', 'file')], delta.added)
        delta = tree_a.branch.repository.get_revision_delta('rev2')
        self.assertIsInstance(delta, TreeDelta)
        self.assertEqual([('vla', 'file2', 'file')], delta.added)

    def test_clone_bzrdir_repository_revision(self):
        # make a repository with some revisions,
        # and clone it, this should not have unreferenced revisions.
        # also: test cloning with a revision id of NULL_REVISION -> empty repo.
        raise TestSkipped('revision limiting is not implemented yet.')

    def test_clone_repository_basis_revision(self):
        raise TestSkipped('the use of a basis should not add noise data to the result.')

    def test_clone_shared_no_tree(self):
        # cloning a shared repository keeps it shared
        # and preserves the make_working_tree setting.
        made_control = self.make_bzrdir('source')
        try:
            made_repo = made_control.create_repository(shared=True)
        except errors.IncompatibleFormat:
            # not all repository formats understand being shared, or
            # may only be shared in some circumstances.
            return
        try:
            made_repo.set_make_working_trees(False)
        except NotImplementedError:
            # the repository does not support having its tree-making flag
            # toggled.
            return
        result = made_control.clone(self.get_url('target'))
        # Check that we have a repository object.
        made_repo.has_revision('foo')

        self.assertEqual(made_control, made_repo.bzrdir)
        self.assertTrue(result.open_repository().is_shared())
        self.assertFalse(result.open_repository().make_working_trees())

    def test_upgrade_preserves_signatures(self):
        wt = self.make_branch_and_tree('source')
        wt.commit('A', allow_pointless=True, rev_id='A')
        repo = wt.branch.repository
        repo.lock_write()
        repo.start_write_group()
        repo.sign_revision('A', bzrlib.gpg.LoopbackGPGStrategy(None))
        repo.commit_write_group()
        repo.unlock()
        old_signature = repo.get_signature_text('A')
        try:
            old_format = bzrdir.BzrDirFormat.get_default_format()
            # This gives metadir branches something they can convert to.
            # it would be nice to have a 'latest' vs 'default' concept.
            format = bzrdir.format_registry.make_bzrdir('dirstate-with-subtree')
            upgrade(repo.bzrdir.root_transport.base, format=format)
        except errors.UpToDateFormat:
            # this is in the most current format already.
            return
        except errors.BadConversionTarget, e:
            raise TestSkipped(str(e))
        wt = WorkingTree.open(wt.basedir)
        new_signature = wt.branch.repository.get_signature_text('A')
        self.assertEqual(old_signature, new_signature)

    def test_format_description(self):
        repo = self.make_repository('.')
        text = repo._format.get_format_description()
        self.failUnless(len(text))

    def test_format_supports_external_lookups(self):
        repo = self.make_repository('.')
        self.assertSubset(
            [repo._format.supports_external_lookups], (True, False))

    def assertMessageRoundtrips(self, message):
        """Assert that message roundtrips to a repository and back intact."""
        tree = self.make_branch_and_tree('.')
        tree.commit(message, rev_id='a', allow_pointless=True)
        rev = tree.branch.repository.get_revision('a')
        # we have to manually escape this as we dont try to
        # roundtrip xml invalid characters at this point.
        # when escaping is moved to the serialiser, this test
        # can check against the literal message rather than
        # this escaped version.
        escaped_message, escape_count = re.subn(
            u'[^\x09\x0A\x0D\u0020-\uD7FF\uE000-\uFFFD]+',
            lambda match: match.group(0).encode('unicode_escape'),
            message)
        escaped_message= re.sub('\r', '\n', escaped_message)
        self.assertEqual(rev.message, escaped_message)
        # insist the class is unicode no matter what came in for 
        # consistency.
        self.assertIsInstance(rev.message, unicode)

    def test_commit_unicode_message(self):
        # a siple unicode message should be preserved
        self.assertMessageRoundtrips(u'foo bar gamm\xae plop')

    def test_commit_unicode_control_characters(self):
        # a unicode message with control characters should roundtrip too.
        self.assertMessageRoundtrips(
            "All 8-bit chars: " +  ''.join([unichr(x) for x in range(256)]))

    def test_check_repository(self):
        """Check a fairly simple repository's history"""
        tree = self.make_branch_and_tree('.')
        tree.commit('initial empty commit', rev_id='a-rev',
                    allow_pointless=True)
        result = tree.branch.repository.check()
        # writes to log; should accept both verbose or non-verbose
        result.report_results(verbose=True)
        result.report_results(verbose=False)

    def test_get_revisions(self):
        tree = self.make_branch_and_tree('.')
        tree.commit('initial empty commit', rev_id='a-rev',
                    allow_pointless=True)
        tree.commit('second empty commit', rev_id='b-rev',
                    allow_pointless=True)
        tree.commit('third empty commit', rev_id='c-rev',
                    allow_pointless=True)
        repo = tree.branch.repository
        revision_ids = ['a-rev', 'b-rev', 'c-rev']
        revisions = repo.get_revisions(revision_ids)
        self.assertEqual(len(revisions), 3)
        zipped = zip(revisions, revision_ids)
        self.assertEqual(len(zipped), 3)
        for revision, revision_id in zipped:
            self.assertEqual(revision.revision_id, revision_id)
            self.assertEqual(revision, repo.get_revision(revision_id))

    def test_root_entry_has_revision(self):
        tree = self.make_branch_and_tree('.')
        tree.commit('message', rev_id='rev_id')
        rev_tree = tree.branch.repository.revision_tree(tree.last_revision())
        self.assertEqual('rev_id', rev_tree.inventory.root.revision)

    def test_upgrade_from_format4(self):
        from bzrlib.tests.test_upgrade import _upgrade_dir_template
        if self.repository_format.get_format_description() \
            == "Repository format 4":
            raise TestSkipped('Cannot convert format-4 to itself')
        if isinstance(self.repository_format, remote.RemoteRepositoryFormat):
            return # local conversion to/from RemoteObjects is irrelevant.
        self.build_tree_contents(_upgrade_dir_template)
        old_repodir = bzrlib.bzrdir.BzrDir.open_unsupported('.')
        old_repo_format = old_repodir.open_repository()._format
        format = self.repository_format._matchingbzrdir
        try:
            format.repository_format = self.repository_format
        except AttributeError:
            pass
        upgrade('.', format)

    def test_pointless_commit(self):
        tree = self.make_branch_and_tree('.')
        self.assertRaises(errors.PointlessCommit, tree.commit, 'pointless',
                          allow_pointless=False)
        tree.commit('pointless', allow_pointless=True)

    def test_format_attributes(self):
        """All repository formats should have some basic attributes."""
        # create a repository to get a real format instance, not the 
        # template from the test suite parameterization.
        repo = self.make_repository('.')
        repo._format.rich_root_data
        repo._format.supports_tree_reference

    def test_get_serializer_format(self):
        repo = self.make_repository('.')
        format = repo.get_serializer_format()
        self.assertEqual(repo._serializer.format_num, format)

    def test_iter_files_bytes(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/file1', 'foo'),
                                  ('tree/file2', 'bar')])
        tree.add(['file1', 'file2'], ['file1-id', 'file2-id'])
        tree.commit('rev1', rev_id='rev1')
        self.build_tree_contents([('tree/file1', 'baz')])
        tree.commit('rev2', rev_id='rev2')
        repository = tree.branch.repository
        repository.lock_read()
        self.addCleanup(repository.unlock)
        extracted = dict((i, ''.join(b)) for i, b in
                         repository.iter_files_bytes(
                         [('file1-id', 'rev1', 'file1-old'),
                          ('file1-id', 'rev2', 'file1-new'),
                          ('file2-id', 'rev1', 'file2'),
                         ]))
        self.assertEqual('foo', extracted['file1-old'])
        self.assertEqual('bar', extracted['file2'])
        self.assertEqual('baz', extracted['file1-new'])
        self.assertRaises(errors.RevisionNotPresent, list,
                          repository.iter_files_bytes(
                          [('file1-id', 'rev3', 'file1-notpresent')]))
        self.assertRaises((errors.RevisionNotPresent, errors.NoSuchId), list,
                          repository.iter_files_bytes(
                          [('file3-id', 'rev3', 'file1-notpresent')]))

    def test_item_keys_introduced_by(self):
        # Make a repo with one revision and one versioned file.
        tree = self.make_branch_and_tree('t')
        self.build_tree(['t/foo'])
        tree.add('foo', 'file1')
        tree.commit('message', rev_id='rev_id')
        repo = tree.branch.repository
        repo.lock_read()
        self.addCleanup(repo.unlock)

        # Item keys will be in this order, for maximum convenience for
        # generating data to insert into knit repository:
        #   * files
        #   * inventory
        #   * signatures
        #   * revisions
        expected_item_keys = [
            ('file', 'file1', ['rev_id']),
            ('inventory', None, ['rev_id']),
            ('signatures', None, []),
            ('revisions', None, ['rev_id'])]
        item_keys = list(repo.item_keys_introduced_by(['rev_id']))
        item_keys = [
            (kind, file_id, list(versions))
            for (kind, file_id, versions) in item_keys]

        if repo.supports_rich_root():
            # Check for the root versioned file in the item_keys, then remove
            # it from streamed_names so we can compare that with
            # expected_record_names.
            # Note that the file keys can be in any order, so this test is
            # written to allow that.
            inv = repo.get_inventory('rev_id')
            root_item_key = ('file', inv.root.file_id, ['rev_id'])
            self.assertTrue(root_item_key in item_keys)
            item_keys.remove(root_item_key)

        self.assertEqual(expected_item_keys, item_keys)

    def test_get_graph(self):
        """Bare-bones smoketest that all repositories implement get_graph."""
        repo = self.make_repository('repo')
        repo.lock_read()
        self.addCleanup(repo.unlock)
        repo.get_graph()

    def test_graph_ghost_handling(self):
        tree = self.make_branch_and_tree('here')
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.commit('initial commit', rev_id='rev1')
        tree.add_parent_tree_id('ghost')
        tree.commit('commit-with-ghost', rev_id='rev2')
        graph = tree.branch.repository.get_graph()
        parents = graph.get_parent_map(['ghost', 'rev2'])
        self.assertTrue('ghost' not in parents)
        self.assertEqual(parents['rev2'], ('rev1', 'ghost'))

    def test_parent_map_type(self):
        tree = self.make_branch_and_tree('here')
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.commit('initial commit', rev_id='rev1')
        tree.commit('next commit', rev_id='rev2')
        graph = tree.branch.repository.get_graph()
        parents = graph.get_parent_map([NULL_REVISION, 'rev1', 'rev2'])
        for value in parents.values():
            self.assertIsInstance(value, tuple)

    def test_implements_revision_graph_can_have_wrong_parents(self):
        """All repositories should implement
        revision_graph_can_have_wrong_parents, so that check and reconcile can
        work correctly.
        """
        repo = self.make_repository('.')
        # This should work, not raise NotImplementedError:
        if not repo.revision_graph_can_have_wrong_parents():
            return
        repo.lock_read()
        self.addCleanup(repo.unlock)
        # This repo must also implement
        # _find_inconsistent_revision_parents and
        # _check_for_inconsistent_revision_parents.  So calling these
        # should not raise NotImplementedError.
        list(repo._find_inconsistent_revision_parents())
        repo._check_for_inconsistent_revision_parents()

    def test_add_signature_text(self):
        repo = self.make_repository('repo')
        repo.lock_write()
        self.addCleanup(repo.unlock)
        self.addCleanup(repo.commit_write_group)
        repo.start_write_group()
        inv = Inventory(revision_id='A')
        inv.root.revision = 'A'
        repo.add_inventory('A', inv, [])
        repo.add_revision('A', Revision('A', committer='A', timestamp=0,
                          inventory_sha1='', timezone=0, message='A'))
        repo.add_signature_text('A', 'This might be a signature')
        self.assertEqual('This might be a signature',
                         repo.get_signature_text('A'))

    def test_add_revision_inventory_sha1(self):
        repo = self.make_repository('repo')
        inv = Inventory(revision_id='A')
        inv.root.revision = 'A'
        inv.root.file_id = 'fixed-root'
        repo.lock_write()
        repo.start_write_group()
        repo.add_revision('A', Revision('A', committer='B', timestamp=0,
                          timezone=0, message='C'), inv=inv)
        repo.commit_write_group()
        repo.unlock()
        repo.lock_read()
        self.assertEquals(osutils.sha_string(
            repo._serializer.write_inventory_to_string(inv)),
            repo.get_revision('A').inventory_sha1)
        repo.unlock()

    def test_install_revisions(self):
        wt = self.make_branch_and_tree('source')
        wt.commit('A', allow_pointless=True, rev_id='A')
        repo = wt.branch.repository
        repo.lock_write()
        repo.start_write_group()
        repo.sign_revision('A', bzrlib.gpg.LoopbackGPGStrategy(None))
        repo.commit_write_group()
        repo.unlock()
        repo.lock_read()
        self.addCleanup(repo.unlock)
        repo2 = self.make_repository('repo2')
        revision = repo.get_revision('A')
        tree = repo.revision_tree('A')
        signature = repo.get_signature_text('A')
        repo2.lock_write()
        self.addCleanup(repo2.unlock)
        repository.install_revisions(repo2, [(revision, tree, signature)])
        self.assertEqual(revision, repo2.get_revision('A'))
        self.assertEqual(signature, repo2.get_signature_text('A'))

    # XXX: this helper duplicated from tests.test_repository
    def make_remote_repository(self, path):
        """Make a RemoteRepository object backed by a real repository that will
        be created at the given path."""
        repo = self.make_repository(path)
        smart_server = server.SmartTCPServer_for_testing()
        smart_server.setUp(self.get_server())
        remote_transport = get_transport(smart_server.get_url()).clone(path)
        self.addCleanup(smart_server.tearDown)
        remote_bzrdir = bzrdir.BzrDir.open_from_transport(remote_transport)
        remote_repo = remote_bzrdir.open_repository()
        return remote_repo

    def test_sprout_from_hpss_preserves_format(self):
        """repo.sprout from a smart server preserves the repository format."""
        if self.repository_format == RepositoryFormat7():
            raise TestNotApplicable(
                "Cannot fetch weaves over smart protocol.")
        remote_repo = self.make_remote_repository('remote')
        local_bzrdir = self.make_bzrdir('local')
        try:
            local_repo = remote_repo.sprout(local_bzrdir)
        except errors.TransportNotPossible:
            raise TestNotApplicable(
                "Cannot lock_read old formats like AllInOne over HPSS.")
        remote_backing_repo = bzrdir.BzrDir.open(
            self.get_vfs_only_url('remote')).open_repository()
        self.assertEqual(remote_backing_repo._format, local_repo._format)

    def test_sprout_branch_from_hpss_preserves_repo_format(self):
        """branch.sprout from a smart server preserves the repository format.
        """
        weave_formats = [RepositoryFormat5(), RepositoryFormat6(),
                         RepositoryFormat7()]
        if self.repository_format in weave_formats:
            raise TestNotApplicable(
                "Cannot fetch weaves over smart protocol.")
        remote_repo = self.make_remote_repository('remote')
        remote_branch = remote_repo.bzrdir.create_branch()
        try:
            local_bzrdir = remote_branch.bzrdir.sprout('local')
        except errors.TransportNotPossible:
            raise TestNotApplicable(
                "Cannot lock_read old formats like AllInOne over HPSS.")
        local_repo = local_bzrdir.open_repository()
        remote_backing_repo = bzrdir.BzrDir.open(
            self.get_vfs_only_url('remote')).open_repository()
        self.assertEqual(remote_backing_repo._format, local_repo._format)

    def test__make_parents_provider(self):
        """Repositories must have a _make_parents_provider method that returns
        an object with a get_parent_map method.
        """
        repo = self.make_repository('repo')
        repo._make_parents_provider().get_parent_map

    def make_repository_and_foo_bar(self, shared):
        made_control = self.make_bzrdir('repository')
        repo = made_control.create_repository(shared=shared)
        bzrdir.BzrDir.create_branch_convenience(self.get_url('repository/foo'),
                                                force_new_repo=False)
        bzrdir.BzrDir.create_branch_convenience(self.get_url('repository/bar'),
                                                force_new_repo=True)
        baz = self.make_bzrdir('repository/baz')
        qux = self.make_branch('repository/baz/qux')
        quxx = self.make_branch('repository/baz/qux/quxx')
        return repo

    def test_find_branches(self):
        repo = self.make_repository_and_foo_bar(shared=False)
        branches = repo.find_branches()
        self.assertContainsRe(branches[-1].base, 'repository/foo/$')
        self.assertContainsRe(branches[-3].base, 'repository/baz/qux/$')
        self.assertContainsRe(branches[-2].base, 'repository/baz/qux/quxx/$')
        # in some formats, creating a repo creates a branch
        if len(branches) == 6:
            self.assertContainsRe(branches[-4].base, 'repository/baz/$')
            self.assertContainsRe(branches[-5].base, 'repository/bar/$')
            self.assertContainsRe(branches[-6].base, 'repository/$')
        else:
            self.assertEqual(4, len(branches))
            self.assertContainsRe(branches[-4].base, 'repository/bar/$')

    def test_find_branches_using(self):
        try:
            repo = self.make_repository_and_foo_bar(shared=True)
        except errors.IncompatibleFormat:
            raise TestNotApplicable
        branches = repo.find_branches(using=True)
        self.assertContainsRe(branches[-1].base, 'repository/foo/$')
        # in some formats, creating a repo creates a branch
        if len(branches) == 2:
            self.assertContainsRe(branches[-2].base, 'repository/$')
        else:
            self.assertEqual(1, len(branches))

    def test_find_branches_using_standalone(self):
        branch = self.make_branch('branch')
        contained = self.make_branch('branch/contained')
        branches = branch.repository.find_branches(using=True)
        self.assertEqual([branch.base], [b.base for b in branches])
        branches = branch.repository.find_branches(using=False)
        self.assertEqual([branch.base, contained.base],
                         [b.base for b in branches])

    def test_find_branches_using_empty_standalone_repo(self):
        repo = self.make_repository('repo')
        self.assertFalse(repo.is_shared())
        try:
            repo.bzrdir.open_branch()
        except errors.NotBranchError:
            self.assertEqual([], repo.find_branches(using=True))
        else:
            self.assertEqual([repo.bzrdir.root_transport.base],
                             [b.base for b in repo.find_branches(using=True)])

    def test_set_get_make_working_trees_true(self):
        repo = self.make_repository('repo')
        try:
            repo.set_make_working_trees(True)
        except errors.RepositoryUpgradeRequired, e:
            raise TestNotApplicable('Format does not support this flag.')
        self.assertTrue(repo.make_working_trees())

    def test_set_get_make_working_trees_false(self):
        repo = self.make_repository('repo')
        try:
            repo.set_make_working_trees(False)
        except errors.RepositoryUpgradeRequired, e:
            raise TestNotApplicable('Format does not support this flag.')
        self.assertFalse(repo.make_working_trees())


class TestRepositoryLocking(TestCaseWithRepository):

    def test_leave_lock_in_place(self):
        repo = self.make_repository('r')
        # Lock the repository, then use leave_lock_in_place so that when we
        # unlock the repository the lock is still held on disk.
        token = repo.lock_write()
        try:
            if token is None:
                # This test does not apply, because this repository refuses lock
                # tokens.
                self.assertRaises(NotImplementedError, repo.leave_lock_in_place)
                return
            repo.leave_lock_in_place()
        finally:
            repo.unlock()
        # We should be unable to relock the repo.
        self.assertRaises(errors.LockContention, repo.lock_write)

    def test_dont_leave_lock_in_place(self):
        repo = self.make_repository('r')
        # Create a lock on disk.
        token = repo.lock_write()
        try:
            if token is None:
                # This test does not apply, because this repository refuses lock
                # tokens.
                self.assertRaises(NotImplementedError,
                                  repo.dont_leave_lock_in_place)
                return
            try:
                repo.leave_lock_in_place()
            except NotImplementedError:
                # This repository doesn't support this API.
                return
        finally:
            repo.unlock()
        # Reacquire the lock (with a different repository object) by using the
        # token.
        new_repo = repo.bzrdir.open_repository()
        new_repo.lock_write(token=token)
        # Call dont_leave_lock_in_place, so that the lock will be released by
        # this instance, even though the lock wasn't originally acquired by it.
        new_repo.dont_leave_lock_in_place()
        new_repo.unlock()
        # Now the repository is unlocked.  Test this by locking it (without a
        # token).
        repo.lock_write()
        repo.unlock()

    def test_lock_read_then_unlock(self):
        # Calling lock_read then unlocking should work without errors.
        repo = self.make_repository('r')
        repo.lock_read()
        repo.unlock()


class TestCaseWithComplexRepository(TestCaseWithRepository):

    def setUp(self):
        super(TestCaseWithComplexRepository, self).setUp()
        tree_a = self.make_branch_and_tree('a')
        self.bzrdir = tree_a.branch.bzrdir
        # add a corrupt inventory 'orphan'
        # this may need some generalising for knits.
        tree_a.lock_write()
        try:
            tree_a.branch.repository.start_write_group()
            try:
                inv_file = tree_a.branch.repository.inventories
                inv_file.add_lines(('orphan',), [], [])
            except:
                tree_a.branch.repository.commit_write_group()
                raise
            else:
                tree_a.branch.repository.abort_write_group()
        finally:
            tree_a.unlock()
        # add a real revision 'rev1'
        tree_a.commit('rev1', rev_id='rev1', allow_pointless=True)
        # add a real revision 'rev2' based on rev1
        tree_a.commit('rev2', rev_id='rev2', allow_pointless=True)
        # add a reference to a ghost
        tree_a.add_parent_tree_id('ghost1')
        try:
            tree_a.commit('rev3', rev_id='rev3', allow_pointless=True)
        except errors.RevisionNotPresent:
            raise TestNotApplicable("Cannot test with ghosts for this format.")
        # add another reference to a ghost, and a second ghost.
        tree_a.add_parent_tree_id('ghost1')
        tree_a.add_parent_tree_id('ghost2')
        tree_a.commit('rev4', rev_id='rev4', allow_pointless=True)

    def test_revision_trees(self):
        revision_ids = ['rev1', 'rev2', 'rev3', 'rev4']
        repository = self.bzrdir.open_repository()
        repository.lock_read()
        self.addCleanup(repository.unlock)
        trees1 = list(repository.revision_trees(revision_ids))
        trees2 = [repository.revision_tree(t) for t in revision_ids]
        self.assertEqual(len(trees1), len(trees2))
        for tree1, tree2 in zip(trees1, trees2):
            self.assertFalse(tree2.changes_from(tree1).has_changed())

    def test_get_deltas_for_revisions(self):
        repository = self.bzrdir.open_repository()
        repository.lock_read()
        self.addCleanup(repository.unlock)
        revisions = [repository.get_revision(r) for r in 
                     ['rev1', 'rev2', 'rev3', 'rev4']]
        deltas1 = list(repository.get_deltas_for_revisions(revisions))
        deltas2 = [repository.get_revision_delta(r.revision_id) for r in
                   revisions]
        self.assertEqual(deltas1, deltas2)

    def test_all_revision_ids(self):
        # all_revision_ids -> all revisions
        self.assertEqual(set(['rev1', 'rev2', 'rev3', 'rev4']),
            set(self.bzrdir.open_repository().all_revision_ids()))

    def test_get_ancestry_missing_revision(self):
        # get_ancestry(revision that is in some data but not fully installed
        # -> NoSuchRevision
        self.assertRaises(errors.NoSuchRevision,
                          self.bzrdir.open_repository().get_ancestry, 'orphan')

    def test_get_unordered_ancestry(self):
        repo = self.bzrdir.open_repository()
        self.assertEqual(set(repo.get_ancestry('rev3')),
                         set(repo.get_ancestry('rev3', topo_sorted=False)))

    def test_reserved_id(self):
        repo = self.make_repository('repository')
        repo.lock_write()
        repo.start_write_group()
        try:
            self.assertRaises(errors.ReservedId, repo.add_inventory, 'reserved:',
                              None, None)
            self.assertRaises(errors.ReservedId, repo.add_revision, 'reserved:',
                              None)
        finally:
            repo.abort_write_group()
            repo.unlock()


class TestCaseWithCorruptRepository(TestCaseWithRepository):

    def setUp(self):
        super(TestCaseWithCorruptRepository, self).setUp()
        # a inventory with no parents and the revision has parents..
        # i.e. a ghost.
        repo = self.make_repository('inventory_with_unnecessary_ghost')
        repo.lock_write()
        repo.start_write_group()
        inv = Inventory(revision_id = 'ghost')
        inv.root.revision = 'ghost'
        sha1 = repo.add_inventory('ghost', inv, [])
        rev = bzrlib.revision.Revision(timestamp=0,
                                       timezone=None,
                                       committer="Foo Bar <foo@example.com>",
                                       message="Message",
                                       inventory_sha1=sha1,
                                       revision_id='ghost')
        rev.parent_ids = ['the_ghost']
        try:
            repo.add_revision('ghost', rev)
        except (errors.NoSuchRevision, errors.RevisionNotPresent):
            raise TestNotApplicable("Cannot test with ghosts for this format.")
         
        inv = Inventory(revision_id = 'the_ghost')
        inv.root.revision = 'the_ghost'
        sha1 = repo.add_inventory('the_ghost', inv, [])
        rev = bzrlib.revision.Revision(timestamp=0,
                                       timezone=None,
                                       committer="Foo Bar <foo@example.com>",
                                       message="Message",
                                       inventory_sha1=sha1,
                                       revision_id='the_ghost')
        rev.parent_ids = []
        repo.add_revision('the_ghost', rev)
        # check its setup usefully
        inv_weave = repo.inventories
        possible_parents = (None, (('ghost',),))
        self.assertSubset(inv_weave.get_parent_map([('ghost',)])[('ghost',)],
            possible_parents)
        repo.commit_write_group()
        repo.unlock()

    def test_corrupt_revision_access_asserts_if_reported_wrong(self):
        repo_url = self.get_url('inventory_with_unnecessary_ghost')
        repo = repository.Repository.open(repo_url)
        reported_wrong = False
        try:
            if repo.get_ancestry('ghost') != [None, 'the_ghost', 'ghost']:
                reported_wrong = True
        except errors.CorruptRepository:
            # caught the bad data:
            return
        if not reported_wrong:
            return
        self.assertRaises(errors.CorruptRepository, repo.get_revision, 'ghost')

    def test_corrupt_revision_get_revision_reconcile(self):
        repo_url = self.get_url('inventory_with_unnecessary_ghost')
        repo = repository.Repository.open(repo_url)
        repo.get_revision_reconcile('ghost')


# FIXME: document why this is a TestCaseWithTransport rather than a
#        TestCaseWithRepository
class TestEscaping(TestCaseWithTransport):
    """Test that repositories can be stored correctly on VFAT transports.
    
    Makes sure we have proper escaping of invalid characters, etc.

    It'd be better to test all operations on the FakeVFATTransportDecorator,
    but working trees go straight to the os not through the Transport layer.
    Therefore we build some history first in the regular way and then 
    check it's safe to access for vfat.
    """

    def test_on_vfat(self):
        # dont bother with remote repository testing, because this test is
        # about local disk layout/support.
        from bzrlib.remote import RemoteRepositoryFormat
        if isinstance(self.repository_format, RemoteRepositoryFormat):
            return
        FOO_ID = 'foo<:>ID'
        REV_ID = 'revid-1' 
        # this makes a default format repository always, which is wrong: 
        # it should be a TestCaseWithRepository in order to get the 
        # default format.
        wt = self.make_branch_and_tree('repo')
        self.build_tree(["repo/foo"], line_endings='binary')
        # add file with id containing wierd characters
        wt.add(['foo'], [FOO_ID])
        wt.commit('this is my new commit', rev_id=REV_ID)
        # now access over vfat; should be safe
        branch = bzrdir.BzrDir.open('vfat+' + self.get_url('repo')).open_branch()
        revtree = branch.repository.revision_tree(REV_ID)
        revtree.lock_read()
        self.addCleanup(revtree.unlock)
        contents = revtree.get_file_text(FOO_ID)
        self.assertEqual(contents, 'contents of repo/foo\n')

    def test_create_bundle(self):
        wt = self.make_branch_and_tree('repo')
        self.build_tree(['repo/file1'])
        wt.add('file1')
        wt.commit('file1', rev_id='rev1')
        fileobj = StringIO()
        wt.branch.repository.create_bundle('rev1', NULL_REVISION, fileobj)
