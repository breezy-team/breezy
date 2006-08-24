# Copyright (C) 2005, 2006 Canonical Ltd
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

import os
import re
import sys

import bzrlib
from bzrlib import bzrdir, errors, repository
from bzrlib.branch import Branch, needs_read_lock, needs_write_lock
from bzrlib.delta import TreeDelta
from bzrlib.errors import (FileExists,
                           NoSuchRevision,
                           NoSuchFile,
                           UninitializableFormat,
                           NotBranchError,
                           )
from bzrlib.inventory import Inventory
from bzrlib.revision import NULL_REVISION
from bzrlib.tests import TestCase, TestCaseWithTransport, TestSkipped
from bzrlib.tests.bzrdir_implementations.test_bzrdir import TestCaseWithBzrDir
from bzrlib.trace import mutter
import bzrlib.transactions as transactions
from bzrlib.transport import get_transport
from bzrlib.upgrade import upgrade
from bzrlib.workingtree import WorkingTree


class TestCaseWithRepository(TestCaseWithBzrDir):

    def setUp(self):
        super(TestCaseWithRepository, self).setUp()

    def make_branch(self, relpath, format=None):
        repo = self.make_repository(relpath, format=None)
        return repo.bzrdir.create_branch()

    def make_repository(self, relpath, format=None):
        made_control = self.make_bzrdir(relpath)
        return self.repository_format.initialize(made_control)


class TestRepository(TestCaseWithRepository):

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
        tree_b.get_file_text('file1')
        rev1 = repo_b.get_revision('rev1')

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
        self.failUnless(isinstance(made_repo, repository.Repository))
        self.assertEqual(made_control, made_repo.bzrdir)

        # find it via bzrdir opening:
        opened_control = bzrdir.BzrDir.open(readonly_t.base)
        direct_opened_repo = opened_control.open_repository()
        self.assertEqual(direct_opened_repo.__class__, made_repo.__class__)
        self.assertEqual(opened_control, direct_opened_repo.bzrdir)

        self.failUnless(isinstance(direct_opened_repo._format,
                        self.repository_format.__class__))
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
        self.failUnless(isinstance(made_repo, repository.Repository))
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
        self.failUnless(isinstance(made_repo, repository.Repository))
        self.assertEqual(made_control, made_repo.bzrdir)
        self.assertTrue(made_repo.is_shared())

    def test_revision_tree(self):
        wt = self.make_branch_and_tree('.')
        wt.commit('lala!', rev_id='revision-1', allow_pointless=True)
        tree = wt.branch.repository.revision_tree('revision-1')
        self.assertEqual(list(tree.list_files()), [])
        tree = wt.branch.repository.revision_tree(None)
        self.assertEqual([], list(tree.list_files()))
        tree = wt.branch.repository.revision_tree(NULL_REVISION)
        self.assertEqual([], list(tree.list_files()))

    def test_fetch(self):
        # smoke test fetch to ensure that the convenience function works.
        # it is defined as a convenience function with the underlying 
        # functionality provided by an InterRepository
        tree_a = self.make_branch_and_tree('a')
        self.build_tree(['a/foo'])
        tree_a.add('foo', 'file1')
        tree_a.commit('rev1', rev_id='rev1')
        # fetch with a default limit (grab everything)
        repo = bzrdir.BzrDir.create_repository(self.get_url('b'))
        if (tree_a.branch.repository._format.rich_root_data and not
            repo._format.rich_root_data):
            raise TestSkipped('Cannot fetch from model2 to model1')
        repo.fetch(tree_a.branch.repository,
                   revision_id=None,
                   pb=bzrlib.progress.DummyProgress())

    def test_fetch_knit2(self):
        tree_a = self.make_branch_and_tree('a')
        self.build_tree(['a/foo'])
        tree_a.add('foo', 'file1')
        tree_a.commit('rev1', rev_id='rev1')
        # fetch with a default limit (grab everything)
        f = bzrdir.BzrDirMetaFormat1()
        f._repository_format = repository.RepositoryFormatKnit2()
        os.mkdir('b')
        b_bzrdir = f.initialize(self.get_url('b'))
        repo = b_bzrdir.create_repository()
        repo.fetch(tree_a.branch.repository,
                   revision_id=None,
                   pb=bzrlib.progress.DummyProgress())
        rev1_tree = repo.revision_tree('rev1')
        lines = rev1_tree.get_file_lines(rev1_tree.inventory.root.file_id)
        self.assertEqual([], lines)
        b_branch = b_bzrdir.create_branch()
        b_branch.pull(tree_a.branch)
        tree_b = b_bzrdir.create_workingtree()
        tree_b.commit('no change', rev_id='rev2')
        rev2_tree = repo.revision_tree('rev2')
        self.assertEqual('rev1', rev2_tree.inventory.root.revision)

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

    def test_clone_repository_incomplete_source_with_basis(self):
        # ensure that basis really does grab from the basis by having incomplete source
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['foo'], transport=tree.bzrdir.transport.clone('..'))
        tree.add('foo')
        tree.commit('revision 1', rev_id='1')
        source = self.make_repository('source')
        # this gives us an incomplete repository
        tree.bzrdir.open_repository().copy_content_into(source)
        tree.commit('revision 2', rev_id='2', allow_pointless=True)
        self.assertFalse(source.has_revision('2'))
        target = source.bzrdir.clone(self.get_url('target'), basis=tree.bzrdir)
        self.assertTrue(target.open_repository().has_revision('2'))

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
        made_repo.set_make_working_trees(False)
        result = made_control.clone(self.get_url('target'))
        self.failUnless(isinstance(made_repo, repository.Repository))
        self.assertEqual(made_control, made_repo.bzrdir)
        self.assertTrue(result.open_repository().is_shared())
        self.assertFalse(result.open_repository().make_working_trees())

    def test_upgrade_preserves_signatures(self):
        wt = self.make_branch_and_tree('source')
        wt.commit('A', allow_pointless=True, rev_id='A')
        wt.branch.repository.sign_revision('A',
            bzrlib.gpg.LoopbackGPGStrategy(None))
        old_signature = wt.branch.repository.get_signature_text('A')
        try:
            old_format = bzrdir.BzrDirFormat.get_default_format()
            # This gives metadir branches something they can convert to.
            # it would be nice to have a 'latest' vs 'default' concept.
            bzrdir.BzrDirFormat.set_default_format(bzrdir.BzrDirMetaFormat1())
            try:
                upgrade(wt.basedir)
            finally:
                bzrdir.BzrDirFormat.set_default_format(old_format)
        except errors.UpToDateFormat:
            # this is in the most current format already.
            return
        except errors.BadConversionTarget, e:
            raise TestSkipped(str(e))
        wt = WorkingTree.open(wt.basedir)
        new_signature = wt.branch.repository.get_signature_text('A')
        self.assertEqual(old_signature, new_signature)

    def test_exposed_versioned_files_are_marked_dirty(self):
        repo = self.make_repository('.')
        repo.lock_write()
        inv = repo.get_inventory_weave()
        repo.unlock()
        self.assertRaises(errors.OutSideTransaction, inv.add_lines, 'foo', [], [])

    def test_format_description(self):
        repo = self.make_repository('.')
        text = repo._format.get_format_description()
        self.failUnless(len(text))

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
        result = tree.branch.repository.check(['a-rev'])
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
        assert len(revisions) == 3, repr(revisions)
        zipped = zip(revisions, revision_ids)
        self.assertEqual(len(zipped), 3)
        for revision, revision_id in zipped:
            self.assertEqual(revision.revision_id, revision_id)
            self.assertEqual(revision, repo.get_revision(revision_id))

    def test_root_entry_has_revision(self):
        tree = self.make_branch_and_tree('.')
        tree.commit('message', rev_id='rev_id')
        self.assertEqual('rev_id', tree.basis_tree().inventory.root.revision)
        rev_tree = tree.branch.repository.revision_tree(tree.last_revision())
        self.assertEqual('rev_id', rev_tree.inventory.root.revision)

    def test_create_basis_inventory(self):
        # Needs testing here because differences between repo and working tree
        # basis inventory formats can lead to bugs.
        t = self.make_branch_and_tree('.')
        b = t.branch
        open('a', 'wb').write('a\n')
        t.add('a')
        t.commit('a', rev_id='r1')

        t._control_files.get_utf8('basis-inventory-cache')

        basis_inv = t.basis_tree().inventory
        self.assertEquals('r1', basis_inv.revision_id)
        
        store_inv = b.repository.get_inventory('r1')
        self.assertEquals(store_inv._byid, basis_inv._byid)

        open('b', 'wb').write('b\n')
        t.add('b')
        t.commit('b', rev_id='r2')

        t._control_files.get_utf8('basis-inventory-cache')

        basis_inv_txt = t.read_basis_inventory()
        basis_inv = bzrlib.xml6.serializer_v6.read_inventory_from_string(basis_inv_txt)
        self.assertEquals('r2', basis_inv.revision_id)
        store_inv = b.repository.get_inventory('r2')

        self.assertEquals(store_inv._byid, basis_inv._byid)

    def test_upgrade_from_format4(self):
        from bzrlib.tests.test_upgrade import _upgrade_dir_template
        if self.repository_format.__class__ == repository.RepositoryFormat4:
            raise TestSkipped('Cannot convert format-4 to itself')
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


class TestCaseWithComplexRepository(TestCaseWithRepository):

    def setUp(self):
        super(TestCaseWithComplexRepository, self).setUp()
        tree_a = self.make_branch_and_tree('a')
        self.bzrdir = tree_a.branch.bzrdir
        # add a corrupt inventory 'orphan'
        # this may need some generalising for knits.
        inv_file = tree_a.branch.repository.control_weaves.get_weave(
            'inventory', 
            tree_a.branch.repository.get_transaction())
        inv_file.add_lines('orphan', [], [])
        # add a real revision 'rev1'
        tree_a.commit('rev1', rev_id='rev1', allow_pointless=True)
        # add a real revision 'rev2' based on rev1
        tree_a.commit('rev2', rev_id='rev2', allow_pointless=True)
        # add a reference to a ghost
        tree_a.add_pending_merge('ghost1')
        tree_a.commit('rev3', rev_id='rev3', allow_pointless=True)
        # add another reference to a ghost, and a second ghost.
        tree_a.add_pending_merge('ghost1')
        tree_a.add_pending_merge('ghost2')
        tree_a.commit('rev4', rev_id='rev4', allow_pointless=True)

    def test_revision_trees(self):
        revision_ids = ['rev1', 'rev2', 'rev3', 'rev4']
        repository = self.bzrdir.open_repository()
        trees1 = list(repository.revision_trees(revision_ids))
        trees2 = [repository.revision_tree(t) for t in revision_ids]
        assert len(trees1) == len(trees2)
        for tree1, tree2 in zip(trees1, trees2):
            assert not tree2.changes_from(tree1).has_changed()

    def test_get_deltas_for_revisions(self):
        repository = self.bzrdir.open_repository()
        revisions = [repository.get_revision(r) for r in 
                     ['rev1', 'rev2', 'rev3', 'rev4']]
        deltas1 = list(repository.get_deltas_for_revisions(revisions))
        deltas2 = [repository.get_revision_delta(r.revision_id) for r in
                   revisions]
        assert deltas1 == deltas2

    def test_all_revision_ids(self):
        # all_revision_ids -> all revisions
        self.assertEqual(['rev1', 'rev2', 'rev3', 'rev4'],
                         self.bzrdir.open_repository().all_revision_ids())

    def test_get_ancestry_missing_revision(self):
        # get_ancestry(revision that is in some data but not fully installed
        # -> NoSuchRevision
        self.assertRaises(errors.NoSuchRevision,
                          self.bzrdir.open_repository().get_ancestry, 'orphan')

    def test_get_revision_graph(self):
        # we can get a mapping of id->parents for the entire revision graph or bits thereof.
        self.assertEqual({'rev1':[],
                          'rev2':['rev1'],
                          'rev3':['rev2'],
                          'rev4':['rev3'],
                          },
                         self.bzrdir.open_repository().get_revision_graph(None))
        self.assertEqual({'rev1':[]},
                         self.bzrdir.open_repository().get_revision_graph('rev1'))
        self.assertEqual({'rev1':[],
                          'rev2':['rev1']},
                         self.bzrdir.open_repository().get_revision_graph('rev2'))
        self.assertRaises(NoSuchRevision,
                          self.bzrdir.open_repository().get_revision_graph,
                          'orphan')
        # and ghosts are not mentioned
        self.assertEqual({'rev1':[],
                          'rev2':['rev1'],
                          'rev3':['rev2'],
                          },
                         self.bzrdir.open_repository().get_revision_graph('rev3'))
        # and we can ask for the NULLREVISION graph
        self.assertEqual({},
            self.bzrdir.open_repository().get_revision_graph(NULL_REVISION))

    def test_get_revision_graph_with_ghosts(self):
        # we can get a graph object with roots, ghosts, ancestors and
        # descendants.
        repo = self.bzrdir.open_repository()
        graph = repo.get_revision_graph_with_ghosts([])
        self.assertEqual(set(['rev1']), graph.roots)
        self.assertEqual(set(['ghost1', 'ghost2']), graph.ghosts)
        self.assertEqual({'rev1':[],
                          'rev2':['rev1'],
                          'rev3':['rev2', 'ghost1'],
                          'rev4':['rev3', 'ghost1', 'ghost2'],
                          },
                          graph.get_ancestors())
        self.assertEqual({'ghost1':{'rev3':1, 'rev4':1},
                          'ghost2':{'rev4':1},
                          'rev1':{'rev2':1},
                          'rev2':{'rev3':1},
                          'rev3':{'rev4':1},
                          'rev4':{},
                          },
                          graph.get_descendants())
        # and we can ask for the NULLREVISION graph
        graph = repo.get_revision_graph_with_ghosts([NULL_REVISION])
        self.assertEqual({}, graph.get_ancestors())
        self.assertEqual({}, graph.get_descendants())


class TestCaseWithCorruptRepository(TestCaseWithRepository):

    def setUp(self):
        super(TestCaseWithCorruptRepository, self).setUp()
        # a inventory with no parents and the revision has parents..
        # i.e. a ghost.
        repo = self.make_repository('inventory_with_unnecessary_ghost')
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
        repo.add_revision('ghost', rev)
         
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
        inv_weave = repo.get_inventory_weave()
        self.assertEqual(['ghost'], inv_weave.get_ancestry(['ghost']))

    def test_corrupt_revision_access_asserts_if_reported_wrong(self):
        repo = repository.Repository.open('inventory_with_unnecessary_ghost')
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
        repo = repository.Repository.open('inventory_with_unnecessary_ghost')
        repo.get_revision_reconcile('ghost')
