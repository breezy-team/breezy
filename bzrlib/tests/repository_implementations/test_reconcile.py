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
from bzrlib.reconcile import reconcile, Reconciler
from bzrlib.revision import Revision
from bzrlib.tests import TestSkipped
from bzrlib.tests.repository_implementations.test_repository import TestCaseWithRepository
from bzrlib.transport import get_transport
from bzrlib.tree import EmptyTree
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
        inv = EmptyTree().inventory
        repo.add_inventory('missing', inv, [])

        # an empty inventory with no revision for testing with.
        # this is referenced by 'references_missing' to let us test
        # that all the cached data is correctly converted into ghost links
        # and the referenced inventory still cleaned.
        repo = self.make_repository('inventory_without_revision_and_ghost')
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

    def checkEmptyReconcile(self, **kwargs):
        """Check a reconcile on an empty repository."""
        self.make_repository('empty')
        d = bzrlib.bzrdir.BzrDir.open('empty')
        # calling on a empty repository should do nothing
        reconciler = d.find_repository().reconcile(**kwargs)
        # no inconsistent parents should have been found
        self.assertEqual(0, reconciler.inconsistent_parents)
        # and no garbage inventories
        self.assertEqual(0, reconciler.garbage_inventories)
        # and no backup weave should have been needed/made.
        self.checkNoBackupInventory(d)

    def test_reconile_empty(self):
        # in an empty repo, theres nothing to do.
        self.checkEmptyReconcile()

    def test_reconcile_empty_thorough(self):
        # reconcile should accept thorough=True
        self.checkEmptyReconcile(thorough=True)

    def test_convenience_reconcile_inventory_without_revision_reconcile(self):
        # smoke test for the all in one ui tool
        d = bzrlib.bzrdir.BzrDir.open('inventory_without_revision')
        reconcile(d)
        # now the backup should have it but not the current inventory
        repo = d.open_repository()
        self.check_missing_was_removed(repo)

    def test_reweave_inventory_without_revision(self):
        # an excess inventory on its own is only reconciled by using thorough
        d = bzrlib.bzrdir.BzrDir.open('inventory_without_revision')
        repo = d.open_repository()
        self.checkUnreconciled(d, repo.reconcile())
        reconciler = repo.reconcile(thorough=True)
        # no bad parents
        self.assertEqual(0, reconciler.inconsistent_parents)
        # and one garbage inventoriy
        self.assertEqual(1, reconciler.garbage_inventories)
        self.check_missing_was_removed(repo)

    def check_thorough_reweave_missing_revision(self, aBzrDir, reconcile,
            **kwargs):
        # actual low level test.
        repo = aBzrDir.open_repository()
        if ([None, 'missing', 'references_missing'] 
            != repo.get_ancestry('references_missing')):
            # the repo handles ghosts without corruption, so reconcile has
            # nothing to do here
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
        d = bzrlib.bzrdir.BzrDir.open('inventory_without_revision_and_ghost')
        def reconcile():
            reconciler = Reconciler(d)
            reconciler.reconcile()
            return reconciler
        self.check_thorough_reweave_missing_revision(d, reconcile)

    def test_reweave_inventory_without_revision_and_ghost(self):
        # actual low level test.
        d = bzrlib.bzrdir.BzrDir.open('inventory_without_revision_and_ghost')
        repo = d.open_repository()
        # nothing should have been altered yet : inventories without
        # revisions are not data loss incurring for current format
        self.check_thorough_reweave_missing_revision(d, repo.reconcile,
            thorough=True)

    def test_reweave_inventory_preserves_a_revision_with_ghosts(self):
        d = bzrlib.bzrdir.BzrDir.open('inventory_one_ghost')
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
        d = bzrlib.bzrdir.BzrDir.open('inventory_ghost_present')
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
        tree.commit('1', rev_id='1')
        uncommit(tree.branch, tree=tree)
        tree.commit('2', rev_id='2')
        uncommit(tree.branch, tree=tree)
        tree.commit('3', rev_id='3')
        uncommit(tree.branch, tree=tree)
        repo_secondary = tree.bzrdir.clone(
            'reversed-secondary-parents').open_repository()

        # now setup the wrong-first parent case
        repo = tree.branch.repository
        inv = EmptyTree().inventory
        sha1 = repo.add_inventory('wrong-first-parent', inv, ['2', '1'])
        rev = Revision(timestamp=0,
                       timezone=None,
                       committer="Foo Bar <foo@example.com>",
                       message="Message",
                       inventory_sha1=sha1,
                       revision_id='wrong-first-parent')
        rev.parent_ids = ['1', '2']
        repo.add_revision('wrong-first-parent', rev)

        # now setup the wrong-secondary parent case
        repo = repo_secondary
        inv = EmptyTree().inventory
        sha1 = repo.add_inventory('wrong-secondary-parent', inv, ['1', '3', '2'])
        rev = Revision(timestamp=0,
                       timezone=None,
                       committer="Foo Bar <foo@example.com>",
                       message="Message",
                       inventory_sha1=sha1,
                       revision_id='wrong-secondary-parent')
        rev.parent_ids = ['1', '2', '3']
        repo.add_revision('wrong-secondary-parent', rev)

    def test_reconcile_wrong_order(self):
        # a wrong order in primary parents is optionally correctable
        d = bzrlib.bzrdir.BzrDir.open('wrong-first-parent')
        repo = d.open_repository()
        g = repo.get_revision_graph()
        if g['wrong-first-parent'] == ['1', '2']:
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
        self.assertEqual(['1', '2'], g['wrong-first-parent'])

    def test_reconcile_wrong_order_secondary(self):
        # a wrong order in secondary parents is ignored.
        d = bzrlib.bzrdir.BzrDir.open('reversed-secondary-parents')
        repo = d.open_repository()
        self.checkUnreconciled(d, repo.reconcile())
        self.checkUnreconciled(d, repo.reconcile(thorough=True))
