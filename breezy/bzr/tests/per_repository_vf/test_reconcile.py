# Copyright (C) 2006-2010 Canonical Ltd
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

"""Tests for reconciliation of repositories."""

import breezy
from breezy import errors
from breezy.bzr.bzrdir import BzrDir
from breezy.bzr.inventory import Inventory
from breezy.bzr.tests.per_repository_vf import (
    TestCaseWithRepository,
    all_repository_vf_format_scenarios,
)
from breezy.bzr.tests.per_repository_vf.helpers import TestCaseWithBrokenRevisionIndex
from breezy.reconcile import Reconciler, reconcile
from breezy.revision import Revision
from breezy.tests import TestSkipped
from breezy.tests.matchers import MatchesAncestry
from breezy.tests.scenarios import load_tests_apply_scenarios
from breezy.uncommit import uncommit

load_tests = load_tests_apply_scenarios


class TestReconcile(TestCaseWithRepository):
    scenarios = all_repository_vf_format_scenarios()

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
        for path in repo.control_transport.list_dir("."):
            self.assertFalse("inventory.backup" in path)


class TestBadRevisionParents(TestCaseWithBrokenRevisionIndex):
    scenarios = all_repository_vf_format_scenarios()

    def test_aborts_if_bad_parents_in_index(self):
        """Reconcile refuses to proceed if the revision index is wrong when
        checked against the revision texts, so that it does not generate broken
        data.

        Ideally reconcile would fix this, but until we implement that we just
        make sure we safely detect this problem.
        """
        repo = self.make_repo_with_extra_ghost_index()
        result = repo.reconcile(thorough=True)
        self.assertTrue(
            result.aborted, "reconcile should have aborted due to bad parents."
        )

    def test_does_not_abort_on_clean_repo(self):
        repo = self.make_repository(".")
        result = repo.reconcile(thorough=True)
        self.assertFalse(
            result.aborted,
            "reconcile should not have aborted on an unbroken repository.",
        )


class TestsNeedingReweave(TestReconcile):
    def setUp(self):
        super().setUp()

        t = self.get_transport()
        # an empty inventory with no revision for testing with.
        repo = self.make_repository("inventory_without_revision")
        repo.lock_write()
        repo.start_write_group()
        inv = Inventory(revision_id=b"missing")
        inv.root.revision = b"missing"
        repo.add_inventory(b"missing", inv, [])
        repo.commit_write_group()
        repo.unlock()

        def add_commit(repo, revision_id, parent_ids):
            repo.lock_write()
            repo.start_write_group()
            inv = Inventory(revision_id=revision_id)
            inv.root.revision = revision_id
            root_id = inv.root.file_id
            sha1 = repo.add_inventory(revision_id, inv, parent_ids)
            repo.texts.add_lines((root_id, revision_id), [], [])
            rev = breezy.revision.Revision(
                timestamp=0,
                timezone=None,
                committer="Foo Bar <foo@example.com>",
                message="Message",
                inventory_sha1=sha1,
                revision_id=revision_id,
            )
            rev.parent_ids = parent_ids
            repo.add_revision(revision_id, rev)
            repo.commit_write_group()
            repo.unlock()

        # an empty inventory with no revision for testing with.
        # this is referenced by 'references_missing' to let us test
        # that all the cached data is correctly converted into ghost links
        # and the referenced inventory still cleaned.
        repo = self.make_repository("inventory_without_revision_and_ghost")
        repo.lock_write()
        repo.start_write_group()
        repo.add_inventory(b"missing", inv, [])
        repo.commit_write_group()
        repo.unlock()
        add_commit(repo, b"references_missing", [b"missing"])

        # a inventory with no parents and the revision has parents..
        # i.e. a ghost.
        repo = self.make_repository("inventory_one_ghost")
        add_commit(repo, b"ghost", [b"the_ghost"])

        # a inventory with a ghost that can be corrected now.
        t.copy_tree("inventory_one_ghost", "inventory_ghost_present")
        bzrdir_url = self.get_url("inventory_ghost_present")
        bzrdir = BzrDir.open(bzrdir_url)
        repo = bzrdir.open_repository()
        add_commit(repo, b"the_ghost", [])

    def checkEmptyReconcile(self, **kwargs):
        """Check a reconcile on an empty repository."""
        self.make_repository("empty")
        d = BzrDir.open(self.get_url("empty"))
        # calling on a empty repository should do nothing
        result = d.find_repository().reconcile(**kwargs)
        # no inconsistent parents should have been found
        self.assertEqual(0, result.inconsistent_parents)
        # and no garbage inventories
        self.assertEqual(0, result.garbage_inventories)
        # and no backup weave should have been needed/made.
        self.checkNoBackupInventory(d)

    def test_reconcile_empty(self):
        # in an empty repo, theres nothing to do.
        self.checkEmptyReconcile()

    def test_repo_has_reconcile_does_inventory_gc_attribute(self):
        repo = self.make_repository("repo")
        self.assertNotEqual(None, repo._reconcile_does_inventory_gc)

    def test_reconcile_empty_thorough(self):
        # reconcile should accept thorough=True
        self.checkEmptyReconcile(thorough=True)

    def test_convenience_reconcile_inventory_without_revision_reconcile(self):
        # smoke test for the all in one ui tool
        bzrdir_url = self.get_url("inventory_without_revision")
        bzrdir = BzrDir.open(bzrdir_url)
        repo = bzrdir.open_repository()
        if not repo._reconcile_does_inventory_gc:
            raise TestSkipped("Irrelevant test")
        reconcile(bzrdir)
        # now the backup should have it but not the current inventory
        repo = bzrdir.open_repository()
        self.check_missing_was_removed(repo)

    def test_reweave_inventory_without_revision(self):
        # an excess inventory on its own is only reconciled by using thorough
        d_url = self.get_url("inventory_without_revision")
        d = BzrDir.open(d_url)
        repo = d.open_repository()
        if not repo._reconcile_does_inventory_gc:
            raise TestSkipped("Irrelevant test")
        self.checkUnreconciled(d, repo.reconcile())
        result = repo.reconcile(thorough=True)
        # no bad parents
        self.assertEqual(0, result.inconsistent_parents)
        # and one garbage inventory
        self.assertEqual(1, result.garbage_inventories)
        self.check_missing_was_removed(repo)

    def check_thorough_reweave_missing_revision(self, aBzrDir, reconcile, **kwargs):
        # actual low level test.
        repo = aBzrDir.open_repository()
        if not repo.has_revision(b"missing"):
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
        self.assertEqual(expected_inconsistent_parents, reconciler.inconsistent_parents)
        # and one garbage inventories
        self.assertEqual(1, reconciler.garbage_inventories)
        # now the backup should have it but not the current inventory
        repo = aBzrDir.open_repository()
        self.check_missing_was_removed(repo)
        # and the parent list for 'references_missing' should have that
        # revision a ghost now.
        self.assertFalse(repo.has_revision(b"missing"))

    def check_missing_was_removed(self, repo):
        if repo._reconcile_backsup_inventory:
            backed_up = False
            for path in repo.control_transport.list_dir("."):
                if "inventory.backup" in path:
                    backed_up = True
            self.assertTrue(backed_up)
            # Not clear how to do this at an interface level:
            # self.assertTrue('missing' in backup.versions())
        self.assertRaises(errors.NoSuchRevision, repo.get_inventory, "missing")

    def test_reweave_inventory_without_revision_reconciler(self):
        # smoke test for the all in one Reconciler class,
        # other tests use the lower level repo.reconcile()
        d_url = self.get_url("inventory_without_revision_and_ghost")
        d = BzrDir.open(d_url)
        if not d.open_repository()._reconcile_does_inventory_gc:
            raise TestSkipped("Irrelevant test")

        def reconcile():
            reconciler = Reconciler(d)
            return reconciler.reconcile()

        self.check_thorough_reweave_missing_revision(d, reconcile)

    def test_reweave_inventory_without_revision_and_ghost(self):
        # actual low level test.
        d_url = self.get_url("inventory_without_revision_and_ghost")
        d = BzrDir.open(d_url)
        repo = d.open_repository()
        if not repo._reconcile_does_inventory_gc:
            raise TestSkipped("Irrelevant test")
        # nothing should have been altered yet : inventories without
        # revisions are not data loss incurring for current format
        self.check_thorough_reweave_missing_revision(d, repo.reconcile, thorough=True)

    def test_reweave_inventory_preserves_a_revision_with_ghosts(self):
        d = BzrDir.open(self.get_url("inventory_one_ghost"))
        reconciler = d.open_repository().reconcile(thorough=True)
        # no inconsistent parents should have been found:
        # the lack of a parent for ghost is normal
        self.assertEqual(0, reconciler.inconsistent_parents)
        # and one garbage inventories
        self.assertEqual(0, reconciler.garbage_inventories)
        # now the current inventory should still have 'ghost'
        repo = d.open_repository()
        repo.get_inventory(b"ghost")
        self.assertThat([b"ghost", b"the_ghost"], MatchesAncestry(repo, b"ghost"))

    def test_reweave_inventory_fixes_ancestryfor_a_present_ghost(self):
        d = BzrDir.open(self.get_url("inventory_ghost_present"))
        repo = d.open_repository()
        m = MatchesAncestry(repo, b"ghost")
        if m.match([b"the_ghost", b"ghost"]) is None:
            # the repo handles ghosts without corruption, so reconcile has
            # nothing to do
            return
        self.assertThat([b"ghost"], m)
        reconciler = repo.reconcile()
        # this is a data corrupting error, so a normal reconcile should fix it.
        # one inconsistent parents should have been found : the
        # available but not reference parent for ghost.
        self.assertEqual(1, reconciler.inconsistent_parents)
        # and no garbage inventories
        self.assertEqual(0, reconciler.garbage_inventories)
        # now the current inventory should still have 'ghost'
        repo = d.open_repository()
        repo.get_inventory(b"ghost")
        repo.get_inventory(b"the_ghost")
        self.assertThat([b"the_ghost", b"ghost"], MatchesAncestry(repo, b"ghost"))
        self.assertThat([b"the_ghost"], MatchesAncestry(repo, b"the_ghost"))

    def test_text_from_ghost_revision(self):
        repo = self.make_repository("text-from-ghost")
        inv = Inventory(revision_id=b"final-revid")
        inv.root.revision = b"root-revid"
        ie = inv.add_path("bla", "file", b"myfileid")
        ie.revision = b"ghostrevid"
        ie.text_size = 42
        ie.text_sha1 = b"bee68c8acd989f5f1765b4660695275948bf5c00"
        rev = breezy.revision.Revision(
            timestamp=0,
            timezone=None,
            committer="Foo Bar <foo@example.com>",
            message="Message",
            revision_id=b"final-revid",
        )
        with repo.lock_write():
            repo.start_write_group()
            try:
                repo.add_revision(b"final-revid", rev, inv)
                try:
                    repo.texts.add_lines(
                        (b"myfileid", b"ghostrevid"),
                        ((b"myfileid", b"ghost-text-parent"),),
                        [b"line1\n", b"line2\n"],
                    )
                except errors.RevisionNotPresent:
                    raise TestSkipped("text ghost parents not supported")
                if repo.supports_rich_root():
                    repo.texts.add_lines((inv.root.file_id, inv.root.revision), [], [])
            finally:
                repo.commit_write_group()
        repo.reconcile(thorough=True)


class TestReconcileWithIncorrectRevisionCache(TestReconcile):
    """Ancestry data gets cached in knits and weaves should be reconcilable.

    This class tests that reconcile can correct invalid caches (such as after
    a reconcile).
    """

    def setUp(self):
        self.reduceLockdirTimeout()
        super().setUp()

        t = self.get_transport()
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
        self.first_tree = self.make_branch_and_tree("wrong-first-parent")
        self.second_tree = self.make_branch_and_tree("reversed-secondary-parents")
        for t in [self.first_tree, self.second_tree]:
            t.commit("1", rev_id=b"1")
            uncommit(t.branch, tree=t)
            t.commit("2", rev_id=b"2")
            uncommit(t.branch, tree=t)
            t.commit("3", rev_id=b"3")
            uncommit(t.branch, tree=t)
        # second_tree = self.make_branch_and_tree('reversed-secondary-parents')
        # second_tree.pull(tree) # XXX won't copy the repo?
        repo_secondary = self.second_tree.branch.repository

        # now setup the wrong-first parent case
        repo = self.first_tree.branch.repository
        repo.lock_write()
        repo.start_write_group()
        inv = Inventory(revision_id=b"wrong-first-parent")
        inv.root.revision = b"wrong-first-parent"
        if repo.supports_rich_root():
            root_id = inv.root.file_id
            repo.texts.add_lines((root_id, b"wrong-first-parent"), [], [])
        sha1 = repo.add_inventory(b"wrong-first-parent", inv, [b"2", b"1"])
        rev = Revision(
            timestamp=0,
            timezone=None,
            committer="Foo Bar <foo@example.com>",
            message="Message",
            inventory_sha1=sha1,
            revision_id=b"wrong-first-parent",
        )
        rev.parent_ids = [b"1", b"2"]
        repo.add_revision(b"wrong-first-parent", rev)
        repo.commit_write_group()
        repo.unlock()

        # now setup the wrong-secondary parent case
        repo = repo_secondary
        repo.lock_write()
        repo.start_write_group()
        inv = Inventory(revision_id=b"wrong-secondary-parent")
        inv.root.revision = b"wrong-secondary-parent"
        if repo.supports_rich_root():
            root_id = inv.root.file_id
            repo.texts.add_lines((root_id, b"wrong-secondary-parent"), [], [])
        sha1 = repo.add_inventory(b"wrong-secondary-parent", inv, [b"1", b"3", b"2"])
        rev = Revision(
            timestamp=0,
            timezone=None,
            committer="Foo Bar <foo@example.com>",
            message="Message",
            inventory_sha1=sha1,
            revision_id=b"wrong-secondary-parent",
        )
        rev.parent_ids = [b"1", b"2", b"3"]
        repo.add_revision(b"wrong-secondary-parent", rev)
        repo.commit_write_group()
        repo.unlock()

    def test_reconcile_wrong_order(self):
        # a wrong order in primary parents is optionally correctable
        repo = self.first_tree.branch.repository
        with repo.lock_read():
            g = repo.get_graph()
            if g.get_parent_map([b"wrong-first-parent"])[b"wrong-first-parent"] == (
                b"1",
                b"2",
            ):
                raise TestSkipped("wrong-first-parent is not setup for testing")
        self.checkUnreconciled(repo.controldir, repo.reconcile())
        # nothing should have been altered yet : inventories without
        # revisions are not data loss incurring for current format
        reconciler = repo.reconcile(thorough=True)
        # these show up as inconsistent parents
        self.assertEqual(1, reconciler.inconsistent_parents)
        # and no garbage inventories
        self.assertEqual(0, reconciler.garbage_inventories)
        # and should have been fixed:
        repo.lock_read()
        self.addCleanup(repo.unlock)
        g = repo.get_graph()
        self.assertEqual(
            {b"wrong-first-parent": (b"1", b"2")},
            g.get_parent_map([b"wrong-first-parent"]),
        )

    def test_reconcile_wrong_order_secondary_inventory(self):
        # a wrong order in the parents for inventories is ignored.
        repo = self.second_tree.branch.repository
        self.checkUnreconciled(repo.controldir, repo.reconcile())
        self.checkUnreconciled(repo.controldir, repo.reconcile(thorough=True))
