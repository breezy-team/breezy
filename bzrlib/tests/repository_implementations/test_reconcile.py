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
from bzrlib.repository import _RevisionTextVersionCache
from bzrlib.revision import Revision
from bzrlib.repofmt.knitrepo import KnitRepository
from bzrlib.tests import TestNotApplicable, TestSkipped
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


class TestReconcileFileVersionParents(TestCaseWithRepository):
    """Tests for how reconcile corrects errors in parents of file versions."""

    def test_reconcile_file_parent_is_not_in_revision_ancestry(self):
        """Reconcile removes file version parents that are not in the revision
        ancestry.
        """
        self.run_test(
            self.file_parent_is_not_in_revision_ancestry_factory,
            ['rev1a', 'rev1b', 'rev2'],
            [([], 'rev1a'),
             ([], 'rev1b'),
             (['rev1a', 'rev1b'], 'rev2')],
            [([], 'rev1a'),
             ([], 'rev1b'),
             (['rev1a'], 'rev2')])

    def file_parent_is_not_in_revision_ancestry_factory(self, repo):
        """Return a repository where a revision 'rev2' has 'a-file' with a
        parent 'rev1b' that is not in the revision ancestry.  Reconcile should
        remove 'rev1b' from the parents list of 'a-file' in 'rev2', preserving
        'rev1a' as a parent.
        """
        # make rev1a: A well-formed revision, containing 'a-file'
        inv = self.make_one_file_inventory(
            repo, 'rev1a', [], root_revision='rev1a')
        self.add_revision(repo, 'rev1a', inv, [])

        # make rev1b, which has no Revision, but has an Inventory, and
        # a-file
        inv = self.make_one_file_inventory(
            repo, 'rev1b', [], root_revision='rev1b')
        repo.add_inventory('rev1b', inv, [])

        # make rev2, with a-file.
        # a-file has 'rev1b' as an ancestor, even though this is not
        # mentioned by 'rev1a', making it an unreferenced ancestor
        inv = self.make_one_file_inventory(
            repo, 'rev2', ['rev1a', 'rev1b'])
        self.add_revision(repo, 'rev2', inv, ['rev1a'])

    def test_reconcile_file_parent_inventory_inaccessible(self):
        """Reconcile removes file version parents whose inventory is
        inaccessible (i.e. the parent revision is a ghost).
        """
        self.run_test(
            self.file_parent_has_inaccessible_inventory_factory,
            ['rev2', 'rev3'],
            [
             ([], 'rev2'),
             (['rev1c'], 'rev3')],
            [
             ([], 'rev2'),
             ([], 'rev3')])

    def file_parent_has_inaccessible_inventory_factory(self, repo):
        """Return a repository with revision 'rev3' containing 'a-file'
        modified in 'rev3' but with a parent which is in the revision
        ancestory, but whose inventory cannot be accessed at all.
        """
        # make rev2, with a-file
        # a-file is sane
        inv = self.make_one_file_inventory(repo, 'rev2', [])
        self.add_revision(repo, 'rev2', inv, [])

        # make ghost revision rev1c, with a version of a-file present so
        # that we generate a knit delta against this version.  In real life
        # the ghost might never have been present or rev3 might have been
        # generated against a revision that was present at the time.  So
        # currently we have the full history of a-file present even though
        # the inventory and revision objects are not.
        self.make_one_file_inventory(repo, 'rev1c', [])

        # make rev3 with a-file
        # a-file refers to 'rev1c', which is a ghost in this repository, so
        # a-file cannot have rev1c as its ancestor.
        # XXX: I've sent a mail to the list about this.  It's not necessarily
        # right that it cannot have rev1c as its ancestor, though it is correct
        # that it should not be a delta against rev1c because we cannot verify
        # that the inventory of rev1c includes a-file as modified in rev1c.
        inv = self.make_one_file_inventory(repo, 'rev3', ['rev1c'])
        self.add_revision(repo, 'rev3', inv, ['rev1c', 'rev1a'])

    def test_reconcile_file_parents_not_referenced_by_any_inventory(self):
        """Reconcile removes file parents that are not referenced by any
        inventory.
        """
        all_versions = [
            'rev1a', 'rev2', 'rev4', 'rev2b', 'rev4', 'rev2c', 'rev5']
        file_parents_before_reconcile = [
             (['rev2'], 'rev3'),
             (['rev2'], 'rev4'),
             (['rev2', 'rev2c'], 'rev5'),
             ]
        file_parents_after_reconcile = [
            # rev3's accessible parent inventories all have rev1a as the last
            # modifier.
            (['rev1a'], 'rev3'),
            # rev1a features in both rev4's parents but should only appear once
            # in the result
            (['rev1a'], 'rev4'),
            # rev2c is the head of rev1a and rev2c, the inventory provided
            # per-file last-modified revisions/.
            (['rev2c'], 'rev5'),
            ]
        self.run_test(
            self.file_parents_not_referenced_by_any_inventory_factory,
            all_versions,
            file_parents_before_reconcile,
            file_parents_after_reconcile
            )
            
    def file_parents_not_referenced_by_any_inventory_factory(self, repo):
        """Return a repository with file 'a-file' which has extra per-file
        versions that are not referenced by any inventory (even though they
        have the same ID as actual revisions).  The inventory of 'rev2'
        references 'rev1a' of 'a-file', but there is a 'rev2' of 'some-file'
        stored and erroneously referenced by later per-file versions (revisions
        'rev4' and 'rev5').
        """
        # make rev1a: A well-formed revision, containing 'a-file'
        inv = self.make_one_file_inventory(
            repo, 'rev1a', [], root_revision='rev1a')
        self.add_revision(repo, 'rev1a', inv, [])

        # make rev2, with a-file.
        # a-file is unmodified from rev1a.
        self.make_one_file_inventory(
            repo, 'rev2', ['rev1a'], inv_revision='rev1a')
        self.add_revision(repo, 'rev2', inv, ['rev1a'])

        # make rev3 with a-file
        # a-file has 'rev2' as its ancestor, but the revision in 'rev2' was
        # rev1a so this is inconsistent with rev2's inventory - it should
        # be rev1a, and at the revision level 1c is not present - it is a
        # ghost, so only the details from rev1a are available for
        # determining whether a delta is acceptable, or a full is needed,
        # and what the correct parents are. ### same problem as the vf2 # # ghost case has in this respect
        inv = self.make_one_file_inventory(repo, 'rev3', ['rev2'])
        self.add_revision(repo, 'rev3', inv, ['rev1c', 'rev1a']) # XXX: extra parent irrevelvant?

        # In rev2b, the true last-modifying-revision of a-file is rev1a,
        # inherited from rev2, but there is a version rev2b of the file, which
        # reconcile could remove, leaving no rev2b.  Most importantly,
        # revisions descending from rev2b should not have per-file parents of
        # a-file-rev2b.
        # ??? This is to test deduplication in fixing rev4
        inv = self.make_one_file_inventory(
            repo, 'rev2b', ['rev1a'], inv_revision='rev1a')
        self.add_revision(repo, 'rev2b', inv, ['rev1a'])

        # rev4 is for testing that when the last modified of a file in
        # multiple parent revisions is the same, that it only appears once
        # in the generated per file parents list: rev2 and rev2b both
        # descend from 1a and do not change the file a-file, so there should
        # be no version of a-file 'rev2' or 'rev2b', but rev4 does change
        # a-file, and is a merge of rev2 and rev2b, so it should end up with
        # a parent of just rev1a - the starting file parents list is simply
        # completely wrong.
        inv = self.make_one_file_inventory(repo, 'rev4', ['rev2'])
        self.add_revision(repo, 'rev4', inv, ['rev2', 'rev2b'])

        # rev2c changes a-file from rev1a, so the version it of a-file it
        # introduces is a head revision when rev5 is checked.
        inv = self.make_one_file_inventory(repo, 'rev2c', ['rev1a'])
        self.add_revision(repo, 'rev2c', inv, ['rev1a'])

        # rev5 descends from rev2 and rev2c; as rev2 does not alter a-file,
        # but rev2c does, this should use rev2c as the parent for the per
        # file history, even though more than one per-file parent is
        # available, because we use the heads of the revision parents for
        # the inventory modification revisions of the file to determine the
        # parents for the per file graph.
        inv = self.make_one_file_inventory(repo, 'rev5', ['rev2', 'rev2c'])
        self.add_revision(repo, 'rev5', inv, ['rev2', 'rev2c'])

    def test_too_many_parents(self):
        self.run_test(
            self.too_many_parents_factory,
            ['bad-parent', 'good-parent', 'broken-revision'],
            [([], 'bad-parent'),
             (['bad-parent'], 'good-parent'),
             (['good-parent', 'bad-parent'], 'broken-revision')],
            [([], 'bad-parent'),
             (['bad-parent'], 'good-parent'),
             (['good-parent'], 'broken-revision')])

    def too_many_parents_factory(self, repo):
        inv = self.make_one_file_inventory(
            repo, 'bad-parent', [], root_revision='bad-parent')
        self.add_revision(repo, 'bad-parent', inv, [])
        
        inv = self.make_one_file_inventory(
            repo, 'good-parent', ['bad-parent'])
        self.add_revision(repo, 'good-parent', inv, ['bad-parent'])
        
        inv = self.make_one_file_inventory(
            repo, 'broken-revision', ['good-parent', 'bad-parent'])
        self.add_revision(repo, 'broken-revision', inv, ['good-parent'])

    #def test_incorrectly_ordered_parents(self):


    def make_repository_using_factory(self, factory):
        """Create a new repository populated by the given factory."""
        repo = self.make_repository('broken-repo')
        repo.lock_write()
        try:
            repo.start_write_group()
            try:
                factory(repo)
                repo.commit_write_group()
                return repo
            except:
                repo.abort_write_group()
                raise
        finally:
            repo.unlock()

    def add_revision(self, repo, revision_id, inv, parent_ids):
        inv.revision_id = revision_id
        inv.root.revision = revision_id
        repo.add_inventory(revision_id, inv, parent_ids)
        revision = Revision(revision_id, committer='jrandom@example.com',
            timestamp=0, inventory_sha1='', timezone=0, message='foo',
            parent_ids=parent_ids)
        repo.add_revision(revision_id,revision, inv)

    def make_one_file_inventory(self, repo, revision, parents,
                                inv_revision=None, root_revision=None):
        """Make an inventory containing a version of a file with ID 'a-file'.

        The file's ID will be 'a-file', and its filename will be 'a file name',
        stored at the tree root.

        :param repo: a repository to add the new file version to.
        :param revision: the revision ID of the new inventory.
        :param parents: the parents for this revision of 'a-file'.
        :param inv_revision: if not None, the revision ID to store in the
            inventory entry.  Otherwise, this defaults to revision.
        :param root_revision: if not None, the inventory's root.revision will
            be set to this.
        """
        inv = Inventory(revision_id=revision)
        if root_revision is not None:
            inv.root.revision = root_revision
        file_id = 'a-file-id'
        entry = InventoryFile(file_id, 'a file name', 'TREE_ROOT')
        if inv_revision is not None:
            entry.revision = inv_revision
        else:
            entry.revision = revision
        entry.text_size = 0
        inv.add(entry)
        vf = repo.weave_store.get_weave_or_empty(file_id,
                                                 repo.get_transaction())
        vf.add_lines(revision, parents, ['%sline\n' % revision])
        return inv

    def require_text_parent_corruption(self, repo):
        if not repo._reconcile_fixes_text_parents:
            raise TestNotApplicable(
                    "Format does not support text parent reconciliation")

    def file_parents(self, repo, revision_id):
        return repo.weave_store.get_weave('a-file-id',
            repo.get_transaction()).get_parents(revision_id)

    def run_test(self, factory, all_versions, affected_before,
            affected_after):
        """Construct a repository and reconcile it, verifying the state before
        and after.

        :param factory: a method to use to populate a repository with sample
            revisions, inventories and file versions.
        :param all_versions: all the versions in repository.  run_test verifies
            that the text of each of these versions of the file is unchanged
            by the reconcile.
        :param affected_before: a list of (parents list, revision).  Each
            version of the file is verified to have the given parents before
            running the reconcile.  i.e. this is used to assert that the repo
            from the factory is what we expect.
        :param affected_after: a list of (parents list, revision).  Each
            version of the file is verified to have the given parents after the
            reconcile.  i.e. this is used to assert that reconcile made the
            changes we expect it to make.
        """
        repo = self.make_repository_using_factory(factory)
        self.require_text_parent_corruption(repo)
        for bad_parents, version in affected_before:
            file_parents = self.file_parents(repo, version)
            self.assertEqual(bad_parents, file_parents,
                "Expected version %s of a-file-id to have parents %s before "
                "reconcile, but it has %s instead."
                % (version, bad_parents, file_parents))
        vf = repo.weave_store.get_weave('a-file-id', repo.get_transaction())
        vf_shas = dict((v, vf.get_sha1(v)) for v in all_versions)
        repo.reconcile(thorough=True)
        for good_parents, version in affected_after:
            file_parents = self.file_parents(repo, version)
            self.assertEqual(good_parents, file_parents,
                "Expected version %s of a-file-id to have parents %s after "
                "reconcile, but it has %s instead."
                % (version, good_parents, file_parents))
        # The content of the versionedfile should be the same after the
        # reconcile.
        vf = repo.weave_store.get_weave('a-file-id', repo.get_transaction())
        self.assertEqual(
            vf_shas, dict((v, vf.get_sha1(v)) for v in all_versions))

