# Copyright (C) 2006-2012, 2016 Canonical Ltd
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

"""Tests for repository commit builder."""

import os

from breezy import errors, osutils, repository, tests
from breezy import revision as _mod_revision
from breezy.bzr import inventorytree
from breezy.bzr.inventorytree import InventoryTreeChange
from breezy.tests import features, per_repository

from ..test_bedding import override_whoami


class TestCommitBuilder(per_repository.TestCaseWithRepository):
    def test_get_commit_builder(self):
        branch = self.make_branch(".")
        branch.repository.lock_write()
        builder = branch.repository.get_commit_builder(
            branch, [], branch.get_config_stack()
        )
        self.assertIsInstance(builder, repository.CommitBuilder)
        self.assertTrue(builder.random_revid)
        branch.repository.commit_write_group()
        branch.repository.unlock()

    def test_finish_inventory_record_iter_changes(self):
        tree = self.make_branch_and_tree(".")
        with tree.lock_write():
            builder = tree.branch.get_commit_builder([])
            try:
                list(
                    builder.record_iter_changes(
                        tree, tree.last_revision(), tree.iter_changes(tree.basis_tree())
                    )
                )
                builder.finish_inventory()
            except:
                builder.abort()
                raise
            repo = tree.branch.repository
            repo.commit_write_group()

    def test_abort_record_iter_changes(self):
        tree = self.make_branch_and_tree(".")
        with tree.lock_write():
            builder = tree.branch.get_commit_builder([])
            try:
                basis = tree.basis_tree()
                last_rev = tree.last_revision()
                changes = tree.iter_changes(basis)
                list(builder.record_iter_changes(tree, last_rev, changes))
                builder.finish_inventory()
            finally:
                builder.abort()

    def test_commit_lossy(self):
        tree = self.make_branch_and_tree(".")
        with tree.lock_write():
            builder = tree.branch.get_commit_builder([], lossy=True)
            list(
                builder.record_iter_changes(
                    tree, tree.last_revision(), tree.iter_changes(tree.basis_tree())
                )
            )
            builder.finish_inventory()
            rev_id = builder.commit("foo bar blah")
        rev = tree.branch.repository.get_revision(rev_id)
        self.assertEqual("foo bar blah", rev.message)

    def test_commit_message(self):
        tree = self.make_branch_and_tree(".")
        with tree.lock_write():
            builder = tree.branch.get_commit_builder([])
            list(
                builder.record_iter_changes(
                    tree, tree.last_revision(), tree.iter_changes(tree.basis_tree())
                )
            )
            builder.finish_inventory()
            rev_id = builder.commit("foo bar blah")
        rev = tree.branch.repository.get_revision(rev_id)
        self.assertEqual("foo bar blah", rev.message)

    def test_updates_branch(self):
        tree = self.make_branch_and_tree(".")
        with tree.lock_write():
            builder = tree.branch.get_commit_builder([])
            list(
                builder.record_iter_changes(
                    tree, tree.last_revision(), tree.iter_changes(tree.basis_tree())
                )
            )
            builder.finish_inventory()
            will_update_branch = builder.updates_branch
            rev_id = builder.commit("might update the branch")
        actually_updated_branch = tree.branch.last_revision() == rev_id
        self.assertEqual(actually_updated_branch, will_update_branch)

    def test_commit_with_revision_id_record_iter_changes(self):
        tree = self.make_branch_and_tree(".")
        with tree.lock_write():
            # use a unicode revision id to test more corner cases.
            # The repository layer is meant to handle this.
            revision_id = "\xc8abc".encode()
            try:
                try:
                    builder = tree.branch.get_commit_builder(
                        [], revision_id=revision_id
                    )
                except errors.NonAsciiRevisionId:
                    revision_id = b"abc"
                    builder = tree.branch.get_commit_builder(
                        [], revision_id=revision_id
                    )
            except repository.CannotSetRevisionId:
                # This format doesn't support supplied revision ids
                return
            self.assertFalse(builder.random_revid)
            try:
                list(
                    builder.record_iter_changes(
                        tree, tree.last_revision(), tree.iter_changes(tree.basis_tree())
                    )
                )
                builder.finish_inventory()
            except:
                builder.abort()
                raise
            self.assertEqual(revision_id, builder.commit("foo bar"))
        self.assertTrue(tree.branch.repository.has_revision(revision_id))
        # the revision id must be set on the inventory when saving it. This
        # does not precisely test that - a repository that wants to can add it
        # on deserialisation, but thats all the current contract guarantees
        # anyway.
        self.assertEqual(
            revision_id,
            tree.branch.repository.revision_tree(revision_id).get_revision_id(),
        )

    def test_commit_without_root_errors(self):
        tree = self.make_branch_and_tree(".")
        with tree.lock_write():
            builder = tree.branch.get_commit_builder([])

            def do_commit():
                try:
                    list(builder.record_iter_changes(tree, tree.last_revision(), []))
                    builder.finish_inventory()
                except:
                    builder.abort()
                    raise
                else:
                    builder.commit("msg")

            self.assertRaises(errors.RootMissing, do_commit)

    def test_commit_unchanged_root_record_iter_changes(self):
        tree = self.make_branch_and_tree(".")
        old_revision_id = tree.commit("oldrev")
        tree.lock_write()
        builder = tree.branch.get_commit_builder([old_revision_id])
        try:
            list(builder.record_iter_changes(tree, old_revision_id, []))
            # Regardless of repository root behaviour we should consider this a
            # pointless commit.
            self.assertFalse(builder.any_changes())
            builder.finish_inventory()
            builder.commit("rev")
            builder_tree = builder.revision_tree()
            new_root_revision = builder_tree.get_file_revision("")
            if tree.branch.repository.supports_rich_root():
                # We should not have seen a new root revision
                self.assertEqual(old_revision_id, new_root_revision)
            else:
                # We should see a new root revision
                self.assertNotEqual(old_revision_id, new_root_revision)
        finally:
            tree.unlock()

    def test_record_delete_record_iter_changes(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree(["foo"])
        tree.add(["foo"])
        foo_id = tree.path2id("foo")
        rev_id = tree.commit("added foo")
        with tree.lock_write():
            builder = tree.branch.get_commit_builder([rev_id])
            try:
                delete_change = InventoryTreeChange(
                    foo_id,
                    ("foo", None),
                    True,
                    (True, False),
                    (tree.path2id(""), None),
                    ("foo", None),
                    ("file", None),
                    (False, None),
                )
                list(builder.record_iter_changes(tree, rev_id, [delete_change]))
                self.assertEqual(
                    ("foo", None, foo_id, None), builder.get_basis_delta()[0]
                )
                self.assertTrue(builder.any_changes())
                builder.finish_inventory()
                builder.commit("delete foo")
            except:
                builder.abort()
                raise
        rev_tree = builder.revision_tree()
        rev_tree.lock_read()
        self.addCleanup(rev_tree.unlock)
        self.assertFalse(rev_tree.is_versioned("foo"))

    def test_revision_tree_record_iter_changes(self):
        tree = self.make_branch_and_tree(".")
        with tree.lock_write():
            builder = tree.branch.get_commit_builder([])
            try:
                list(
                    builder.record_iter_changes(
                        tree,
                        _mod_revision.NULL_REVISION,
                        tree.iter_changes(tree.basis_tree()),
                    )
                )
                builder.finish_inventory()
                rev_id = builder.commit("foo bar")
            except:
                builder.abort()
                raise
            rev_tree = builder.revision_tree()
            # Just a couple simple tests to ensure that it actually follows
            # the RevisionTree api.
            self.assertEqual(rev_id, rev_tree.get_revision_id())
            self.assertEqual((), tuple(rev_tree.get_parent_ids()))

    def test_root_entry_has_revision(self):
        # test the root revision created and put in the basis
        # has the right rev id.
        # XXX: RBC 20081118 - this test is too big, it depends on the exact
        # behaviour of tree methods and so on; it should be written to the
        # commit builder interface directly.
        tree = self.make_branch_and_tree(".")
        rev_id = tree.commit("message")
        basis_tree = tree.basis_tree()
        basis_tree.lock_read()
        self.addCleanup(basis_tree.unlock)
        self.assertEqual(rev_id, basis_tree.get_file_revision(""))

    def _get_revtrees(self, tree, revision_ids):
        with tree.lock_read():
            trees = list(tree.branch.repository.revision_trees(revision_ids))
            for _tree in trees:
                _tree.lock_read()
                self.addCleanup(_tree.unlock)
            return trees

    def test_last_modified_revision_after_commit_root_unchanged(self):
        # commiting without changing the root does not change the
        # last modified except on non-rich-root-repositories.
        tree = self.make_branch_and_tree(".")
        rev1 = tree.commit("rev1")
        rev2 = tree.commit("rev2")
        tree1, tree2 = self._get_revtrees(tree, [rev1, rev2])
        self.assertEqual(rev1, tree1.get_file_revision(""))
        if tree.branch.repository.supports_rich_root():
            self.assertEqual(rev1, tree2.get_file_revision(""))
        else:
            self.assertEqual(rev2, tree2.get_file_revision(""))

    def _add_commit_check_unchanged(self, tree, name):
        tree.add([name])
        if tree.supports_file_ids:
            file_id = tree.path2id(name)
        else:
            file_id = None
        self._commit_check_unchanged(tree, name, file_id)

    def _commit_check_unchanged(self, tree, name, file_id):
        rev1 = tree.commit("rev1")
        rev2 = self.mini_commit_record_iter_changes(tree, name, name, False, False)
        tree1, tree2 = self._get_revtrees(tree, [rev1, rev2])
        self.assertEqual(rev1, tree1.get_file_revision(name))
        self.assertEqual(rev1, tree2.get_file_revision(name))
        if tree.supports_file_ids:
            expected_graph = {}
            expected_graph[(file_id, rev1)] = ()
            self.assertFileGraph(expected_graph, tree, (file_id, rev1))

    def test_last_modified_revision_after_commit_dir_unchanged(self):
        # committing without changing a dir does not change the last modified.
        tree = self.make_branch_and_tree(".")
        if not tree.has_versioned_directories():
            raise tests.TestNotApplicable(
                "Format does not support versioned directories"
            )
        self.build_tree(["dir/"])
        self._add_commit_check_unchanged(tree, "dir")

    def test_last_modified_revision_after_commit_dir_contents_unchanged(self):
        # committing without changing a dir does not change the last modified
        # of the dir even the dirs contents are changed.
        tree = self.make_branch_and_tree(".")
        self.build_tree(["dir/", "dir/orig"])
        tree.add(["dir", "dir/orig"])
        rev1 = tree.commit("rev1")
        self.build_tree(["dir/content"])
        tree.add(["dir/content"])
        rev2 = tree.commit("rev2")
        tree1, tree2 = self._get_revtrees(tree, [rev1, rev2])
        self.assertEqual(rev1, tree1.get_file_revision("dir"))
        self.assertEqual(rev1, tree2.get_file_revision("dir"))
        if tree.supports_file_ids:
            dir_id = tree1.path2id("dir")
            expected_graph = {(dir_id, rev1): ()}
            self.assertFileGraph(expected_graph, tree, (dir_id, rev1))

    def test_last_modified_revision_after_commit_file_unchanged(self):
        # committing without changing a file does not change the last modified.
        tree = self.make_branch_and_tree(".")
        self.build_tree(["file"])
        self._add_commit_check_unchanged(tree, "file")

    def test_last_modified_revision_after_commit_link_unchanged(self):
        # committing without changing a link does not change the last modified.
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        tree = self.make_branch_and_tree(".")
        os.symlink("target", "link")
        self._add_commit_check_unchanged(tree, "link")

    def test_last_modified_revision_after_commit_reference_unchanged(self):
        # committing without changing a subtree does not change the last
        # modified.
        tree = self.make_branch_and_tree(".")
        subtree = self.make_reference("reference")
        subtree.commit("")
        try:
            tree.add_reference(subtree)
            self._commit_check_unchanged(
                tree,
                "reference",
                subtree.path2id("") if subtree.supports_file_ids else None,
            )
        except errors.UnsupportedOperation:
            return

    def _add_commit_renamed_check_changed(self, tree, name, expect_fs_hash=False):
        def rename():
            tree.rename_one(name, "new_" + name)

        self._add_commit_change_check_changed(
            tree, (name, "new_" + name), rename, expect_fs_hash=expect_fs_hash
        )

    def _commit_renamed_check_changed(self, tree, name, expect_fs_hash=False):
        def rename():
            tree.rename_one(name, "new_" + name)

        self._commit_change_check_changed(
            tree, [name, "new_" + name], rename, expect_fs_hash=expect_fs_hash
        )

    def test_last_modified_revision_after_rename_dir_changes(self):
        # renaming a dir changes the last modified.
        tree = self.make_branch_and_tree(".")
        if not tree.has_versioned_directories():
            raise tests.TestNotApplicable(
                "Format does not support versioned directories"
            )
        self.build_tree(["dir/"])
        self._add_commit_renamed_check_changed(tree, "dir")

    def test_last_modified_revision_after_rename_file_changes(self):
        # renaming a file changes the last modified.
        tree = self.make_branch_and_tree(".")
        self.build_tree(["file"])
        self._add_commit_renamed_check_changed(tree, "file", expect_fs_hash=True)

    def test_last_modified_revision_after_rename_link_changes(self):
        # renaming a link changes the last modified.
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        tree = self.make_branch_and_tree(".")
        os.symlink("target", "link")
        self._add_commit_renamed_check_changed(tree, "link")

    def test_last_modified_revision_after_rename_ref_changes(self):
        # renaming a reference changes the last modified.
        tree = self.make_branch_and_tree(".")
        subtree = self.make_reference("reference")
        subtree.commit("")
        try:
            tree.add_reference(subtree)
            self._commit_renamed_check_changed(tree, "reference")
        except errors.UnsupportedOperation:
            return

    def _add_commit_reparent_check_changed(self, tree, name, expect_fs_hash=False):
        self.build_tree(["newparent/"])
        tree.add(["newparent"])

        def reparent():
            tree.rename_one(name, "newparent/new_" + name)

        self._add_commit_change_check_changed(
            tree,
            (name, "newparent/new_" + name),
            reparent,
            expect_fs_hash=expect_fs_hash,
        )

    def test_last_modified_revision_after_reparent_dir_changes(self):
        # reparenting a dir changes the last modified.
        tree = self.make_branch_and_tree(".")
        if not tree.has_versioned_directories():
            raise tests.TestNotApplicable(
                "Format does not support versioned directories"
            )
        self.build_tree(["dir/"])
        self._add_commit_reparent_check_changed(tree, "dir")

    def test_last_modified_revision_after_reparent_file_changes(self):
        # reparenting a file changes the last modified.
        tree = self.make_branch_and_tree(".")
        self.build_tree(["file"])
        self._add_commit_reparent_check_changed(tree, "file", expect_fs_hash=True)

    def test_last_modified_revision_after_reparent_link_changes(self):
        # reparenting a link changes the last modified.
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        tree = self.make_branch_and_tree(".")
        os.symlink("target", "link")
        self._add_commit_reparent_check_changed(tree, "link")

    def _add_commit_change_check_changed(
        self, tree, names, changer, expect_fs_hash=False
    ):
        tree.add([names[0]])
        self.assertTrue(tree.is_versioned(names[0]))
        self._commit_change_check_changed(
            tree, names, changer, expect_fs_hash=expect_fs_hash
        )

    def _commit_change_check_changed(self, tree, names, changer, expect_fs_hash=False):
        rev1 = tree.commit("rev1")
        changer()
        rev2 = self.mini_commit_record_iter_changes(
            tree, names[0], names[1], expect_fs_hash=expect_fs_hash
        )
        tree1, tree2 = self._get_revtrees(tree, [rev1, rev2])
        self.assertEqual(rev1, tree1.get_file_revision(names[0]))
        self.assertEqual(rev2, tree2.get_file_revision(names[1]))
        if tree1.supports_file_ids:
            file_id = tree1.path2id(names[0])
            expected_graph = {}
            expected_graph[(file_id, rev1)] = ()
            expected_graph[(file_id, rev2)] = ((file_id, rev1),)
            self.assertFileGraph(expected_graph, tree, (file_id, rev2))

    def mini_commit_record_iter_changes(
        self,
        tree,
        name,
        new_name,
        records_version=True,
        delta_against_basis=True,
        expect_fs_hash=False,
    ):
        """Perform a miniature commit looking for record entry results.

        This version uses the record_iter_changes interface.

        :param tree: The tree to commit.
        :param name: The path in the basis tree of the tree being committed.
        :param new_name: The path in the tree being committed.
        :param records_version: True if the commit of new_name is expected to
            record a new version.
        :param delta_against_basis: True of the commit of new_name is expected
            to have a delta against the basis.
        :param expect_fs_hash: If true, looks for a fs hash output from
            record_iter_changes.
        """
        with tree.lock_write():
            # mini manual commit here so we can check the return of
            # record_iter_changes
            parent_ids = tree.get_parent_ids()
            builder = tree.branch.get_commit_builder(parent_ids)
            try:
                parent_tree = tree.basis_tree()
                with parent_tree.lock_read():
                    changes = list(tree.iter_changes(parent_tree))
                result = list(builder.record_iter_changes(tree, parent_ids[0], changes))
                self.assertTrue(tree.is_versioned(new_name))
                if isinstance(tree, inventorytree.InventoryTree):
                    file_id = tree.path2id(new_name)
                    self.assertIsNot(None, file_id)
                    # TODO(jelmer): record_iter_changes shouldn't yield
                    # data that is WorkingTree-format-specific and uses file ids.
                    if expect_fs_hash:
                        tree_file_stat = tree.get_file_with_stat(new_name)
                        tree_file_stat[0].close()
                        self.assertLength(1, result)
                        result = result[0]
                        self.assertEqual(result[0], new_name)
                        self.assertEqual(result[1][0], tree.get_file_sha1(new_name))
                        self.assertEqualStat(result[1][1], tree_file_stat[1])
                    else:
                        self.assertEqual([], result)
                builder.finish_inventory()
                if tree.branch.repository._format.supports_full_versioned_files:
                    inv_key = (builder._new_revision_id,)
                    inv_sha1 = tree.branch.repository.inventories.get_sha1s([inv_key])[
                        inv_key
                    ]
                    self.assertEqual(inv_sha1, builder.inv_sha1)
                rev2 = builder.commit("rev2")
            except BaseException:
                builder.abort()
                raise
            delta = builder.get_basis_delta()
            delta_dict = {change[1]: change for change in delta}
            if tree.branch.repository._format.records_per_file_revision:
                version_recorded = (
                    new_name in delta_dict
                    and delta_dict[new_name][3] is not None
                    and delta_dict[new_name][3].revision == rev2
                )
                if records_version:
                    self.assertTrue(version_recorded)
                else:
                    self.assertFalse(version_recorded)

            revtree = builder.revision_tree()
            new_entry = next(revtree.iter_entries_by_dir(specific_files=[new_name]))[1]

            if delta_against_basis:
                (delta_old_name, delta_new_name, delta_file_id, delta_entry) = (
                    delta_dict[new_name]
                )
                self.assertEqual(delta_new_name, new_name)
                if tree.supports_rename_tracking():
                    self.assertEqual(name, delta_old_name)
                else:
                    self.assertIn(delta_old_name, (name, None))
                if tree.supports_setting_file_ids():
                    self.assertEqual(delta_file_id, file_id)
                    self.assertEqual(delta_entry.file_id, file_id)
                self.assertEqual(delta_entry.kind, new_entry.kind)
                self.assertEqual(delta_entry.name, new_entry.name)
                self.assertEqual(delta_entry.parent_id, new_entry.parent_id)
                if delta_entry.kind == "file":
                    self.assertEqual(
                        delta_entry.text_size, revtree.get_file_size(new_name)
                    )
                    if getattr(delta_entry, "text_sha1", None):
                        self.assertEqual(
                            delta_entry.text_sha1, revtree.get_file_sha1(new_name)
                        )
                elif delta_entry.kind == "symlink":
                    self.assertEqual(
                        delta_entry.symlink_target, new_entry.symlink_target
                    )
            else:
                if tree.branch.repository._format.records_per_file_revision:
                    self.assertFalse(version_recorded)
            tree.set_parent_ids([rev2])
        return rev2

    def assertFileGraph(self, expected_graph, tree, tip):
        # all the changes that have occured should be in the ancestry
        # (closest to a public per-file graph API we have today)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        g = dict(tree.branch.repository.get_file_graph().iter_ancestry([tip]))
        self.assertEqual(expected_graph, g)

    def test_last_modified_revision_after_content_file_changes(self):
        # altering a file changes the last modified.
        tree = self.make_branch_and_tree(".")
        self.build_tree(["file"])

        def change_file():
            tree.put_file_bytes_non_atomic("file", b"new content")

        self._add_commit_change_check_changed(
            tree, ("file", "file"), change_file, expect_fs_hash=True
        )

    def _test_last_mod_rev_after_content_link_changes(self, link, target, newtarget):
        # changing a link changes the last modified.
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        tree = self.make_branch_and_tree(".")
        os.symlink(target, link)

        def change_link():
            os.unlink(link)
            os.symlink(newtarget, link)

        self._add_commit_change_check_changed(tree, (link, link), change_link)

    def test_last_modified_rev_after_content_link_changes(self):
        self._test_last_mod_rev_after_content_link_changes(
            "link", "target", "newtarget"
        )

    def test_last_modified_rev_after_content_unicode_link_changes(self):
        self.requireFeature(features.UnicodeFilenameFeature)
        self._test_last_mod_rev_after_content_link_changes(
            "li\u1234nk", "targ\N{EURO SIGN}t", "n\N{EURO SIGN}wtarget"
        )

    def _commit_sprout(self, tree, name):
        tree.add([name])
        rev_id = tree.commit("rev")
        return rev_id, tree.controldir.sprout("t2").open_workingtree()

    def _rename_in_tree(self, tree, name, message):
        tree.rename_one(name, "new_" + name)
        return tree.commit(message)

    def _commit_sprout_rename_merge(self, tree1, name, expect_fs_hash=False):
        """Do a rename in both trees."""
        rev1, tree2 = self._commit_sprout(tree1, name)
        if tree2.supports_file_ids:
            file_id = tree2.path2id(name)
            self.assertIsNot(None, file_id)
        self.assertTrue(tree2.is_versioned(name))
        # change both sides equally
        rev2 = self._rename_in_tree(tree1, name, "rev2")
        rev3 = self._rename_in_tree(tree2, name, "rev3")
        tree1.merge_from_branch(tree2.branch)
        rev4 = self.mini_commit_record_iter_changes(
            tree1,
            "new_" + name,
            "new_" + name,
            expect_fs_hash=expect_fs_hash,
            delta_against_basis=tree1.supports_rename_tracking(),
        )
        (tree3,) = self._get_revtrees(tree1, [rev4])
        if tree1.supports_file_ids:
            expected_graph = {}
            if tree1.supports_rename_tracking():
                self.assertEqual(rev4, tree3.get_file_revision("new_" + name))
                expected_graph[(file_id, rev1)] = ()
                expected_graph[(file_id, rev2)] = ((file_id, rev1),)
                expected_graph[(file_id, rev3)] = ((file_id, rev1),)
                expected_graph[(file_id, rev4)] = (
                    (file_id, rev2),
                    (file_id, rev3),
                )
            else:
                self.assertEqual(rev2, tree3.get_file_revision("new_" + name))
                expected_graph[(file_id, rev4)] = ()
            self.assertFileGraph(expected_graph, tree1, (file_id, rev4))

    def test_last_modified_revision_after_merge_dir_changes(self):
        # merge a dir changes the last modified.
        tree1 = self.make_branch_and_tree("t1")
        if not tree1.has_versioned_directories():
            raise tests.TestNotApplicable(
                "Format does not support versioned directories"
            )
        self.build_tree(["t1/dir/"])
        self._commit_sprout_rename_merge(tree1, "dir")

    def test_last_modified_revision_after_merge_file_changes(self):
        # merge a file changes the last modified.
        tree1 = self.make_branch_and_tree("t1")
        self.build_tree(["t1/file"])
        self._commit_sprout_rename_merge(tree1, "file", expect_fs_hash=True)

    def test_last_modified_revision_after_merge_link_changes(self):
        # merge a link changes the last modified.
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        tree1 = self.make_branch_and_tree("t1")
        os.symlink("target", "t1/link")
        self._commit_sprout_rename_merge(tree1, "link")

    def _commit_sprout_rename_merge_converged(self, tree1, name):
        # Make a merge which just incorporates a change from a branch:
        # The per-file graph is straight line, and no alteration occurs
        # in the inventory.
        # Part 1: change in the merged branch.
        rev1, tree2 = self._commit_sprout(tree1, name)
        if tree2.supports_file_ids:
            file_id = tree2.path2id(name)
            self.assertIsNot(None, file_id)
        # change on the other side to merge back
        rev2 = self._rename_in_tree(tree2, name, "rev2")
        tree1.merge_from_branch(tree2.branch)

        if tree2.supports_file_ids:

            def _check_graph(in_tree, changed_in_tree):
                self.mini_commit_record_iter_changes(
                    in_tree,
                    name,
                    "new_" + name,
                    False,
                    delta_against_basis=changed_in_tree,
                )
                (tree3,) = self._get_revtrees(in_tree, [rev2])
                self.assertEqual(rev2, tree3.get_file_revision("new_" + name))
                expected_graph = {}
                expected_graph[(file_id, rev1)] = ()
                expected_graph[(file_id, rev2)] = ((file_id, rev1),)
                self.assertFileGraph(expected_graph, in_tree, (file_id, rev2))

            _check_graph(tree1, True)
        # Part 2: change in the merged into branch - we use tree2 that has a
        # change to name, branch tree1 and give it an unrelated change, then
        # merge that to t2.
        other_tree = tree1.controldir.sprout("t3").open_workingtree()
        other_tree.commit("other_rev")
        tree2.merge_from_branch(other_tree.branch)
        if tree2.supports_file_ids:
            _check_graph(tree2, False)

    def _commit_sprout_make_merge(self, tree1, make):
        # Make a merge which incorporates the addition of a new object to
        # another branch. The per-file graph shows no additional change
        # in the merge because its a straight line.
        tree1.commit("rev1")
        tree2 = tree1.controldir.sprout("t2").open_workingtree()
        # make and commit on the other side to merge back
        make("t2/name")
        tree2.add(["name"])
        self.assertTrue(tree2.is_versioned("name"))
        rev2 = tree2.commit("rev2")
        tree1.merge_from_branch(tree2.branch)
        self.mini_commit_record_iter_changes(tree1, None, "name", False)
        (tree3,) = self._get_revtrees(tree1, [rev2])
        # in rev2, name should be only changed in rev2
        self.assertEqual(rev2, tree3.get_file_revision("name"))
        if tree2.supports_file_ids:
            file_id = tree2.path2id("name")
            expected_graph = {}
            expected_graph[(file_id, rev2)] = ()
            self.assertFileGraph(expected_graph, tree1, (file_id, rev2))

    def test_last_modified_revision_after_converged_merge_dir_unchanged(self):
        # merge a dir that changed preserves the last modified.
        tree1 = self.make_branch_and_tree("t1")
        if not tree1.has_versioned_directories():
            raise tests.TestNotApplicable(
                "Format does not support versioned directories"
            )
        self.build_tree(["t1/dir/"])
        self._commit_sprout_rename_merge_converged(tree1, "dir")

    def test_last_modified_revision_after_converged_merge_file_unchanged(self):
        # merge a file that changed preserves the last modified.
        tree1 = self.make_branch_and_tree("t1")
        self.build_tree(["t1/file"])
        self._commit_sprout_rename_merge_converged(tree1, "file")

    def test_last_modified_revision_after_converged_merge_link_unchanged(self):
        # merge a link that changed preserves the last modified.
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        tree1 = self.make_branch_and_tree("t1")
        os.symlink("target", "t1/link")
        self._commit_sprout_rename_merge_converged(tree1, "link")

    def test_last_modified_revision_after_merge_new_dir_unchanged(self):
        # merge a new dir does not change the last modified.
        tree1 = self.make_branch_and_tree("t1")
        if not tree1.has_versioned_directories():
            raise tests.TestNotApplicable(
                "Format does not support versioned directories"
            )
        self._commit_sprout_make_merge(tree1, self.make_dir)

    def test_last_modified_revision_after_merge_new_file_unchanged(self):
        # merge a new file does not change the last modified.
        tree1 = self.make_branch_and_tree("t1")
        self._commit_sprout_make_merge(tree1, self.make_file)

    def test_last_modified_revision_after_merge_new_link_unchanged(self):
        # merge a new link does not change the last modified.
        tree1 = self.make_branch_and_tree("t1")
        self._commit_sprout_make_merge(tree1, self.make_link)

    def make_dir(self, name):
        self.build_tree([name + "/"])

    def make_file(self, name):
        self.build_tree([name])

    def make_link(self, name):
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        os.symlink("target", name)

    def make_reference(self, name):
        tree = self.make_branch_and_tree(name)
        if not tree.branch.repository._format.rich_root_data:
            raise tests.TestNotApplicable("format does not support rich roots")
        tree.commit("foo")
        return tree

    def _check_kind_change(self, make_before, make_after, expect_fs_hash=False):
        tree = self.make_branch_and_tree(".")
        path = "name"
        make_before(path)

        def change_kind():
            if osutils.file_kind(path) == "directory":
                osutils.rmtree(path)
            else:
                osutils.delete_any(path)
            make_after(path)

        self._add_commit_change_check_changed(
            tree, (path, path), change_kind, expect_fs_hash=expect_fs_hash
        )

    def test_last_modified_dir_file(self):
        if not self.repository_format.supports_versioned_directories:
            # TODO(jelmer): Perhaps test this by creating a directory
            # with a file in it?
            raise tests.TestNotApplicable(
                "format does not support versioned directories"
            )
        try:
            self._check_kind_change(self.make_dir, self.make_file, expect_fs_hash=True)
        except errors.UnsupportedKindChange:
            raise tests.TestSkipped(
                "tree does not support changing entry kind from directory to file"
            )

    def test_last_modified_dir_link(self):
        if not self.repository_format.supports_versioned_directories:
            # TODO(jelmer): Perhaps test this by creating a directory
            # with a file in it?
            raise tests.TestNotApplicable(
                "format does not support versioned directories"
            )
        try:
            self._check_kind_change(self.make_dir, self.make_link)
        except errors.UnsupportedKindChange:
            raise tests.TestSkipped(
                "tree does not support changing entry kind from directory to link"
            )

    def test_last_modified_link_file(self):
        self._check_kind_change(self.make_link, self.make_file, expect_fs_hash=True)

    def test_last_modified_link_dir(self):
        if not self.repository_format.supports_versioned_directories:
            # TODO(jelmer): Perhaps test this by creating a directory
            # with a file in it?
            raise tests.TestNotApplicable(
                "format does not support versioned directories"
            )

        self._check_kind_change(self.make_link, self.make_dir)

    def test_last_modified_file_dir(self):
        if not self.repository_format.supports_versioned_directories:
            # TODO(jelmer): Perhaps test this by creating a directory
            # with a file in it?
            raise tests.TestNotApplicable(
                "format does not support versioned directories"
            )

        self._check_kind_change(self.make_file, self.make_dir)

    def test_last_modified_file_link(self):
        self._check_kind_change(self.make_file, self.make_link)

    def test_get_commit_builder_with_invalid_revprops(self):
        branch = self.make_branch(".")
        branch.repository.lock_write()
        self.addCleanup(branch.repository.unlock)
        self.assertRaises(
            ValueError,
            branch.repository.get_commit_builder,
            branch,
            [],
            branch.get_config_stack(),
            revprops={"invalid": "property\rwith\r\ninvalid chars"},
        )

    def test_get_commit_builder_with_surrogateescape(self):
        tree = self.make_branch_and_tree(".")
        with tree.lock_write():
            builder = tree.branch.get_commit_builder(
                [],
                revprops={
                    "invalid": "property" + b"\xc0".decode("utf-8", "surrogateescape")
                },
            )
            list(
                builder.record_iter_changes(
                    tree, tree.last_revision(), tree.iter_changes(tree.basis_tree())
                )
            )
            builder.finish_inventory()
            try:
                rev_id = builder.commit("foo bar blah")
            except NotImplementedError:
                raise tests.TestNotApplicable(
                    "Format does not support revision properties"
                )
        rev = tree.branch.repository.get_revision(rev_id)
        self.assertEqual("foo bar blah", rev.message)

    def test_commit_builder_commit_with_invalid_message(self):
        branch = self.make_branch(".")
        branch.repository.lock_write()
        self.addCleanup(branch.repository.unlock)
        builder = branch.repository.get_commit_builder(
            branch, [], branch.get_config_stack()
        )
        self.addCleanup(branch.repository.abort_write_group)
        self.assertRaises(ValueError, builder.commit, "Invalid\r\ncommit message\r\n")

    def test_non_ascii_str_committer_rejected(self):
        """Ensure an error is raised on a non-ascii byte string committer."""
        branch = self.make_branch(".")
        branch.repository.lock_write()
        self.addCleanup(branch.repository.unlock)
        self.assertRaises(
            UnicodeDecodeError,
            branch.repository.get_commit_builder,
            branch,
            [],
            branch.get_config_stack(),
            committer=b"Erik B\xe5gfors <erik@example.com>",
        )

    def test_stacked_repositories_reject_commit_builder(self):
        # As per bug 375013, committing to stacked repositories is currently
        # broken if we aren't in a chk repository. So old repositories with
        # fallbacks refuse to hand out a commit builder.
        repo_basis = self.make_repository("basis")
        branch = self.make_branch("local")
        repo_local = branch.repository
        try:
            repo_local.add_fallback_repository(repo_basis)
        except errors.UnstackableRepositoryFormat:
            raise tests.TestNotApplicable("not a stackable format.")
        self.addCleanup(repo_local.lock_write().unlock)
        if not repo_local._format.supports_chks:
            self.assertRaises(
                errors.BzrError,
                repo_local.get_commit_builder,
                branch,
                [],
                branch.get_config_stack(),
            )
        else:
            builder = repo_local.get_commit_builder(
                branch, [], branch.get_config_stack()
            )
            builder.abort()

    def test_committer_no_username(self):
        # Ensure that when no username is available but a committer is
        # supplied, commit works.
        override_whoami(self)
        tree = self.make_branch_and_tree(".")
        with tree.lock_write():
            # Make sure no username is available.
            self.assertRaises(errors.NoWhoami, tree.branch.get_commit_builder, [])
            builder = tree.branch.get_commit_builder([], committer="me@example.com")
            try:
                list(
                    builder.record_iter_changes(
                        tree, tree.last_revision(), tree.iter_changes(tree.basis_tree())
                    )
                )
                builder.finish_inventory()
            except:
                builder.abort()
                raise
            repo = tree.branch.repository
            repo.commit_write_group()
