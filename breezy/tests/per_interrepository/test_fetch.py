# Copyright (C) 2008, 2009, 2010 Canonical Ltd
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

from breezy import errors, osutils, repository
from breezy.bzr import inventory, versionedfile
from breezy.bzr.vf_search import SearchResult
from breezy.errors import NoSuchRevision
from breezy.repository import WriteGroup
from breezy.revision import NULL_REVISION, Revision
from breezy.tests import TestNotApplicable
from breezy.tests.per_interrepository import TestCaseWithInterRepository
from breezy.tests.per_interrepository.test_interrepository import (
    check_repo_format_for_funky_id_on_win32,
)


class TestInterRepository(TestCaseWithInterRepository):
    def disable_commit_write_group_paranoia(self, repo):
        pack_coll = getattr(repo, "_pack_collection", None)
        if pack_coll is not None:
            # Monkey-patch the pack collection instance to allow storing
            # incomplete revisions.
            pack_coll._check_new_inventories = lambda: []

    def test_fetch(self):
        tree_a = self.make_branch_and_tree("a")
        self.build_tree(["a/foo"])
        tree_a.add("foo")
        rev1 = tree_a.commit("rev1")

        def check_push_rev1(repo):
            # ensure the revision is missing.
            self.assertRaises(NoSuchRevision, repo.get_revision, rev1)
            # fetch with a limit of NULL_REVISION
            repo.fetch(tree_a.branch.repository, revision_id=NULL_REVISION)
            # nothing should have been pushed
            self.assertFalse(repo.has_revision(rev1))
            # fetch with a default limit (grab everything)
            try:
                repo.fetch(tree_a.branch.repository)
            except errors.NoRoundtrippingSupport:
                raise TestNotApplicable("roundtripping not supported")
            # check that b now has all the data from a's first commit.
            repo.get_revision(rev1)
            tree = repo.revision_tree(rev1)
            tree.lock_read()
            self.addCleanup(tree.unlock)
            tree.get_file_text("foo")
            for path in tree.all_versioned_paths():
                if tree.kind(path) == "file":
                    with tree.get_file(path) as f:
                        f.read()

        # makes a target version repo
        repo_b = self.make_to_repository("b")
        check_push_rev1(repo_b)

    def test_fetch_inconsistent_last_changed_entries(self):
        """If an inventory has odd data we should still get what it references.

        This test tests that we do fetch a file text created in a revision not
        being fetched, but referenced from the revision we are fetching when the
        adjacent revisions to the one being fetched do not reference that text.
        """
        if not self.repository_format.supports_full_versioned_files:
            raise TestNotApplicable("Need full versioned files")
        tree = self.make_branch_and_tree("source")
        revid = tree.commit("old")
        to_repo = self.make_to_repository("to_repo")
        try:
            to_repo.fetch(tree.branch.repository, revid)
        except errors.NoRoundtrippingSupport:
            raise TestNotApplicable("roundtripping not supported")
        # Make a broken revision and fetch it.
        source = tree.branch.repository
        source.lock_write()
        self.addCleanup(source.unlock)
        with WriteGroup(source):
            # We need two revisions: OLD and NEW. NEW will claim to need a file
            # 'FOO' changed in 'OLD'. OLD will not have that file at all.
            source.texts.insert_record_stream(
                [
                    versionedfile.FulltextContentFactory(
                        (b"foo", revid), (), None, b"contents"
                    )
                ]
            )
            basis = source.revision_tree(revid)
            parent_id = basis.path2id("")
            entry = inventory.make_entry("file", "foo-path", parent_id, b"foo")
            entry.revision = revid
            entry.text_size = len("contents")
            entry.text_sha1 = osutils.sha_string(b"contents")
            inv_sha1, _ = source.add_inventory_by_delta(
                revid, [(None, "foo-path", b"foo", entry)], b"new", [revid]
            )
            rev = Revision(
                timestamp=0,
                timezone=None,
                committer="Foo Bar <foo@example.com>",
                message="Message",
                inventory_sha1=inv_sha1,
                revision_id=b"new",
                parent_ids=[revid],
            )
            source.add_revision(rev.revision_id, rev)
        to_repo.fetch(source, b"new")
        to_repo.lock_read()
        self.addCleanup(to_repo.unlock)
        self.assertEqual(
            b"contents",
            next(
                to_repo.texts.get_record_stream([(b"foo", revid)], "unordered", True)
            ).get_bytes_as("fulltext"),
        )

    def test_fetch_from_stacked_smart(self):
        self.setup_smart_server_with_call_log()
        self.test_fetch_from_stacked()

    def test_fetch_from_stacked_smart_old(self):
        self.setup_smart_server_with_call_log()
        self.disable_verb(b"Repository.get_stream_1.19")
        self.test_fetch_from_stacked()

    def test_fetch_from_stacked(self):
        """Fetch from a stacked branch succeeds."""
        if not self.repository_format.supports_external_lookups:
            raise TestNotApplicable("Need stacking support in the source.")
        builder = self.make_branch_builder("full-branch")
        builder.start_series()
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"root-id", "directory", "")),
                ("add", ("file", b"file-id", "file", b"content\n")),
            ],
            revision_id=b"first",
        )
        builder.build_snapshot(
            [b"first"],
            [("modify", ("file", b"second content\n"))],
            revision_id=b"second",
        )
        builder.build_snapshot(
            [b"second"],
            [("modify", ("file", b"third content\n"))],
            revision_id=b"third",
        )
        builder.finish_series()
        branch = builder.get_branch()
        repo = self.make_repository("stacking-base")
        trunk = repo.controldir.create_branch()
        trunk.repository.fetch(branch.repository, b"second")
        repo = self.make_repository("stacked")
        stacked_branch = repo.controldir.create_branch()
        stacked_branch.set_stacked_on_url(trunk.base)
        stacked_branch.repository.fetch(branch.repository, b"third")
        target = self.make_to_repository("target")
        try:
            target.fetch(stacked_branch.repository, b"third")
        except errors.NoRoundtrippingSupport:
            raise TestNotApplicable("roundtripping not supported")
        target.lock_read()
        self.addCleanup(target.unlock)
        all_revs = {b"first", b"second", b"third"}
        self.assertEqual(all_revs, set(target.get_parent_map(all_revs)))

    def test_fetch_parent_inventories_at_stacking_boundary_smart(self):
        self.setup_smart_server_with_call_log()
        self.test_fetch_parent_inventories_at_stacking_boundary()

    def test_fetch_parent_inventories_at_stacking_boundary_smart_old(self):
        self.setup_smart_server_with_call_log()
        self.disable_verb(b"Repository.insert_stream_1.19")
        try:
            self.test_fetch_parent_inventories_at_stacking_boundary()
        except errors.ConnectionReset:
            self.knownFailure("Random spurious failure, see bug 874153")

    def test_fetch_parent_inventories_at_stacking_boundary(self):
        """Fetch to a stacked branch copies inventories for parents of
        revisions at the stacking boundary.

        This is necessary so that the server is able to determine the file-ids
        altered by all revisions it contains, which means that it needs both
        the inventory for any revision it has, and the inventories of all that
        revision's parents.

        However, we should also skip any revisions which are ghosts in the
        parents.
        """
        if not self.repository_format_to.supports_external_lookups:
            raise TestNotApplicable("Need stacking support in the target.")
        builder = self.make_branch_builder("branch")
        builder.start_series()
        base = builder.build_snapshot(
            None,
            [
                ("add", ("", None, "directory", "")),
                ("add", ("file", None, "file", b"content\n")),
            ],
        )
        left = builder.build_snapshot([base], [("modify", ("file", b"left content\n"))])
        right = builder.build_snapshot(
            [base], [("modify", ("file", b"right content\n"))]
        )
        merge = builder.build_snapshot(
            [left, right], [("modify", ("file", b"left and right content\n"))]
        )
        builder.finish_series()
        branch = builder.get_branch()
        revtree = branch.repository.revision_tree(merge)
        if not revtree.supports_file_ids:
            raise TestNotApplicable("from format does not support file ids")
        root_id = revtree.path2id("")
        file_id = revtree.path2id("file")

        repo = self.make_to_repository("trunk")
        trunk = repo.controldir.create_branch()
        trunk.repository.fetch(branch.repository, left)
        trunk.repository.fetch(branch.repository, right)
        repo = self.make_to_repository("stacked")
        stacked_branch = repo.controldir.create_branch()
        stacked_branch.set_stacked_on_url(trunk.base)
        stacked_branch.repository.fetch(branch.repository, merge)
        unstacked_repo = stacked_branch.controldir.open_repository()
        unstacked_repo.lock_read()
        self.addCleanup(unstacked_repo.unlock)
        self.assertFalse(unstacked_repo.has_revision(left))
        self.assertFalse(unstacked_repo.has_revision(right))
        self.assertEqual(
            {(left,), (right,), (merge,)}, unstacked_repo.inventories.keys()
        )
        # And the basis inventories have been copied correctly
        trunk.lock_read()
        self.addCleanup(trunk.unlock)
        left_tree, right_tree = trunk.repository.revision_trees([left, right])
        stacked_branch.lock_read()
        self.addCleanup(stacked_branch.unlock)
        (stacked_left_tree, stacked_right_tree) = (
            stacked_branch.repository.revision_trees([left, right])
        )
        self.assertEqual(left_tree.root_inventory, stacked_left_tree.root_inventory)
        self.assertEqual(right_tree.root_inventory, stacked_right_tree.root_inventory)

        # Finally, it's not enough to see that the basis inventories are
        # present.  The texts introduced in merge (and only those) should be
        # present, and also generating a stream should succeed without blowing
        # up.
        self.assertTrue(unstacked_repo.has_revision(merge))
        expected_texts = {(file_id, merge)}
        if stacked_branch.repository.texts.get_parent_map([(root_id, merge)]):
            # If a (root-id,merge) text exists, it should be in the stacked
            # repo.
            expected_texts.add((root_id, merge))
        self.assertEqual(expected_texts, unstacked_repo.texts.keys())
        self.assertCanStreamRevision(unstacked_repo, merge)

    def assertCanStreamRevision(self, repo, revision_id):
        exclude_keys = set(repo.all_revision_ids()) - {revision_id}
        search = SearchResult([revision_id], exclude_keys, 1, [revision_id])
        source = repo._get_source(repo._format)
        for _substream_kind, substream in source.get_stream(search):
            # Consume the substream
            list(substream)

    def test_fetch_across_stacking_boundary_ignores_ghost(self):
        if not self.repository_format_to.supports_external_lookups:
            raise TestNotApplicable("Need stacking support in the target.")
        if not self.repository_format.supports_ghosts:
            raise TestNotApplicable("Need ghost support in the source.")
        self.make_to_repository("to")
        builder = self.make_branch_builder("branch")
        builder.start_series()
        base = builder.build_snapshot(
            None,
            [
                ("add", ("", None, "directory", "")),
                ("add", ("file", None, "file", b"content\n")),
            ],
        )
        second = builder.build_snapshot(
            [base], [("modify", ("file", b"second content\n"))]
        )
        third = builder.build_snapshot(
            [second, b"ghost"], [("modify", ("file", b"third content\n"))]
        )
        builder.finish_series()
        branch = builder.get_branch()
        revtree = branch.repository.revision_tree(base)
        root_id = revtree.path2id("")
        file_id = revtree.path2id("file")
        repo = self.make_to_repository("trunk")
        trunk = repo.controldir.create_branch()
        trunk.repository.fetch(branch.repository, second)
        repo = self.make_to_repository("stacked")
        stacked_branch = repo.controldir.create_branch()
        stacked_branch.set_stacked_on_url(trunk.base)
        stacked_branch.repository.fetch(branch.repository, third)
        unstacked_repo = stacked_branch.controldir.open_repository()
        unstacked_repo.lock_read()
        self.addCleanup(unstacked_repo.unlock)
        self.assertFalse(unstacked_repo.has_revision(second))
        self.assertFalse(unstacked_repo.has_revision(b"ghost"))
        self.assertEqual({(second,), (third,)}, unstacked_repo.inventories.keys())
        # And the basis inventories have been copied correctly
        trunk.lock_read()
        self.addCleanup(trunk.unlock)
        second_tree = trunk.repository.revision_tree(second)
        stacked_branch.lock_read()
        self.addCleanup(stacked_branch.unlock)
        stacked_second_tree = stacked_branch.repository.revision_tree(second)
        self.assertEqual(second_tree, stacked_second_tree)
        # Finally, it's not enough to see that the basis inventories are
        # present.  The texts introduced in merge (and only those) should be
        # present, and also generating a stream should succeed without blowing
        # up.
        self.assertTrue(unstacked_repo.has_revision(third))
        expected_texts = {(file_id, third)}
        if stacked_branch.repository.texts.get_parent_map([(root_id, third)]):
            # If a (root-id,third) text exists, it should be in the stacked
            # repo.
            expected_texts.add((root_id, third))
        self.assertEqual(expected_texts, unstacked_repo.texts.keys())
        self.assertCanStreamRevision(unstacked_repo, third)

    def test_fetch_from_stacked_to_stacked_copies_parent_inventories(self):
        """Fetch from a stacked branch copies inventories for parents of
        revisions at the stacking boundary.

        Specifically, fetch will copy the parent inventories from the
        source for which the corresponding revisions are not present.  This
        will happen even when the source repository has no fallbacks configured
        (as is the case during upgrade).
        """
        if not self.repository_format.supports_external_lookups:
            raise TestNotApplicable("Need stacking support in the source.")
        if not self.repository_format_to.supports_external_lookups:
            raise TestNotApplicable("Need stacking support in the target.")
        builder = self.make_branch_builder("branch")
        builder.start_series()
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"root-id", "directory", "")),
                ("add", ("file", b"file-id", "file", b"content\n")),
            ],
            revision_id=b"base",
        )
        builder.build_snapshot(
            [b"base"], [("modify", ("file", b"left content\n"))], revision_id=b"left"
        )
        builder.build_snapshot(
            [b"base"], [("modify", ("file", b"right content\n"))], revision_id=b"right"
        )
        builder.build_snapshot(
            [b"left", b"right"],
            [("modify", ("file", b"left and right content\n"))],
            revision_id=b"merge",
        )
        builder.finish_series()
        branch = builder.get_branch()
        repo = self.make_repository("old-trunk")
        # Make a pair of equivalent trunk repos in the from and to formats.
        old_trunk = repo.controldir.create_branch()
        old_trunk.repository.fetch(branch.repository, b"left")
        old_trunk.repository.fetch(branch.repository, b"right")
        repo = self.make_to_repository("new-trunk")
        new_trunk = repo.controldir.create_branch()
        new_trunk.repository.fetch(branch.repository, b"left")
        new_trunk.repository.fetch(branch.repository, b"right")
        # Make the source; a repo stacked on old_trunk contained just the data
        # for 'merge'.
        repo = self.make_repository("old-stacked")
        old_stacked_branch = repo.controldir.create_branch()
        old_stacked_branch.set_stacked_on_url(old_trunk.base)
        old_stacked_branch.repository.fetch(branch.repository, b"merge")
        # Make the target, a repo stacked on new_trunk.
        repo = self.make_to_repository("new-stacked")
        new_stacked_branch = repo.controldir.create_branch()
        new_stacked_branch.set_stacked_on_url(new_trunk.base)
        old_unstacked_repo = old_stacked_branch.controldir.open_repository()
        new_unstacked_repo = new_stacked_branch.controldir.open_repository()
        # Reopen the source and target repos without any fallbacks, and fetch
        # 'merge'.
        new_unstacked_repo.fetch(old_unstacked_repo, b"merge")
        # Now check the results.  new_unstacked_repo should contain all the
        # data necessary to stream 'merge' (i.e. the parent inventories).
        new_unstacked_repo.lock_read()
        self.addCleanup(new_unstacked_repo.unlock)
        self.assertFalse(new_unstacked_repo.has_revision(b"left"))
        self.assertFalse(new_unstacked_repo.has_revision(b"right"))
        self.assertEqual(
            {(b"left",), (b"right",), (b"merge",)},
            new_unstacked_repo.inventories.keys(),
        )
        # And the basis inventories have been copied correctly
        new_trunk.lock_read()
        self.addCleanup(new_trunk.unlock)
        left_tree, right_tree = new_trunk.repository.revision_trees([b"left", b"right"])
        new_stacked_branch.lock_read()
        self.addCleanup(new_stacked_branch.unlock)
        (stacked_left_tree, stacked_right_tree) = (
            new_stacked_branch.repository.revision_trees([b"left", b"right"])
        )
        self.assertEqual(left_tree, stacked_left_tree)
        self.assertEqual(right_tree, stacked_right_tree)
        # Finally, it's not enough to see that the basis inventories are
        # present.  The texts introduced in merge (and only those) should be
        # present, and also generating a stream should succeed without blowing
        # up.
        self.assertTrue(new_unstacked_repo.has_revision(b"merge"))
        expected_texts = {(b"file-id", b"merge")}
        if new_stacked_branch.repository.texts.get_parent_map([(b"root-id", b"merge")]):
            # If a (root-id,merge) text exists, it should be in the stacked
            # repo.
            expected_texts.add((b"root-id", b"merge"))
        self.assertEqual(expected_texts, new_unstacked_repo.texts.keys())
        self.assertCanStreamRevision(new_unstacked_repo, b"merge")

    def test_fetch_missing_basis_text(self):
        """If fetching a delta, we should die if a basis is not present."""
        if not self.repository_format.supports_full_versioned_files:
            raise TestNotApplicable("Need full versioned files support")
        if not self.repository_format_to.supports_full_versioned_files:
            raise TestNotApplicable("Need full versioned files support")
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/a"])
        tree.add(["a"])
        rev1 = tree.commit("one")
        self.build_tree_contents([("tree/a", b"new contents\n")])
        rev2 = tree.commit("two")

        to_repo = self.make_to_repository("to_repo")
        # We build a broken revision so that we can test the fetch code dies
        # properly. So copy the inventory and revision, but not the text.
        with to_repo.lock_write(), WriteGroup(to_repo, suppress_errors=True):
            inv = tree.branch.repository.get_inventory(rev1)
            to_repo.add_inventory(rev1, inv, [])
            rev = tree.branch.repository.get_revision(rev1)
            to_repo.add_revision(rev1, rev, inv=inv)
            self.disable_commit_write_group_paranoia(to_repo)

        # Implementations can either ensure that the target of the delta is
        # reconstructable, or raise an exception (which stream based copies
        # generally do).
        try:
            to_repo.fetch(tree.branch.repository, rev2)
        except (errors.BzrCheckError, errors.RevisionNotPresent):
            # If an exception is raised, the revision should not be in the
            # target.
            #
            # Can also just raise a generic check errors; stream insertion
            # does this to include all the missing data
            self.assertRaises(
                (errors.NoSuchRevision, errors.RevisionNotPresent),
                to_repo.revision_tree,
                rev2,
            )
        else:
            # If not exception is raised, then the text should be
            # available.
            with to_repo.lock_read():
                rt = to_repo.revision_tree(rev2)
                self.assertEqual(b"new contents\n", rt.get_file_text("a"))

    def test_fetch_missing_revision_same_location_fails(self):
        repo_a = self.make_repository(".")
        repo_b = repository.Repository.open(".")
        self.assertRaises(
            errors.NoSuchRevision, repo_b.fetch, repo_a, revision_id=b"XXX"
        )

    def test_fetch_same_location_trivial_works(self):
        repo_a = self.make_repository(".")
        repo_b = repository.Repository.open(".")
        repo_a.fetch(repo_b)

    def test_fetch_missing_text_other_location_fails(self):
        if not self.repository_format.supports_full_versioned_files:
            raise TestNotApplicable("Need full versioned files")

        source_tree = self.make_branch_and_tree("source")
        source = source_tree.branch.repository
        target = self.make_to_repository("target")

        # start by adding a file so the data knit for the file exists in
        # repositories that have specific files for each fileid.
        self.build_tree(["source/id"])
        source_tree.add(["id"], ids=[b"id"])
        source_tree.commit("a", rev_id=b"a")
        # now we manually insert a revision with an inventory referencing
        # file 'id' at revision 'b', but we do not insert revision b.
        # this should ensure that the new versions of files are being checked
        # for during pull operations
        inv = source.get_inventory(b"a")
        source.lock_write()
        self.addCleanup(source.unlock)
        source.start_write_group()
        inv.get_entry(b"id").revision = b"b"
        inv.revision_id = b"b"
        sha1 = source.add_inventory(b"b", inv, [b"a"])
        rev = Revision(
            timestamp=0,
            timezone=None,
            committer="Foo Bar <foo@example.com>",
            message="Message",
            inventory_sha1=sha1,
            revision_id=b"b",
        )
        rev.parent_ids = [b"a"]
        source.add_revision(b"b", rev)
        self.disable_commit_write_group_paranoia(source)
        source.commit_write_group()
        try:
            self.assertRaises(errors.RevisionNotPresent, target.fetch, source)
        except errors.NoRoundtrippingSupport:
            raise TestNotApplicable("roundtripping not supported")
        self.assertFalse(target.has_revision(b"b"))

    def test_fetch_funky_file_id(self):
        from_tree = self.make_branch_and_tree("tree")
        if sys.platform == "win32":
            from_repo = from_tree.branch.repository
            check_repo_format_for_funky_id_on_win32(from_repo)
        self.build_tree(["tree/filename"])
        if not from_tree.supports_setting_file_ids():
            raise TestNotApplicable("from tree format can not create custom file ids")
        from_tree.add("filename", ids=b"funky-chars<>%&;\"'")
        from_tree.commit("commit filename")
        to_repo = self.make_to_repository("to")
        try:
            to_repo.fetch(from_tree.branch.repository, from_tree.get_parent_ids()[0])
        except errors.NoRoundtrippingSupport:
            raise TestNotApplicable("roundtripping not supported")

    def test_fetch_revision_hash(self):
        """Ensure that inventory hashes are updated by fetch."""
        if not self.repository_format_to.supports_full_versioned_files:
            raise TestNotApplicable("Need full versioned files")
        from_tree = self.make_branch_and_tree("tree")
        revid = from_tree.commit("foo")
        to_repo = self.make_to_repository("to")
        try:
            to_repo.fetch(from_tree.branch.repository)
        except errors.NoRoundtrippingSupport:
            raise TestNotApplicable("roundtripping not supported")
        recorded_inv_sha1 = to_repo.get_revision(revid).inventory_sha1
        to_repo.lock_read()
        self.addCleanup(to_repo.unlock)
        stream = to_repo.inventories.get_record_stream([(revid,)], "unordered", True)
        bytes = next(stream).get_bytes_as("fulltext")
        computed_inv_sha1 = osutils.sha_string(bytes)
        self.assertEqual(computed_inv_sha1, recorded_inv_sha1)


class TestFetchDependentData(TestCaseWithInterRepository):
    def test_reference(self):
        from_tree = self.make_branch_and_tree("tree")
        to_repo = self.make_to_repository("to")
        if (
            not from_tree.supports_tree_reference()
            or not from_tree.branch.repository._format.supports_tree_reference
            or not to_repo._format.supports_tree_reference
        ):
            raise TestNotApplicable("Need subtree support.")
        if not to_repo._format.supports_full_versioned_files:
            raise TestNotApplicable("Need full versioned files support.")
        subtree = self.make_branch_and_tree("tree/subtree")
        subtree.commit("subrev 1")
        from_tree.add_reference(subtree)
        tree_rev = from_tree.commit("foo")
        # now from_tree has a last-modified of subtree of the rev id of the
        # commit for foo, and a reference revision of the rev id of the commit
        # for subrev 1
        to_repo.fetch(from_tree.branch.repository, tree_rev)
        # to_repo should have a file_graph for from_tree.path2id('subtree') and
        # revid tree_rev.
        if from_tree.supports_file_ids:
            file_id = from_tree.path2id("subtree")
            with to_repo.lock_read():
                self.assertEqual(
                    {(file_id, tree_rev): ()},
                    to_repo.texts.get_parent_map([(file_id, tree_rev)]),
                )
