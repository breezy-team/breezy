# Copyright (C) 2006 Canonical Ltd
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

"""Tests for reconiliation of repositories."""


import bzrlib
import bzrlib.errors as errors
from bzrlib.inventory import Inventory, InventoryFile
from bzrlib.reconcile import reconcile, Reconciler
from bzrlib.revision import Revision
from bzrlib.tests import TestSkipped
from bzrlib.tests.repository_implementations.test_repository import TestCaseWithRepository
from bzrlib.transport import get_transport
from bzrlib.uncommit import uncommit
from bzrlib.workingtree import WorkingTree


class TestReconcile(TestCaseWithRepository):

    def checkUnreconciled(self, d, reconciler):
        """Check that d did not get reconciled."""
        # nothing should have been fixed yet:
        self.assertEqual(0, reconciler.inconsistent_parents)
        # and no garbage inventories
        self.assertEqual(0, reconciler.garbage_inventories)
        self.checkNoBackupInventory(d)

    def checkNoBackupInventory(self, aBzrDir):
        """Check that there is no backup inventory in aBzrDir."""
        repo = aBzrDir.open_repository()
        self.assertRaises(errors.NoSuchFile,
                          repo.control_weaves.get_weave,
                          'inventory.backup',
                          repo.get_transaction())


class TestsNeedingReweave(TestReconcile):

    def setUp(self):
        super(TestsNeedingReweave, self).setUp()
        
        t = get_transport(self.get_url())
        # an empty inventory with no revision for testing with.
        repo = self.make_repository('inventory_without_revision')
        repo.lock_write()
        repo.start_write_group()
        inv = Inventory(revision_id='missing')
        inv.root.revision = 'missing'
        repo.add_inventory('missing', inv, [])
        repo.commit_write_group()
        repo.unlock()

        # an empty inventory with no revision for testing with.
        # this is referenced by 'references_missing' to let us test
        # that all the cached data is correctly converted into ghost links
        # and the referenced inventory still cleaned.
        repo = self.make_repository('inventory_without_revision_and_ghost')
        repo.lock_write()
        repo.start_write_group()
        repo.add_inventory('missing', inv, [])
        inv = Inventory(revision_id='references_missing')
        inv.root.revision = 'references_missing'
        sha1 = repo.add_inventory('references_missing', inv, ['missing'])
        rev = Revision(timestamp=0,
                       timezone=None,
                       committer="Foo Bar <foo@example.com>",
                       message="Message",
                       inventory_sha1=sha1,
                       revision_id='references_missing')
        rev.parent_ids = ['missing']
        repo.add_revision('references_missing', rev)
        repo.commit_write_group()
        repo.unlock()

        # a inventory with no parents and the revision has parents..
        # i.e. a ghost.
        repo = self.make_repository('inventory_one_ghost')
        repo.lock_write()
        repo.start_write_group()
        inv = Inventory(revision_id='ghost')
        inv.root.revision = 'ghost'
        sha1 = repo.add_inventory('ghost', inv, [])
        rev = Revision(timestamp=0,
                       timezone=None,
                       committer="Foo Bar <foo@example.com>",
                       message="Message",
                       inventory_sha1=sha1,
                       revision_id='ghost')
        rev.parent_ids = ['the_ghost']
        repo.add_revision('ghost', rev)
        repo.commit_write_group()
        repo.unlock()
         
        # a inventory with a ghost that can be corrected now.
        t.copy_tree('inventory_one_ghost', 'inventory_ghost_present')
        bzrdir_url = self.get_url('inventory_ghost_present')
        bzrdir = bzrlib.bzrdir.BzrDir.open(bzrdir_url)
        repo = bzrdir.open_repository()
        repo.lock_write()
        repo.start_write_group()
        inv = Inventory(revision_id='the_ghost')
        inv.root.revision = 'the_ghost'
        sha1 = repo.add_inventory('the_ghost', inv, [])
        rev = Revision(timestamp=0,
                       timezone=None,
                       committer="Foo Bar <foo@example.com>",
                       message="Message",
                       inventory_sha1=sha1,
                       revision_id='the_ghost')
        rev.parent_ids = []
        repo.add_revision('the_ghost', rev)
        repo.commit_write_group()
        repo.unlock()

    def checkEmptyReconcile(self, **kwargs):
        """Check a reconcile on an empty repository."""
        self.make_repository('empty')
        d = bzrlib.bzrdir.BzrDir.open(self.get_url('empty'))
        # calling on a empty repository should do nothing
        reconciler = d.find_repository().reconcile(**kwargs)
        # no inconsistent parents should have been found
        self.assertEqual(0, reconciler.inconsistent_parents)
        # and no garbage inventories
        self.assertEqual(0, reconciler.garbage_inventories)
        # and no backup weave should have been needed/made.
        self.checkNoBackupInventory(d)

    def test_reconcile_empty(self):
        # in an empty repo, theres nothing to do.
        self.checkEmptyReconcile()

    def test_repo_has_reconcile_does_inventory_gc_attribute(self):
        repo = self.make_repository('repo')
        self.assertNotEqual(None, repo._reconcile_does_inventory_gc)

    def test_reconcile_empty_thorough(self):
        # reconcile should accept thorough=True
        self.checkEmptyReconcile(thorough=True)

    def test_convenience_reconcile_inventory_without_revision_reconcile(self):
        # smoke test for the all in one ui tool
        bzrdir_url = self.get_url('inventory_without_revision')
        bzrdir = bzrlib.bzrdir.BzrDir.open(bzrdir_url)
        repo = bzrdir.open_repository()
        if not repo._reconcile_does_inventory_gc:
            raise TestSkipped('Irrelevant test')
        reconcile(bzrdir)
        # now the backup should have it but not the current inventory
        repo = bzrdir.open_repository()
        self.check_missing_was_removed(repo)

    def test_reweave_inventory_without_revision(self):
        # an excess inventory on its own is only reconciled by using thorough
        d_url = self.get_url('inventory_without_revision')
        d = bzrlib.bzrdir.BzrDir.open(d_url)
        repo = d.open_repository()
        if not repo._reconcile_does_inventory_gc:
            raise TestSkipped('Irrelevant test')
        self.checkUnreconciled(d, repo.reconcile())
        reconciler = repo.reconcile(thorough=True)
        # no bad parents
        self.assertEqual(0, reconciler.inconsistent_parents)
        # and one garbage inventory
        self.assertEqual(1, reconciler.garbage_inventories)
        self.check_missing_was_removed(repo)

    def check_thorough_reweave_missing_revision(self, aBzrDir, reconcile,
            **kwargs):
        # actual low level test.
        repo = aBzrDir.open_repository()
        if ([None, 'missing', 'references_missing']
            != repo.get_ancestry('references_missing')):
            # the repo handles ghosts without corruption, so reconcile has
            # nothing to do here. Specifically, this test has the inventory
            # 'missing' present and the revision 'missing' missing, so clearly
            # 'missing' cannot be reported in the present ancestry -> missing
            # is something that can be filled as a ghost.
            expected_inconsistent_parents = 0
        else:
            expected_inconsistent_parents = 1
        reconciler = reconcile(**kwargs)
        # some number of inconsistent parents should have been found
        self.assertEqual(expected_inconsistent_parents,
                         reconciler.inconsistent_parents)
        # and one garbage inventories
        self.assertEqual(1, reconciler.garbage_inventories)
        # now the backup should have it but not the current inventory
        repo = aBzrDir.open_repository()
        self.check_missing_was_removed(repo)
        # and the parent list for 'references_missing' should have that
        # revision a ghost now.
        self.assertEqual([None, 'references_missing'],
                         repo.get_ancestry('references_missing'))

    def check_missing_was_removed(self, repo):
        backup = repo.control_weaves.get_weave('inventory.backup',
                                               repo.get_transaction())
        self.assertTrue('missing' in backup.versions())
        self.assertRaises(errors.RevisionNotPresent,
                          repo.get_inventory, 'missing')

    def test_reweave_inventory_without_revision_reconciler(self):
        # smoke test for the all in one Reconciler class,
        # other tests use the lower level repo.reconcile()
        d_url = self.get_url('inventory_without_revision_and_ghost')
        d = bzrlib.bzrdir.BzrDir.open(d_url)
        if not d.open_repository()._reconcile_does_inventory_gc:
            raise TestSkipped('Irrelevant test')
        def reconcile():
            reconciler = Reconciler(d)
            reconciler.reconcile()
            return reconciler
        self.check_thorough_reweave_missing_revision(d, reconcile)

    def test_reweave_inventory_without_revision_and_ghost(self):
        # actual low level test.
        d_url = self.get_url('inventory_without_revision_and_ghost')
        d = bzrlib.bzrdir.BzrDir.open(d_url)
        repo = d.open_repository()
        if not repo._reconcile_does_inventory_gc:
            raise TestSkipped('Irrelevant test')
        # nothing should have been altered yet : inventories without
        # revisions are not data loss incurring for current format
        self.check_thorough_reweave_missing_revision(d, repo.reconcile,
            thorough=True)

    def test_reweave_inventory_preserves_a_revision_with_ghosts(self):
        d = bzrlib.bzrdir.BzrDir.open(self.get_url('inventory_one_ghost'))
        reconciler = d.open_repository().reconcile(thorough=True)
        # no inconsistent parents should have been found: 
        # the lack of a parent for ghost is normal
        self.assertEqual(0, reconciler.inconsistent_parents)
        # and one garbage inventories
        self.assertEqual(0, reconciler.garbage_inventories)
        # now the current inventory should still have 'ghost'
        repo = d.open_repository()
        repo.get_inventory('ghost')
        self.assertEqual([None, 'ghost'], repo.get_ancestry('ghost'))
        
    def test_reweave_inventory_fixes_ancestryfor_a_present_ghost(self):
        d = bzrlib.bzrdir.BzrDir.open(self.get_url('inventory_ghost_present'))
        repo = d.open_repository()
        ghost_ancestry = repo.get_ancestry('ghost')
        if ghost_ancestry == [None, 'the_ghost', 'ghost']:
            # the repo handles ghosts without corruption, so reconcile has
            # nothing to do
            return
        self.assertEqual([None, 'ghost'], ghost_ancestry)
        reconciler = repo.reconcile()
        # this is a data corrupting error, so a normal reconcile should fix it.
        # one inconsistent parents should have been found : the
        # available but not reference parent for ghost.
        self.assertEqual(1, reconciler.inconsistent_parents)
        # and no garbage inventories
        self.assertEqual(0, reconciler.garbage_inventories)
        # now the current inventory should still have 'ghost'
        repo = d.open_repository()
        repo.get_inventory('ghost')
        repo.get_inventory('the_ghost')
        self.assertEqual([None, 'the_ghost', 'ghost'], repo.get_ancestry('ghost'))
        self.assertEqual([None, 'the_ghost'], repo.get_ancestry('the_ghost'))


class TestReconcileWithIncorrectRevisionCache(TestReconcile):
    """Ancestry data gets cached in knits and weaves should be reconcilable.

    This class tests that reconcile can correct invalid caches (such as after
    a reconcile).
    """

    def setUp(self):
        self.reduceLockdirTimeout()
        super(TestReconcileWithIncorrectRevisionCache, self).setUp()
        
        t = get_transport(self.get_url())
        # we need a revision with two parents in the wrong order
        # which should trigger reinsertion.
        # and another with the first one correct but the other two not
        # which should not trigger reinsertion.
        # these need to be in different repositories so that we don't
        # trigger a reconcile based on the other case.
        # there is no api to construct a broken knit repository at
        # this point. if we ever encounter a bad graph in a knit repo
        # we should add a lower level api to allow constructing such cases.
        
        # first off the common logic:
        tree = self.make_branch_and_tree('wrong-first-parent')
        second_tree = self.make_branch_and_tree('reversed-secondary-parents')
        for t in [tree, second_tree]:
            t.commit('1', rev_id='1')
            uncommit(t.branch, tree=t)
            t.commit('2', rev_id='2')
            uncommit(t.branch, tree=t)
            t.commit('3', rev_id='3')
            uncommit(t.branch, tree=t)
        #second_tree = self.make_branch_and_tree('reversed-secondary-parents')
        #second_tree.pull(tree) # XXX won't copy the repo?
        repo_secondary = second_tree.branch.repository

        # now setup the wrong-first parent case
        repo = tree.branch.repository
        repo.lock_write()
        repo.start_write_group()
        inv = Inventory(revision_id='wrong-first-parent')
        inv.root.revision = 'wrong-first-parent'
        sha1 = repo.add_inventory('wrong-first-parent', inv, ['2', '1'])
        rev = Revision(timestamp=0,
                       timezone=None,
                       committer="Foo Bar <foo@example.com>",
                       message="Message",
                       inventory_sha1=sha1,
                       revision_id='wrong-first-parent')
        rev.parent_ids = ['1', '2']
        repo.add_revision('wrong-first-parent', rev)
        repo.commit_write_group()
        repo.unlock()

        # now setup the wrong-secondary parent case
        repo = repo_secondary
        repo.lock_write()
        repo.start_write_group()
        inv = Inventory(revision_id='wrong-secondary-parent')
        inv.root.revision = 'wrong-secondary-parent'
        sha1 = repo.add_inventory('wrong-secondary-parent', inv, ['1', '3', '2'])
        rev = Revision(timestamp=0,
                       timezone=None,
                       committer="Foo Bar <foo@example.com>",
                       message="Message",
                       inventory_sha1=sha1,
                       revision_id='wrong-secondary-parent')
        rev.parent_ids = ['1', '2', '3']
        repo.add_revision('wrong-secondary-parent', rev)
        repo.commit_write_group()
        repo.unlock()

    def test_reconcile_wrong_order(self):
        # a wrong order in primary parents is optionally correctable
        t = get_transport(self.get_url()).clone('wrong-first-parent')
        d = bzrlib.bzrdir.BzrDir.open_from_transport(t)
        repo = d.open_repository()
        g = repo.get_revision_graph()
        if tuple(g['wrong-first-parent']) == ('1', '2'):
            raise TestSkipped('wrong-first-parent is not setup for testing')
        self.checkUnreconciled(d, repo.reconcile())
        # nothing should have been altered yet : inventories without
        # revisions are not data loss incurring for current format
        reconciler = repo.reconcile(thorough=True)
        # these show up as inconsistent parents
        self.assertEqual(1, reconciler.inconsistent_parents)
        # and no garbage inventories
        self.assertEqual(0, reconciler.garbage_inventories)
        # and should have been fixed:
        g = repo.get_revision_graph()
        self.assertEqual(('1', '2'), g['wrong-first-parent'])

    def test_reconcile_wrong_order_secondary_inventory(self):
        # a wrong order in the parents for inventories is ignored.
        t = get_transport(self.get_url()).clone('reversed-secondary-parents')
        d = bzrlib.bzrdir.BzrDir.open_from_transport(t)
        repo = d.open_repository()
        self.checkUnreconciled(d, repo.reconcile())
        self.checkUnreconciled(d, repo.reconcile(thorough=True))

    def make_broken_repository(self):
        repo = self.make_repository('.')

        # make rev1a: A well-formed revision, containing 'file1'
        inv = Inventory(revision_id='rev1a')
        inv.root.revision = 'rev1a'
        self.add_file(repo, inv, 'file1', 'rev1a', [])
        self.add_file(repo, inv, 'file3', 'rev1a', [])
        self.add_revision(repo, 'rev1a', inv, [''])

        # make rev1b, which has no Revision, but has an Inventory, and file1
        inv = Inventory(revision_id='rev1b')
        inv.root.revision = 'rev1b'
        self.add_file(repo, inv, 'file1', 'rev1b', [])
        repo.add_inventory('rev1b', inv, [])

        # make rev2, with file1 and file2
        # file2 is sane
        # file1 has 'rev1b' as an ancestor, even though this is not
        # mentioned by 'rev1a', making it an unreferenced ancestor
        inv = Inventory()
        self.add_file(repo, inv, 'file1', 'rev2', ['rev1a', 'rev1b'])
        self.add_file(repo, inv, 'file2', 'rev2', [])
        self.add_file(repo, inv, 'file3', 'rev2', ['rev1a'],
                      inv_revision='rev1a')
        self.add_revision(repo, 'rev2', inv, ['rev1a'])

        # make ghost revision rev1c
        inv = Inventory()
        self.add_file(repo, inv, 'file2', 'rev1c', [])

        # make rev3 with file2
        # file2 refers to 'rev1c', which is a ghost in this repository, so
        # file2 cannot have rev1c as its ancestor.
        # file3 has 'rev2' as its ancestor, but the revision in 'rev2' was
        # rev1a
        inv = Inventory()
        self.add_file(repo, inv, 'file2', 'rev3', ['rev1c'])
        self.add_file(repo, inv, 'file3', 'rev3', ['rev2'])
        self.add_revision(repo, 'rev3', inv, ['rev1c', 'rev1a'])

        # In rev2b, the true last-modifying-revision of file3 is rev1a, which
        # matches rev2.  This is to test deduplication in fixing rev4
        inv = Inventory()
        self.add_file(repo, inv, 'file3', 'rev2b', ['rev1a'],
            inv_revision='rev1a')
        self.add_revision(repo, 'rev2b', inv, ['rev1a'])

        # rev4 is for testing deduplication (rev2 and rev2b both have rev1a
        # as the last-modifying revision).
        inv = Inventory()
        self.add_file(repo, inv, 'file3', 'rev4', ['rev2'])
        self.add_revision(repo, 'rev4', inv, ['rev2', 'rev2b'])

        # rev2c is a descendant of rev1a, so the version it of file3 it
        # introduces is a head revision wrt 5
        inv = Inventory()
        self.add_file(repo, inv, 'file3', 'rev2c', ['rev1a'])
        self.add_revision(repo, 'rev2c', inv, ['rev1a'])

        # rev5 tests that only head revisions are selected as parents
        inv = Inventory()
        self.add_file(repo, inv, 'file3', 'rev5', ['rev2', 'rev2c'])
        self.add_revision(repo, 'rev5', inv, ['rev2', 'rev2c'])
        return repo

    def add_revision(self, repo, revision_id, inv, parent_ids):
        inv.revision_id = revision_id
        inv.root.revision = revision_id
        repo.add_inventory(revision_id, inv, parent_ids)
        revision = Revision(revision_id, committer='jrandom@example.com',
            timestamp=0, inventory_sha1='', timezone=0, message='foo',
            parent_ids=parent_ids)
        repo.add_revision(revision_id,revision, inv)

    def add_file(self, repo, inv, filename, revision, parents,
                 inv_revision=None):
        file_id = filename + '-id'
        entry = InventoryFile(file_id, filename, 'TREE_ROOT')
        if inv_revision is not None:
            entry.revision = inv_revision
        else:
            entry.revision = revision
        inv.add(entry)
        vf = repo.weave_store.get_weave_or_empty(file_id,
                                                 repo.get_transaction())
        vf.add_lines(revision, parents, ['%sline\n' % revision])

    def test_reconcile_text_parents(self):
        repo = self.make_broken_repository()
        vf = repo.weave_store.get_weave('file2-id', repo.get_transaction())
        bad_ancestors = repo.find_bad_ancestors(['rev1a', 'rev2', 'rev3'],
                                                'file2-id', vf, {})
        shas = dict((v, vf.get_sha1(v)) for v in vf.versions())
        vf = repo.weave_store.get_weave('file3-id', repo.get_transaction())
        self.assertEqual(['rev2'], vf.get_parents('rev3'))
        self.assertNotEqual({}, bad_ancestors)
        repo.reconcile()
        vf = repo.weave_store.get_weave('file2-id', repo.get_transaction())
        revision_versions = {}
        bad_ancestors = repo.find_bad_ancestors(['rev1a', 'rev2', 'rev3'],
                                                'file2-id', vf,
                                                revision_versions)
        self.assertEqual({}, bad_ancestors)
        shas2 = dict((v, vf.get_sha1(v)) for v in vf.versions())
        self.assertEqual(shas, shas2)
        vf = repo.weave_store.get_weave('file3-id', repo.get_transaction())
        self.assertEqual(['rev1a'], vf.get_parents('rev3'))

        # check deduplication
        self.assertEqual(['rev1a'], vf.get_parents('rev4'))

        # check all only parents are selected
        self.assertEqual(['rev2c'], vf.get_parents('rev5'))
