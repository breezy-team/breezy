# Copyright (C) 2006 by Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Tests for reconiliation of repositories."""


import bzrlib
import bzrlib.errors as errors
from bzrlib.reconcile import reconcile, Reconciler, RepoReconciler
from bzrlib.revision import Revision
from bzrlib.tests.repository_implementations.test_repository import TestCaseWithRepository
from bzrlib.transport import get_transport
from bzrlib.tree import EmptyTree
from bzrlib.workingtree import WorkingTree


class TestsNeedingReweave(TestCaseWithRepository):

    def setUp(self):
        super(TestsNeedingReweave, self).setUp()
        
        t = get_transport(self.get_url())
        # an empty inventory with no revision for testing with.
        # this is referenced by 'references_missing' to let us test
        # that all the cached data is correctly converted into ghost links
        # and the referenced inventory still cleaned.
        repo = self.make_repository('inventory_without_revision')
        inv = EmptyTree().inventory
        repo.add_inventory('missing', inv, [])
        sha1 = repo.add_inventory('references_missing', inv, ['missing'])
        rev = Revision(timestamp=0,
                       timezone=None,
                       committer="Foo Bar <foo@example.com>",
                       message="Message",
                       inventory_sha1=sha1,
                       revision_id='references_missing')
        rev.parent_ids = ['missing']
        repo.add_revision('references_missing', rev)

        # a inventory with no parents and the revision has parents..
        # i.e. a ghost.
        repo = self.make_repository('inventory_one_ghost')
        sha1 = repo.add_inventory('ghost', inv, [])
        rev = Revision(timestamp=0,
                       timezone=None,
                       committer="Foo Bar <foo@example.com>",
                       message="Message",
                       inventory_sha1=sha1,
                       revision_id='ghost')
        rev.parent_ids = ['the_ghost']
        repo.add_revision('ghost', rev)
         
        # a inventory with a ghost that can be corrected now.
        t.copy_tree('inventory_one_ghost', 'inventory_ghost_present')
        repo = bzrlib.repository.Repository.open('inventory_ghost_present')
        sha1 = repo.add_inventory('the_ghost', inv, [])
        rev = Revision(timestamp=0,
                       timezone=None,
                       committer="Foo Bar <foo@example.com>",
                       message="Message",
                       inventory_sha1=sha1,
                       revision_id='the_ghost')
        rev.parent_ids = []
        repo.add_revision('the_ghost', rev)

    def test_reweave_empty(self):
        self.make_repository('empty')
        d = bzrlib.bzrdir.BzrDir.open('empty')
        # calling on a empty repository should do nothing
        reconciler = RepoReconciler(d.find_repository())
        reconciler.reconcile()
        # no inconsistent parents should have been found
        self.assertEqual(0, reconciler.inconsistent_parents)
        # and no garbage inventories
        self.assertEqual(0, reconciler.garbage_inventories)
        # and no backup weave should have been needed/made.
        repo = d.open_repository()
        self.assertRaises(errors.NoSuchFile,
                          repo.control_weaves.get_weave,
                          'inventory.backup',
                          repo.get_transaction())

    def test_reweave_inventory_without_revision_reconcile(self):
        # smoke test for the all in one ui tool
        d = bzrlib.bzrdir.BzrDir.open('inventory_without_revision')
        reconcile(d)
        # now the backup should have it but not the current inventory
        repo = d.open_repository()
        backup = repo.control_weaves.get_weave('inventory.backup',
                                               repo.get_transaction())
        self.assertTrue('missing' in backup.versions())
        self.assertRaises(errors.RevisionNotPresent,
                          repo.get_inventory, 'missing')

    def test_reweave_inventory_without_revision_reconciler(self):
        # smoke test for the all in one Reconciler class,
        # other tests use the lower level RepoReconciler.
        d = bzrlib.bzrdir.BzrDir.open('inventory_without_revision')
        reconciler = Reconciler(d)
        reconciler.reconcile()
        # no inconsistent parents should have been found
        self.assertEqual(1, reconciler.inconsistent_parents)
        # and one garbage inventories
        self.assertEqual(1, reconciler.garbage_inventories)
        # now the backup should have it but not the current inventory
        repo = d.open_repository()
        backup = repo.control_weaves.get_weave('inventory.backup',
                                               repo.get_transaction())
        self.assertTrue('missing' in backup.versions())
        self.assertRaises(errors.RevisionNotPresent,
                          repo.get_inventory, 'missing')

    def test_reweave_inventory_without_revision(self):
        # actual low level test.
        d = bzrlib.bzrdir.BzrDir.open('inventory_without_revision')
        reconciler = RepoReconciler(d.open_repository())
        reconciler.reconcile()
        # no inconsistent parents should have been found
        self.assertEqual(1, reconciler.inconsistent_parents)
        # and one garbage inventories
        self.assertEqual(1, reconciler.garbage_inventories)
        # now the backup should have it but not the current inventory
        repo = d.open_repository()
        backup = repo.control_weaves.get_weave('inventory.backup',
                                               repo.get_transaction())
        self.assertTrue('missing' in backup.versions())
        self.assertRaises(errors.RevisionNotPresent,
                          repo.get_inventory, 'missing')
        # and the parent list for 'references_missing' should have that
        # revision a ghost now.
        self.assertEqual([None, 'references_missing'],
                         repo.get_ancestry('references_missing'))

    def test_reweave_inventory_preserves_a_revision_with_ghosts(self):
        d = bzrlib.bzrdir.BzrDir.open('inventory_one_ghost')
        reconciler = RepoReconciler(d.open_repository())
        reconciler.reconcile()
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
        d = bzrlib.bzrdir.BzrDir.open('inventory_ghost_present')
        repo = d.open_repository()
        self.assertEqual([None, 'ghost'], repo.get_ancestry('ghost'))
        reconciler = RepoReconciler(repo)
        reconciler.reconcile()
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
