# Copyright (C) 2011, 2012, 2016 Canonical Ltd
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

import contextlib

from breezy import errors, gpg, tests
from breezy import repository as _mod_repository
from breezy import revision as _mod_revision
from breezy.bzr import vf_repository
from breezy.bzr.tests.per_repository_vf import (
    TestCaseWithRepository,
    all_repository_vf_format_scenarios,
)
from bzrformats import inventory, versionedfile

from ....tests.matchers import MatchesAncestry
from ....tests.scenarios import load_tests_apply_scenarios

load_tests = load_tests_apply_scenarios


class TestRepository(TestCaseWithRepository):
    scenarios = all_repository_vf_format_scenarios()

    def assertFormatAttribute(self, attribute, allowed_values):
        """Assert that the format has an attribute 'attribute'."""
        repo = self.make_repository("repo")
        self.assertSubset([getattr(repo._format, attribute)], allowed_values)

    def test_attribute__fetch_order(self):
        """Test the _fetch_order attribute."""
        self.assertFormatAttribute("_fetch_order", ("topological", "unordered"))

    def test_attribute__fetch_uses_deltas(self):
        """Test the _fetch_uses_deltas attribute."""
        self.assertFormatAttribute("_fetch_uses_deltas", (True, False))

    def test_attribute_inventories_store(self):
        """Test the existence of the inventories attribute."""
        tree = self.make_branch_and_tree("tree")
        repo = tree.branch.repository
        self.assertIsInstance(repo.inventories, versionedfile.VersionedFiles)

    def test_attribute_inventories_basics(self):
        """Test basic aspects of the inventories attribute."""
        tree = self.make_branch_and_tree("tree")
        repo = tree.branch.repository
        rev_id = (tree.commit("a"),)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual({rev_id}, set(repo.inventories.keys()))

    def test_attribute_revision_store(self):
        """Test the existence of the revisions attribute."""
        tree = self.make_branch_and_tree("tree")
        repo = tree.branch.repository
        self.assertIsInstance(repo.revisions, versionedfile.VersionedFiles)

    def test_attribute_revision_store_basics(self):
        """Test the basic behaviour of the revisions attribute."""
        tree = self.make_branch_and_tree("tree")
        repo = tree.branch.repository
        repo.lock_write()
        try:
            self.assertEqual(set(), set(repo.revisions.keys()))
            revid = (tree.commit("foo"),)
            self.assertEqual({revid}, set(repo.revisions.keys()))
            self.assertEqual({revid: ()}, repo.revisions.get_parent_map([revid]))
        finally:
            repo.unlock()
        tree2 = self.make_branch_and_tree("tree2")
        tree2.pull(tree.branch)
        left_id = (tree2.commit("left"),)
        right_id = (tree.commit("right"),)
        tree.merge_from_branch(tree2.branch)
        merge_id = (tree.commit("merged"),)
        repo.lock_read()
        self.addCleanup(repo.unlock)
        self.assertEqual(
            {revid, left_id, right_id, merge_id}, set(repo.revisions.keys())
        )
        self.assertEqual(
            {
                revid: (),
                left_id: (revid,),
                right_id: (revid,),
                merge_id: (right_id, left_id),
            },
            repo.revisions.get_parent_map(repo.revisions.keys()),
        )

    def test_attribute_signature_store(self):
        """Test the existence of the signatures attribute."""
        tree = self.make_branch_and_tree("tree")
        repo = tree.branch.repository
        self.assertIsInstance(repo.signatures, versionedfile.VersionedFiles)

    def test_exposed_versioned_files_are_marked_dirty(self):
        repo = self.make_repository(".")
        repo.lock_write()
        signatures = repo.signatures
        revisions = repo.revisions
        inventories = repo.inventories
        repo.unlock()
        self.assertRaises(errors.ObjectNotLocked, signatures.keys)
        self.assertRaises(errors.ObjectNotLocked, revisions.keys)
        self.assertRaises(errors.ObjectNotLocked, inventories.keys)
        self.assertRaises(
            errors.ObjectNotLocked, signatures.add_lines, ("foo",), [], []
        )
        self.assertRaises(errors.ObjectNotLocked, revisions.add_lines, ("foo",), [], [])
        self.assertRaises(
            errors.ObjectNotLocked, inventories.add_lines, ("foo",), [], []
        )

    def test__get_sink(self):
        repo = self.make_repository("repo")
        sink = repo._get_sink()
        self.assertIsInstance(sink, vf_repository.StreamSink)

    def test_get_serializer_format(self):
        repo = self.make_repository(".")
        format = repo.get_serializer_format()
        self.assertEqual(repo._inventory_serializer.format_num, format)

    def test_add_revision_inventory_sha1(self):
        inv = inventory.Inventory(revision_id=b"A")
        root = inventory.InventoryDirectory(b"fixed-root", "", None, b"A")
        inv.add(root)
        # Insert the inventory on its own to an identical repository, to get
        # its sha1.
        reference_repo = self.make_repository("reference_repo")
        reference_repo.lock_write()
        reference_repo.start_write_group()
        inv_sha1 = reference_repo.add_inventory(b"A", inv, [])
        reference_repo.abort_write_group()
        reference_repo.unlock()
        # Now insert a revision with this inventory, and it should get the same
        # sha1.
        repo = self.make_repository("repo")
        repo.lock_write()
        repo.start_write_group()
        repo.texts.add_lines((b"fixed-root", b"A"), [], [])
        repo.add_revision(
            b"A",
            _mod_revision.Revision(
                b"A",
                committer="B",
                timestamp=0,
                timezone=0,
                message="C",
                parent_ids=[],
                properties={},
                inventory_sha1=None,
            ),
            inv=inv,
        )
        repo.commit_write_group()
        repo.unlock()
        repo.lock_read()
        self.assertEqual(inv_sha1, repo.get_revision(b"A").inventory_sha1)
        repo.unlock()

    def test_install_revisions(self):
        wt = self.make_branch_and_tree("source")
        wt.commit("A", allow_pointless=True, rev_id=b"A")
        repo = wt.branch.repository
        repo.lock_write()
        repo.start_write_group()
        repo.sign_revision(b"A", gpg.LoopbackGPGStrategy(None))
        repo.commit_write_group()
        repo.unlock()
        repo.lock_read()
        self.addCleanup(repo.unlock)
        repo2 = self.make_repository("repo2")
        revision = repo.get_revision(b"A")
        tree = repo.revision_tree(b"A")
        signature = repo.get_signature_text(b"A")
        repo2.lock_write()
        self.addCleanup(repo2.unlock)
        vf_repository.install_revisions(repo2, [(revision, tree, signature)])
        self.assertEqual(revision, repo2.get_revision(b"A"))
        self.assertEqual(signature, repo2.get_signature_text(b"A"))

    def test_attribute_text_store(self):
        """Test the existence of the texts attribute."""
        tree = self.make_branch_and_tree("tree")
        repo = tree.branch.repository
        self.assertIsInstance(repo.texts, versionedfile.VersionedFiles)

    def test_iter_inventories_is_ordered(self):
        # just a smoke test
        tree = self.make_branch_and_tree("a")
        first_revision = tree.commit("")
        second_revision = tree.commit("")
        tree.lock_read()
        self.addCleanup(tree.unlock)
        revs = (first_revision, second_revision)
        invs = tree.branch.repository.iter_inventories(revs)
        for rev_id, inv in zip(revs, invs):
            self.assertEqual(rev_id, inv.revision_id)

    def test_item_keys_introduced_by(self):
        # Make a repo with one revision and one versioned file.
        tree = self.make_branch_and_tree("t")
        self.build_tree(["t/foo"])
        tree.add("foo", ids=b"file1")
        tree.commit("message", rev_id=b"rev_id")
        repo = tree.branch.repository
        repo.lock_write()
        repo.start_write_group()
        try:
            repo.sign_revision(b"rev_id", gpg.LoopbackGPGStrategy(None))
        except errors.UnsupportedOperation:
            signature_texts = []
        else:
            signature_texts = [b"rev_id"]
        repo.commit_write_group()
        repo.unlock()
        repo.lock_read()
        self.addCleanup(repo.unlock)

        # Item keys will be in this order, for maximum convenience for
        # generating data to insert into knit repository:
        #   * files
        #   * inventory
        #   * signatures
        #   * revisions
        expected_item_keys = [
            ("file", b"file1", [b"rev_id"]),
            ("inventory", None, [b"rev_id"]),
            ("signatures", None, signature_texts),
            ("revisions", None, [b"rev_id"]),
        ]
        item_keys = list(repo.item_keys_introduced_by([b"rev_id"]))
        item_keys = [
            (kind, file_id, list(versions)) for (kind, file_id, versions) in item_keys
        ]

        if repo.supports_rich_root():
            # Check for the root versioned file in the item_keys, then remove
            # it from streamed_names so we can compare that with
            # expected_record_names.
            # Note that the file keys can be in any order, so this test is
            # written to allow that.
            inv = repo.get_inventory(b"rev_id")
            root_item_key = ("file", inv.root.file_id, [b"rev_id"])
            self.assertIn(root_item_key, item_keys)
            item_keys.remove(root_item_key)

        self.assertEqual(expected_item_keys, item_keys)

    def test_attribute_text_store_basics(self):
        """Test the basic behaviour of the text store."""
        tree = self.make_branch_and_tree("tree")
        repo = tree.branch.repository
        file_id = b"Foo:Bar"
        file_key = (file_id,)
        with tree.lock_write():
            self.assertEqual(set(), set(repo.texts.keys()))
            tree.add(["foo"], ["file"], [file_id])
            tree.put_file_bytes_non_atomic("foo", b"content\n")
            try:
                rev_key = (tree.commit("foo"),)
            except errors.IllegalPath as e:
                raise tests.TestNotApplicable(
                    f"file_id {file_id!r} cannot be stored on this"
                    " platform for this repo format"
                ) from e
            if repo._format.rich_root_data:
                root_commit = (tree.path2id(""),) + rev_key
                keys = {root_commit}
                parents = {root_commit: ()}
            else:
                keys = set()
                parents = {}
            keys.add(file_key + rev_key)
            parents[file_key + rev_key] = ()
            self.assertEqual(keys, set(repo.texts.keys()))
            self.assertEqual(parents, repo.texts.get_parent_map(repo.texts.keys()))
        tree2 = self.make_branch_and_tree("tree2")
        tree2.pull(tree.branch)
        tree2.put_file_bytes_non_atomic("foo", b"right\n")
        right_key = (tree2.commit("right"),)
        keys.add(file_key + right_key)
        parents[file_key + right_key] = (file_key + rev_key,)
        tree.put_file_bytes_non_atomic("foo", b"left\n")
        left_key = (tree.commit("left"),)
        keys.add(file_key + left_key)
        parents[file_key + left_key] = (file_key + rev_key,)
        tree.merge_from_branch(tree2.branch)
        tree.put_file_bytes_non_atomic("foo", b"merged\n")
        with contextlib.suppress(errors.UnsupportedOperation):
            tree.auto_resolve()
        merge_key = (tree.commit("merged"),)
        keys.add(file_key + merge_key)
        parents[file_key + merge_key] = (file_key + left_key, file_key + right_key)
        repo.lock_read()
        self.addCleanup(repo.unlock)
        self.assertEqual(keys, set(repo.texts.keys()))
        self.assertEqual(parents, repo.texts.get_parent_map(repo.texts.keys()))


class TestCaseWithComplexRepository(TestCaseWithRepository):
    scenarios = all_repository_vf_format_scenarios()

    def setUp(self):
        super().setUp()
        tree_a = self.make_branch_and_tree("a")
        self.controldir = tree_a.branch.controldir
        # add a corrupt inventory 'orphan'
        # this may need some generalising for knits.
        with tree_a.lock_write(), _mod_repository.WriteGroup(tree_a.branch.repository):
            inv_file = tree_a.branch.repository.inventories
            inv_file.add_lines((b"orphan",), [], [])
        # add a real revision 'rev1'
        tree_a.commit("rev1", rev_id=b"rev1", allow_pointless=True)
        # add a real revision 'rev2' based on rev1
        tree_a.commit("rev2", rev_id=b"rev2", allow_pointless=True)
        # add a reference to a ghost
        tree_a.add_parent_tree_id(b"ghost1")
        try:
            tree_a.commit("rev3", rev_id=b"rev3", allow_pointless=True)
        except errors.RevisionNotPresent as e:
            raise tests.TestNotApplicable(
                "Cannot test with ghosts for this format."
            ) from e
        # add another reference to a ghost, and a second ghost.
        tree_a.add_parent_tree_id(b"ghost1")
        tree_a.add_parent_tree_id(b"ghost2")
        tree_a.commit("rev4", rev_id=b"rev4", allow_pointless=True)

    def test_revision_trees(self):
        revision_ids = [b"rev1", b"rev2", b"rev3", b"rev4"]
        repository = self.controldir.open_repository()
        repository.lock_read()
        self.addCleanup(repository.unlock)
        trees1 = list(repository.revision_trees(revision_ids))
        trees2 = [repository.revision_tree(t) for t in revision_ids]
        self.assertEqual(len(trees1), len(trees2))
        for tree1, tree2 in zip(trees1, trees2):
            self.assertFalse(tree2.changes_from(tree1).has_changed())

    def test_get_revision_deltas(self):
        repository = self.controldir.open_repository()
        repository.lock_read()
        self.addCleanup(repository.unlock)
        revisions = [
            repository.get_revision(r) for r in [b"rev1", b"rev2", b"rev3", b"rev4"]
        ]
        deltas1 = list(repository.get_revision_deltas(revisions))
        deltas2 = [repository.get_revision_delta(r.revision_id) for r in revisions]
        self.assertEqual(deltas1, deltas2)

    def test_all_revision_ids(self):
        # all_revision_ids -> all revisions
        self.assertEqual(
            {b"rev1", b"rev2", b"rev3", b"rev4"},
            set(self.controldir.open_repository().all_revision_ids()),
        )

    def test_reserved_id(self):
        repo = self.make_repository("repository")
        with repo.lock_write(), _mod_repository.WriteGroup(repo):
            self.assertRaises(
                errors.ReservedId, repo.add_inventory, b"reserved:", None, None
            )
            self.assertRaises(
                errors.ReservedId,
                repo.add_inventory_by_delta,
                "foo",
                [],
                b"reserved:",
                None,
            )
            self.assertRaises(errors.ReservedId, repo.add_revision, b"reserved:", None)


class TestCaseWithCorruptRepository(TestCaseWithRepository):
    scenarios = all_repository_vf_format_scenarios()

    def setUp(self):
        super().setUp()
        # a inventory with no parents and the revision has parents..
        # i.e. a ghost.
        repo = self.make_repository("inventory_with_unnecessary_ghost")
        repo.lock_write()
        repo.start_write_group()
        inv = inventory.Inventory(revision_id=b"ghost", root_id=None)
        root = inventory.InventoryDirectory(b"TREE_ROOT", "", None, b"ghost")
        inv.add(root)
        if repo.supports_rich_root():
            root_id = inv.root.file_id
            repo.texts.add_lines((root_id, b"ghost"), [], [])
        sha1 = repo.add_inventory(b"ghost", inv, [])
        rev = _mod_revision.Revision(
            timestamp=0,
            timezone=None,
            committer="Foo Bar <foo@example.com>",
            message="Message",
            inventory_sha1=sha1,
            revision_id=b"ghost",
            parent_ids=[b"the_ghost"],
            properties={},
        )
        try:
            repo.add_revision(b"ghost", rev)
        except (errors.NoSuchRevision, errors.RevisionNotPresent) as e:
            raise tests.TestNotApplicable(
                "Cannot test with ghosts for this format."
            ) from e

        inv = inventory.Inventory(revision_id=b"the_ghost", root_id=None)
        root = inventory.InventoryDirectory(b"TREE_ROOT", "", None, b"the_ghost")
        inv.add(root)
        if repo.supports_rich_root():
            root_id = inv.root.file_id
            repo.texts.add_lines((root_id, b"the_ghost"), [], [])
        sha1 = repo.add_inventory(b"the_ghost", inv, [])
        rev = _mod_revision.Revision(
            timestamp=0,
            timezone=None,
            committer="Foo Bar <foo@example.com>",
            message="Message",
            inventory_sha1=sha1,
            revision_id=b"the_ghost",
            properties={},
            parent_ids=[],
        )
        repo.add_revision(b"the_ghost", rev)
        # check its setup usefully
        inv_weave = repo.inventories
        possible_parents = (None, ((b"ghost",),))
        self.assertSubset(
            inv_weave.get_parent_map([(b"ghost",)])[(b"ghost",)], possible_parents
        )
        repo.commit_write_group()
        repo.unlock()

    def test_corrupt_revision_access_asserts_if_reported_wrong(self):
        repo_url = self.get_url("inventory_with_unnecessary_ghost")
        repo = _mod_repository.Repository.open(repo_url)
        m = MatchesAncestry(repo, b"ghost")
        reported_wrong = False
        try:
            if m.match([b"the_ghost", b"ghost"]) is not None:
                reported_wrong = True
        except errors.CorruptRepository:
            # caught the bad data:
            return
        if not reported_wrong:
            return
        self.assertRaises(errors.CorruptRepository, repo.get_revision, b"ghost")

    def test_corrupt_revision_get_revision_reconcile(self):
        repo_url = self.get_url("inventory_with_unnecessary_ghost")
        repo = _mod_repository.Repository.open(repo_url)
        repo.get_revision_reconcile(b"ghost")
