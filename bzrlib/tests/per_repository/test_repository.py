# Copyright (C) 2006-2011 Canonical Ltd
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

"""Tests for repository implementations - tests a repository format."""

from cStringIO import StringIO
import re

from bzrlib import (
    branch as _mod_branch,
    controldir,
    delta as _mod_delta,
    errors,
    gpg,
    info,
    inventory,
    remote,
    repository,
    revision as _mod_revision,
    tests,
    transport,
    upgrade,
    workingtree,
    )
from bzrlib.repofmt import (
    knitpack_repo,
    )
from bzrlib.tests import (
    per_repository,
    test_server,
    )
from bzrlib.tests.matchers import *


class TestRepositoryMakeBranchAndTree(per_repository.TestCaseWithRepository):

    def test_repository_format(self):
        # make sure the repository on tree.branch is of the desired format,
        # because developers use this api to setup the tree, branch and
        # repository for their tests: having it now give the right repository
        # type would invalidate the tests.
        tree = self.make_branch_and_tree('repo')
        self.assertIsInstance(tree.branch.repository._format,
            self.repository_format.__class__)


class TestRepository(per_repository.TestCaseWithRepository):

    def assertFormatAttribute(self, attribute, allowed_values):
        """Assert that the format has an attribute 'attribute'."""
        repo = self.make_repository('repo')
        self.assertSubset([getattr(repo._format, attribute)], allowed_values)

    def test_attribute_fast_deltas(self):
        """Test the format.fast_deltas attribute."""
        self.assertFormatAttribute('fast_deltas', (True, False))

    def test_attribute_supports_nesting_repositories(self):
        """Test the format.supports_nesting_repositories."""
        self.assertFormatAttribute('supports_nesting_repositories',
            (True, False))

    def test_attribute_supports_unreferenced_revisions(self):
        """Test the format.supports_unreferenced_revisions."""
        self.assertFormatAttribute('supports_unreferenced_revisions',
            (True, False))

    def test_attribute__fetch_reconcile(self):
        """Test the _fetch_reconcile attribute."""
        self.assertFormatAttribute('_fetch_reconcile', (True, False))

    def test_attribute_format_experimental(self):
        self.assertFormatAttribute('experimental', (True, False))

    def test_attribute_format_pack_compresses(self):
        self.assertFormatAttribute('pack_compresses', (True, False))

    def test_attribute_format_supports_full_versioned_files(self):
        self.assertFormatAttribute('supports_full_versioned_files',
            (True, False))

    def test_attribute_format_supports_funky_characters(self):
        self.assertFormatAttribute('supports_funky_characters',
            (True, False))

    def test_attribute_format_supports_leaving_lock(self):
        self.assertFormatAttribute('supports_leaving_lock',
            (True, False))

    def test_attribute_format_versioned_directories(self):
        self.assertFormatAttribute('supports_versioned_directories', (True, False))

    def test_attribute_format_revision_graph_can_have_wrong_parents(self):
        self.assertFormatAttribute('revision_graph_can_have_wrong_parents',
            (True, False))

    def test_format_is_deprecated(self):
        repo = self.make_repository('repo')
        self.assertSubset([repo._format.is_deprecated()], (True, False))

    def test_format_is_supported(self):
        repo = self.make_repository('repo')
        self.assertSubset([repo._format.is_supported()], (True, False))

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

    def test_supports_rich_root(self):
        tree = self.make_branch_and_tree('a')
        tree.commit('')
        second_revision = tree.commit('')
        rev_tree = tree.branch.repository.revision_tree(second_revision)
        rev_tree.lock_read()
        self.addCleanup(rev_tree.unlock)
        root_revision = rev_tree.get_file_revision(rev_tree.get_root_id())
        rich_root = (root_revision != second_revision)
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
        t = self.get_transport()
        readonly_t = self.get_readonly_transport()
        made_control = self.bzrdir_format.initialize(t.base)
        made_repo = self.repository_format.initialize(made_control)
        self.assertEqual(made_control, made_repo.bzrdir)

        # find it via controldir opening:
        opened_control = controldir.ControlDir.open(readonly_t.base)
        direct_opened_repo = opened_control.open_repository()
        self.assertEqual(direct_opened_repo.__class__, made_repo.__class__)
        self.assertEqual(opened_control, direct_opened_repo.bzrdir)

        self.assertIsInstance(direct_opened_repo._format,
                              self.repository_format.__class__)
        # find it via Repository.open
        opened_repo = repository.Repository.open(readonly_t.base)
        self.assertIsInstance(opened_repo, made_repo.__class__)
        self.assertEqual(made_repo._format.__class__,
                         opened_repo._format.__class__)
        # if it has a unique id string, can we probe for it ?
        try:
            self.repository_format.get_format_string()
        except NotImplementedError:
            return
        self.assertEqual(self.repository_format,
             repository.RepositoryFormatMetaDir.find_format(opened_control))

    def test_format_matchingbzrdir(self):
        self.assertEqual(self.repository_format,
            self.repository_format._matchingbzrdir.repository_format)
        self.assertEqual(self.repository_format,
            self.bzrdir_format.repository_format)

    def test_format_network_name(self):
        repo = self.make_repository('r')
        format = repo._format
        network_name = format.network_name()
        self.assertIsInstance(network_name, str)
        # We want to test that the network_name matches the actual format on
        # disk.  For local repositories, that means that using network_name as
        # a key in the registry gives back the same format.  For remote
        # repositories, that means that the network_name of the
        # RemoteRepositoryFormat we have locally matches the actual format
        # present on the remote side.
        if isinstance(format, remote.RemoteRepositoryFormat):
            repo._ensure_real()
            real_repo = repo._real_repository
            self.assertEqual(real_repo._format.network_name(), network_name)
        else:
            registry = repository.network_format_registry
            looked_up_format = registry.get(network_name)
            self.assertEqual(format.__class__, looked_up_format.__class__)

    def test_create_repository(self):
        # bzrdir can construct a repository for itself.
        if not self.bzrdir_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            return
        t = self.get_transport()
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
        t = self.get_transport()
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
        tree.lock_read()
        try:
            self.assertEqual('revision-1',
                tree.get_file_revision(tree.get_root_id()))
            expected = inventory.InventoryDirectory('fixed-root', '', None)
            expected.revision = 'revision-1'
            self.assertEqual([('', 'V', 'directory', 'fixed-root', expected)],
                             list(tree.list_files(include_root=True)))
        finally:
            tree.unlock()
        tree = self.callDeprecated(['NULL_REVISION should be used for the null'
            ' revision instead of None, as of bzr 0.91.'],
            wt.branch.repository.revision_tree, None)
        tree.lock_read()
        try:
            self.assertEqual([], list(tree.list_files(include_root=True)))
        finally:
            tree.unlock()
        tree = wt.branch.repository.revision_tree(_mod_revision.NULL_REVISION)
        tree.lock_read()
        try:
            self.assertEqual([], list(tree.list_files(include_root=True)))
        finally:
            tree.unlock()

    def test_get_revision_delta(self):
        tree_a = self.make_branch_and_tree('a')
        self.build_tree(['a/foo'])
        tree_a.add('foo', 'file1')
        tree_a.commit('rev1', rev_id='rev1')
        self.build_tree(['a/vla'])
        tree_a.add('vla', 'file2')
        tree_a.commit('rev2', rev_id='rev2')

        delta = tree_a.branch.repository.get_revision_delta('rev1')
        self.assertIsInstance(delta, _mod_delta.TreeDelta)
        self.assertEqual([('foo', 'file1', 'file')], delta.added)
        delta = tree_a.branch.repository.get_revision_delta('rev2')
        self.assertIsInstance(delta, _mod_delta.TreeDelta)
        self.assertEqual([('vla', 'file2', 'file')], delta.added)

    def test_clone_bzrdir_repository_revision(self):
        # make a repository with some revisions,
        # and clone it, this should not have unreferenced revisions.
        # also: test cloning with a revision id of NULL_REVISION -> empty repo.
        raise tests.TestSkipped('revision limiting is not implemented yet.')

    def test_clone_repository_basis_revision(self):
        raise tests.TestSkipped(
            'the use of a basis should not add noise data to the result.')

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
        except errors.UnsupportedOperation:
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
        if not self.repository_format.supports_revision_signatures:
            raise tests.TestNotApplicable(
                "repository does not support signing revisions")
        wt = self.make_branch_and_tree('source')
        wt.commit('A', allow_pointless=True, rev_id='A')
        repo = wt.branch.repository
        repo.lock_write()
        repo.start_write_group()
        try:
            repo.sign_revision('A', gpg.LoopbackGPGStrategy(None))
        except errors.UnsupportedOperation:
            self.assertFalse(repo._format.supports_revision_signatures)
            raise tests.TestNotApplicable("signatures not supported by repository format")
        repo.commit_write_group()
        repo.unlock()
        old_signature = repo.get_signature_text('A')
        try:
            old_format = controldir.ControlDirFormat.get_default_format()
            # This gives metadir branches something they can convert to.
            # it would be nice to have a 'latest' vs 'default' concept.
            format = controldir.format_registry.make_bzrdir(
                'development-subtree')
            upgrade.upgrade(repo.bzrdir.root_transport.base, format=format)
        except errors.UpToDateFormat:
            # this is in the most current format already.
            return
        except errors.BadConversionTarget, e:
            raise tests.TestSkipped(str(e))
        wt = workingtree.WorkingTree.open(wt.basedir)
        new_signature = wt.branch.repository.get_signature_text('A')
        self.assertEqual(old_signature, new_signature)

    def test_format_description(self):
        repo = self.make_repository('.')
        text = repo._format.get_format_description()
        self.assertTrue(len(text))

    def test_format_supports_external_lookups(self):
        repo = self.make_repository('.')
        self.assertSubset(
            [repo._format.supports_external_lookups], (True, False))

    def assertMessageRoundtrips(self, message):
        """Assert that message roundtrips to a repository and back intact."""
        tree = self.make_branch_and_tree('.')
        tree.commit(message, rev_id='a', allow_pointless=True)
        rev = tree.branch.repository.get_revision('a')
        serializer = getattr(tree.branch.repository, "_serializer", None)
        if serializer is not None and serializer.squashes_xml_invalid_characters:
            # we have to manually escape this as we dont try to
            # roundtrip xml invalid characters in the xml-based serializers.
            escaped_message, escape_count = re.subn(
                u'[^\x09\x0A\x0D\u0020-\uD7FF\uE000-\uFFFD]+',
                lambda match: match.group(0).encode('unicode_escape'),
                message)
            self.assertEqual(rev.message, escaped_message)
        else:
            self.assertEqual(rev.message, message)
        # insist the class is unicode no matter what came in for
        # consistency.
        self.assertIsInstance(rev.message, unicode)

    def test_commit_unicode_message(self):
        # a siple unicode message should be preserved
        self.assertMessageRoundtrips(u'foo bar gamm\xae plop')

    def test_commit_unicode_control_characters(self):
        # a unicode message with control characters should roundtrip too.
        unichars = [unichr(x) for x in range(256)]
        # '\r' is not directly allowed anymore, as it used to be translated
        # into '\n' anyway
        unichars[ord('\r')] = u'\n'
        self.assertMessageRoundtrips(
            u"All 8-bit chars: " +  ''.join(unichars))

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
        rev_tree.lock_read()
        self.addCleanup(rev_tree.unlock)
        root_id = rev_tree.get_root_id()
        self.assertEqual('rev_id', rev_tree.get_file_revision(root_id))

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

    def test_get_known_graph_ancestry(self):
        tree = self.make_branch_and_tree('here')
        tree.lock_write()
        self.addCleanup(tree.unlock)
        # A
        # |\
        # | B
        # |/
        # C
        tree.commit('initial commit', rev_id='A')
        tree_other = tree.bzrdir.sprout('there').open_workingtree()
        tree_other.commit('another', rev_id='B')
        tree.merge_from_branch(tree_other.branch)
        tree.commit('another', rev_id='C')
        kg = tree.branch.repository.get_known_graph_ancestry(
            ['C'])
        self.assertEqual(['C'], list(kg.heads(['A', 'B', 'C'])))
        self.assertEqual(['A', 'B', 'C'], list(kg.topo_sort()))

    def test_parent_map_type(self):
        tree = self.make_branch_and_tree('here')
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.commit('initial commit', rev_id='rev1')
        tree.commit('next commit', rev_id='rev2')
        graph = tree.branch.repository.get_graph()
        parents = graph.get_parent_map(
            [_mod_revision.NULL_REVISION, 'rev1', 'rev2'])
        for value in parents.values():
            self.assertIsInstance(value, tuple)

    def test_implements_revision_graph_can_have_wrong_parents(self):
        """All repositories should implement
        revision_graph_can_have_wrong_parents, so that check and reconcile can
        work correctly.
        """
        repo = self.make_repository('.')
        # This should work, not raise NotImplementedError:
        if not repo._format.revision_graph_can_have_wrong_parents:
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
        builder = self.make_branch_builder('.')
        builder.start_series()
        builder.build_snapshot('A', None, [
            ('add', ('', 'root-id', 'directory', None))])
        builder.finish_series()
        b = builder.get_branch()
        b.lock_write()
        self.addCleanup(b.unlock)
        if b.repository._format.supports_revision_signatures:
            b.repository.start_write_group()
            b.repository.add_signature_text('A', 'This might be a signature')
            b.repository.commit_write_group()
            self.assertEqual('This might be a signature',
                             b.repository.get_signature_text('A'))
        else:
            b.repository.start_write_group()
            self.addCleanup(b.repository.abort_write_group)
            self.assertRaises(errors.UnsupportedOperation,
                b.repository.add_signature_text, 'A',
                'This might be a signature')

    # XXX: this helper duplicated from tests.test_repository
    def make_remote_repository(self, path, shared=None):
        """Make a RemoteRepository object backed by a real repository that will
        be created at the given path."""
        repo = self.make_repository(path, shared=shared)
        smart_server = test_server.SmartTCPServer_for_testing()
        self.start_server(smart_server, self.get_server())
        remote_transport = transport.get_transport_from_url(
            smart_server.get_url()).clone(path)
        if not repo.bzrdir._format.supports_transport(remote_transport):
            raise tests.TestNotApplicable(
                "format does not support transport")
        remote_bzrdir = controldir.ControlDir.open_from_transport(
            remote_transport)
        remote_repo = remote_bzrdir.open_repository()
        return remote_repo

    def test_sprout_from_hpss_preserves_format(self):
        """repo.sprout from a smart server preserves the repository format."""
        remote_repo = self.make_remote_repository('remote')
        local_bzrdir = self.make_bzrdir('local')
        try:
            local_repo = remote_repo.sprout(local_bzrdir)
        except errors.TransportNotPossible:
            raise tests.TestNotApplicable(
                "Cannot lock_read old formats like AllInOne over HPSS.")
        remote_backing_repo = controldir.ControlDir.open(
            self.get_vfs_only_url('remote')).open_repository()
        self.assertEqual(
            remote_backing_repo._format.network_name(),
            local_repo._format.network_name())

    def test_sprout_branch_from_hpss_preserves_repo_format(self):
        """branch.sprout from a smart server preserves the repository format.
        """
        if not self.repository_format.supports_leaving_lock:
            raise tests.TestNotApplicable(
                "Format can not be used over HPSS")
        remote_repo = self.make_remote_repository('remote')
        remote_branch = remote_repo.bzrdir.create_branch()
        try:
            local_bzrdir = remote_branch.bzrdir.sprout('local')
        except errors.TransportNotPossible:
            raise tests.TestNotApplicable(
                "Cannot lock_read old formats like AllInOne over HPSS.")
        local_repo = local_bzrdir.open_repository()
        remote_backing_repo = controldir.ControlDir.open(
            self.get_vfs_only_url('remote')).open_repository()
        self.assertEqual(remote_backing_repo._format, local_repo._format)

    def test_sprout_branch_from_hpss_preserves_shared_repo_format(self):
        """branch.sprout from a smart server preserves the repository format of
        a branch from a shared repository.
        """
        if not self.repository_format.supports_leaving_lock:
            raise tests.TestNotApplicable(
                "Format can not be used over HPSS")
        # Make a shared repo
        remote_repo = self.make_remote_repository('remote', shared=True)
        remote_backing_repo = controldir.ControlDir.open(
            self.get_vfs_only_url('remote')).open_repository()
        # Make a branch in that repo in an old format that isn't the default
        # branch format for the repo.
        from bzrlib.branchfmt.fullhistory import BzrBranchFormat5
        format = remote_backing_repo.bzrdir.cloning_metadir()
        format._branch_format = BzrBranchFormat5()
        remote_transport = remote_repo.bzrdir.root_transport.clone('branch')
        controldir.ControlDir.create_branch_convenience(
            remote_transport.base, force_new_repo=False, format=format)
        remote_branch = controldir.ControlDir.open_from_transport(
            remote_transport).open_branch()
        try:
            local_bzrdir = remote_branch.bzrdir.sprout('local')
        except errors.TransportNotPossible:
            raise tests.TestNotApplicable(
                "Cannot lock_read old formats like AllInOne over HPSS.")
        local_repo = local_bzrdir.open_repository()
        self.assertEqual(remote_backing_repo._format, local_repo._format)

    def test_clone_to_hpss(self):
        if not self.repository_format.supports_leaving_lock:
            raise tests.TestNotApplicable(
                "Cannot lock pre_metadir_formats remotely.")
        remote_transport = self.make_smart_server('remote')
        local_branch = self.make_branch('local')
        remote_branch = local_branch.create_clone_on_transport(remote_transport)
        self.assertEqual(
            local_branch.repository._format.supports_external_lookups,
            remote_branch.repository._format.supports_external_lookups)

    def test_clone_stacking_policy_upgrades(self):
        """Cloning an unstackable branch format to somewhere with a default
        stack-on branch upgrades branch and repo to match the target and honour
        the policy.
        """
        try:
            repo = self.make_repository('repo', shared=True)
        except errors.IncompatibleFormat:
            raise tests.TestNotApplicable('Cannot make a shared repository')
        if repo.bzrdir._format.fixed_components:
            self.knownFailure(
                "pre metadir branches do not upgrade on push "
                "with stacking policy")
        if isinstance(repo._format,
                      knitpack_repo.RepositoryFormatKnitPack5RichRootBroken):
            raise tests.TestNotApplicable("unsupported format")
        # Make a source branch in 'repo' in an unstackable branch format
        bzrdir_format = self.repository_format._matchingbzrdir
        transport = self.get_transport('repo/branch')
        transport.mkdir('.')
        target_bzrdir = bzrdir_format.initialize_on_transport(transport)
        branch = _mod_branch.BzrBranchFormat6().initialize(target_bzrdir)
        # Ensure that stack_on will be stackable and match the serializer of
        # repo.
        if isinstance(repo, remote.RemoteRepository):
            repo._ensure_real()
            info_repo = repo._real_repository
        else:
            info_repo = repo
        format_description = info.describe_format(info_repo.bzrdir,
            info_repo, None, None)
        formats = format_description.split(' or ')
        stack_on_format = formats[0]
        if stack_on_format in ["pack-0.92", "dirstate", "metaweave"]:
            stack_on_format = "1.9"
        elif stack_on_format in ["dirstate-with-subtree", "rich-root",
            "rich-root-pack", "pack-0.92-subtree"]:
            stack_on_format = "1.9-rich-root"
        # formats not tested for above are already stackable, so we can use the
        # format as-is.
        stack_on = self.make_branch('stack-on-me', format=stack_on_format)
        self.make_bzrdir('.').get_config().set_default_stack_on('stack-on-me')
        target = branch.bzrdir.clone(self.get_url('target'))
        # The target branch supports stacking.
        self.assertTrue(target.open_branch()._format.supports_stacking())
        if isinstance(repo, remote.RemoteRepository):
            repo._ensure_real()
            repo = repo._real_repository
        target_repo = target.open_repository()
        if isinstance(target_repo, remote.RemoteRepository):
            target_repo._ensure_real()
            target_repo = target_repo._real_repository
        # The repository format is unchanged if it could already stack, or the
        # same as the stack on.
        if repo._format.supports_external_lookups:
            self.assertEqual(repo._format, target_repo._format)
        else:
            self.assertEqual(stack_on.repository._format, target_repo._format)

    def test__make_parents_provider(self):
        """Repositories must have a _make_parents_provider method that returns
        an object with a get_parent_map method.
        """
        repo = self.make_repository('repo')
        repo._make_parents_provider().get_parent_map

    def make_repository_and_foo_bar(self, shared=None):
        made_control = self.make_bzrdir('repository')
        repo = made_control.create_repository(shared=shared)
        if not repo._format.supports_nesting_repositories:
            raise tests.TestNotApplicable("repository does not support "
                "nesting repositories")
        controldir.ControlDir.create_branch_convenience(
            self.get_url('repository/foo'), force_new_repo=False)
        controldir.ControlDir.create_branch_convenience(
            self.get_url('repository/bar'), force_new_repo=True)
        baz = self.make_bzrdir('repository/baz')
        qux = self.make_branch('repository/baz/qux')
        quxx = self.make_branch('repository/baz/qux/quxx')
        return repo

    def test_find_branches(self):
        repo = self.make_repository_and_foo_bar()
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
            raise tests.TestNotApplicable
        branches = repo.find_branches(using=True)
        self.assertContainsRe(branches[-1].base, 'repository/foo/$')
        # in some formats, creating a repo creates a branch
        if len(branches) == 2:
            self.assertContainsRe(branches[-2].base, 'repository/$')
        else:
            self.assertEqual(1, len(branches))

    def test_find_branches_using_standalone(self):
        branch = self.make_branch('branch')
        if not branch.repository._format.supports_nesting_repositories:
            raise tests.TestNotApplicable("format does not support nesting "
                "repositories")
        contained = self.make_branch('branch/contained')
        branches = branch.repository.find_branches(using=True)
        self.assertEqual([branch.base], [b.base for b in branches])
        branches = branch.repository.find_branches(using=False)
        self.assertEqual([branch.base, contained.base],
                         [b.base for b in branches])

    def test_find_branches_using_empty_standalone_repo(self):
        try:
            repo = self.make_repository('repo', shared=False)
        except errors.IncompatibleFormat:
            raise tests.TestNotApplicable("format does not support standalone "
                "repositories")
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
        except (errors.RepositoryUpgradeRequired, errors.UnsupportedOperation), e:
            raise tests.TestNotApplicable('Format does not support this flag.')
        self.assertTrue(repo.make_working_trees())

    def test_set_get_make_working_trees_false(self):
        repo = self.make_repository('repo')
        try:
            repo.set_make_working_trees(False)
        except (errors.RepositoryUpgradeRequired, errors.UnsupportedOperation), e:
            raise tests.TestNotApplicable('Format does not support this flag.')
        self.assertFalse(repo.make_working_trees())


class TestRepositoryLocking(per_repository.TestCaseWithRepository):

    def test_leave_lock_in_place(self):
        repo = self.make_repository('r')
        # Lock the repository, then use leave_lock_in_place so that when we
        # unlock the repository the lock is still held on disk.
        token = repo.lock_write().repository_token
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
        # Cleanup
        repo.lock_write(token)
        repo.dont_leave_lock_in_place()
        repo.unlock()

    def test_dont_leave_lock_in_place(self):
        repo = self.make_repository('r')
        # Create a lock on disk.
        token = repo.lock_write().repository_token
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

    def test_lock_read_returns_unlockable(self):
        repo = self.make_repository('r')
        self.assertThat(repo.lock_read, ReturnsUnlockable(repo))

    def test_lock_write_returns_unlockable(self):
        repo = self.make_repository('r')
        self.assertThat(repo.lock_write, ReturnsUnlockable(repo))


# FIXME: document why this is a TestCaseWithTransport rather than a
#        TestCaseWithRepository
class TestEscaping(tests.TestCaseWithTransport):
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
        if isinstance(self.repository_format, remote.RemoteRepositoryFormat):
            return
        self.transport_server = test_server.FakeVFATServer
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
        branch = controldir.ControlDir.open(self.get_url('repo')).open_branch()
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
        wt.branch.repository.create_bundle(
            'rev1', _mod_revision.NULL_REVISION, fileobj)


class TestRepositoryControlComponent(per_repository.TestCaseWithRepository):
    """Repository implementations adequately implement ControlComponent."""

    def test_urls(self):
        repo = self.make_repository('repo')
        self.assertIsInstance(repo.user_url, str)
        self.assertEqual(repo.user_url, repo.user_transport.base)
        # for all current bzrdir implementations the user dir must be
        # above the control dir but we might need to relax that?
        self.assertEqual(repo.control_url.find(repo.user_url), 0)
        self.assertEqual(repo.control_url, repo.control_transport.base)


class TestDeltaRevisionFiltered(per_repository.TestCaseWithRepository):

    def setUp(self):
        super(TestDeltaRevisionFiltered, self).setUp()
        tree_a = self.make_branch_and_tree('a')
        self.build_tree(['a/foo', 'a/bar/', 'a/bar/b1', 'a/bar/b2', 'a/baz'])
        tree_a.add(['foo', 'bar', 'bar/b1', 'bar/b2', 'baz'],
                   ['foo-id', 'bar-id', 'b1-id', 'b2-id', 'baz-id'])
        tree_a.commit('rev1', rev_id='rev1')
        self.build_tree(['a/bar/b3'])
        tree_a.add('bar/b3', 'b3-id')
        tree_a.commit('rev2', rev_id='rev2')
        self.repository = tree_a.branch.repository

    def test_multiple_files(self):
        # Test multiple files
        delta = self.repository.get_revision_delta('rev1',
            specific_fileids=['foo-id', 'baz-id'])
        self.assertIsInstance(delta, _mod_delta.TreeDelta)
        self.assertEqual([
            ('baz', 'baz-id', 'file'),
            ('foo', 'foo-id', 'file'),
            ], delta.added)

    def test_directory(self):
        # Test a directory
        delta = self.repository.get_revision_delta('rev1',
            specific_fileids=['bar-id'])
        self.assertIsInstance(delta, _mod_delta.TreeDelta)
        self.assertEqual([
            ('bar', 'bar-id', 'directory'),
            ('bar/b1', 'b1-id', 'file'),
            ('bar/b2', 'b2-id', 'file'),
            ], delta.added)

    def test_unrelated(self):
        # Try another revision
        delta = self.repository.get_revision_delta('rev2',
                specific_fileids=['foo-id'])
        self.assertIsInstance(delta, _mod_delta.TreeDelta)
        self.assertEqual([], delta.added)

    def test_file_in_directory(self):
        # Test a file in a directory, both of which were added
        delta = self.repository.get_revision_delta('rev1',
            specific_fileids=['b2-id'])
        self.assertIsInstance(delta, _mod_delta.TreeDelta)
        self.assertEqual([
            ('bar', 'bar-id', 'directory'),
            ('bar/b2', 'b2-id', 'file'),
            ], delta.added)

    def test_file_in_unchanged_directory(self):
        delta = self.repository.get_revision_delta('rev2',
            specific_fileids=['b3-id'])
        self.assertIsInstance(delta, _mod_delta.TreeDelta)
        if delta.added == [
            ('bar', 'bar-id', 'directory'),
            ('bar/b3', 'b3-id', 'file')]:
            self.knownFailure("bzr incorrectly reports 'bar' as added - "
                              "bug 878217")
        self.assertEqual([
            ('bar/b3', 'b3-id', 'file'),
            ], delta.added)
