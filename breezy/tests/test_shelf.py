# Copyright (C) 2008-2011 Canonical Ltd
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

import os

from .. import errors, ignores, osutils, shelf, tests, transform, workingtree
from ..bzr import pack
from . import KnownFailure, features

EMPTY_SHELF = (
    b"Bazaar pack format 1 (introduced in 0.18)\n"
    b"B23\n"
    b"metadata\n\n"
    b"d11:revision_id5:null:e"
    b"B159\n"
    b"attribs\n\n"
    b"d10:_id_numberi0e18:_new_executabilityde7:_new_idde"
    b"9:_new_namede11:_new_parentde16:_non_present_idsde"
    b"17:_removed_contentsle11:_removed_idle14:_tree_path_idsdeeE"
)


class TestErrors(tests.TestCase):
    def test_invalid_shelf_id(self):
        invalid_id = "foo"
        err = shelf.InvalidShelfId(invalid_id)
        self.assertEqual(
            '"foo" is not a valid shelf id, try a number instead.', str(err)
        )


class TestPrepareShelf(tests.TestCaseWithTransport):
    def prepare_shelve_rename(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree(["foo"])
        tree.add(["foo"], ids=[b"foo-id"])
        tree.commit("foo")
        tree.rename_one("foo", "bar")
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        creator = shelf.ShelfCreator(tree, tree.basis_tree())
        self.addCleanup(creator.finalize)
        self.assertEqual(
            [("rename", b"foo-id", "foo", "bar")], list(creator.iter_shelvable())
        )
        return creator

    def check_shelve_rename(self, creator):
        work_trans_id = creator.work_transform.trans_id_file_id(b"foo-id")
        self.assertEqual("foo", creator.work_transform.final_name(work_trans_id))
        shelf_trans_id = creator.shelf_transform.trans_id_file_id(b"foo-id")
        self.assertEqual("bar", creator.shelf_transform.final_name(shelf_trans_id))

    def test_shelve_rename(self):
        creator = self.prepare_shelve_rename()
        creator.shelve_rename(b"foo-id")
        self.check_shelve_rename(creator)

    def test_shelve_change_handles_rename(self):
        creator = self.prepare_shelve_rename()
        creator.shelve_change(("rename", b"foo-id", "foo", "bar"))
        self.check_shelve_rename(creator)

    def prepare_shelve_move(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree(["foo/", "bar/", "foo/baz"])
        tree.add(["foo", "bar", "foo/baz"], ids=[b"foo-id", b"bar-id", b"baz-id"])
        tree.commit("foo")
        tree.rename_one("foo/baz", "bar/baz")
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        creator = shelf.ShelfCreator(tree, tree.basis_tree())
        self.addCleanup(creator.finalize)
        self.assertEqual(
            [("rename", b"baz-id", "foo/baz", "bar/baz")],
            list(creator.iter_shelvable()),
        )
        return creator, tree

    def check_shelve_move(self, creator, tree):
        work_trans_id = creator.work_transform.trans_id_file_id(b"baz-id")
        work_foo = creator.work_transform.trans_id_file_id(b"foo-id")
        self.assertEqual(work_foo, creator.work_transform.final_parent(work_trans_id))
        shelf_trans_id = creator.shelf_transform.trans_id_file_id(b"baz-id")
        shelf_bar = creator.shelf_transform.trans_id_file_id(b"bar-id")
        self.assertEqual(
            shelf_bar, creator.shelf_transform.final_parent(shelf_trans_id)
        )
        creator.transform()
        self.assertEqual("foo/baz", tree.id2path(b"baz-id"))

    def test_shelve_move(self):
        creator, tree = self.prepare_shelve_move()
        creator.shelve_rename(b"baz-id")
        self.check_shelve_move(creator, tree)

    def test_shelve_change_handles_move(self):
        creator, tree = self.prepare_shelve_move()
        creator.shelve_change(("rename", b"baz-id", "foo/baz", "bar/baz"))
        self.check_shelve_move(creator, tree)

    def test_shelve_changed_root_id(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree(["foo"])
        tree.set_root_id(b"first-root-id")
        tree.add(["foo"], ids=[b"foo-id"])
        tree.commit("foo")
        tree.set_root_id(b"second-root-id")
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        creator = shelf.ShelfCreator(tree, tree.basis_tree())
        self.addCleanup(creator.finalize)
        self.expectFailure(
            "shelf doesn't support shelving root changes yet",
            self.assertEqual,
            [
                ("delete file", b"first-root-id", "directory", ""),
                ("add file", b"second-root-id", "directory", ""),
                ("rename", b"foo-id", "foo", "foo"),
            ],
            list(creator.iter_shelvable()),
        )

        self.assertEqual(
            [
                ("delete file", b"first-root-id", "directory", ""),
                ("add file", b"second-root-id", "directory", ""),
                ("rename", b"foo-id", "foo", "foo"),
            ],
            list(creator.iter_shelvable()),
        )

    def assertShelvedFileEqual(self, expected_content, creator, file_id):
        s_trans_id = creator.shelf_transform.trans_id_file_id(file_id)
        shelf_file = creator.shelf_transform._limbo_name(s_trans_id)
        self.assertFileEqual(expected_content, shelf_file)

    def prepare_content_change(self):
        tree = self.make_branch_and_tree(".")
        tree.lock_write()
        self.addCleanup(tree.unlock)
        self.build_tree_contents([("foo", b"a\n")])
        tree.add("foo", ids=b"foo-id")
        tree.commit("Committed foo")
        self.build_tree_contents([("foo", b"b\na\nc\n")])
        creator = shelf.ShelfCreator(tree, tree.basis_tree())
        self.addCleanup(creator.finalize)
        return creator

    def test_shelve_content_change(self):
        creator = self.prepare_content_change()
        self.assertEqual([("modify text", b"foo-id")], list(creator.iter_shelvable()))
        creator.shelve_lines(b"foo-id", [b"a\n", b"c\n"])
        creator.transform()
        self.assertFileEqual(b"a\nc\n", "foo")
        self.assertShelvedFileEqual(b"b\na\n", creator, b"foo-id")

    def test_shelve_change_handles_modify_text(self):
        creator = self.prepare_content_change()
        creator.shelve_change(("modify text", b"foo-id"))
        creator.transform()
        self.assertFileEqual(b"a\n", "foo")
        self.assertShelvedFileEqual(b"b\na\nc\n", creator, b"foo-id")

    def test_shelve_all(self):
        creator = self.prepare_content_change()
        creator.shelve_all()
        creator.transform()
        self.assertFileEqual(b"a\n", "foo")
        self.assertShelvedFileEqual(b"b\na\nc\n", creator, b"foo-id")

    def prepare_shelve_creation(self):
        tree = self.make_branch_and_tree(".")
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.commit("Empty tree")
        self.build_tree_contents([("foo", b"a\n"), ("bar/",)])
        tree.add(["foo", "bar"], ids=[b"foo-id", b"bar-id"])
        creator = shelf.ShelfCreator(tree, tree.basis_tree())
        self.addCleanup(creator.finalize)
        self.assertEqual(
            [
                ("add file", b"bar-id", "directory", "bar"),
                ("add file", b"foo-id", "file", "foo"),
            ],
            sorted(creator.iter_shelvable()),
        )
        return creator, tree

    def check_shelve_creation(self, creator, tree):
        self.assertRaises(
            StopIteration, next, tree.iter_entries_by_dir(specific_files=["foo"])
        )
        s_trans_id = creator.shelf_transform.trans_id_file_id(b"foo-id")
        self.assertEqual(b"foo-id", creator.shelf_transform.final_file_id(s_trans_id))
        self.assertPathDoesNotExist("foo")
        self.assertPathDoesNotExist("bar")
        self.assertShelvedFileEqual("a\n", creator, b"foo-id")
        s_bar_trans_id = creator.shelf_transform.trans_id_file_id(b"bar-id")
        self.assertEqual(
            "directory", creator.shelf_transform.final_kind(s_bar_trans_id)
        )

    def test_shelve_creation(self):
        creator, tree = self.prepare_shelve_creation()
        creator.shelve_creation(b"foo-id")
        creator.shelve_creation(b"bar-id")
        creator.transform()
        self.check_shelve_creation(creator, tree)

    def test_shelve_change_handles_creation(self):
        creator, tree = self.prepare_shelve_creation()
        creator.shelve_change(("add file", b"foo-id", "file", "foo"))
        creator.shelve_change(("add file", b"bar-id", "directory", "bar"))
        creator.transform()
        self.check_shelve_creation(creator, tree)

    def test_shelve_directory_with_ignored(self):
        tree = self.make_branch_and_tree(".")
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.commit("Empty tree")
        self.build_tree_contents(
            [("foo", b"a\n"), ("bar/",), ("bar/ignored", b"ign\n")]
        )
        tree.add(["foo", "bar"], ids=[b"foo-id", b"bar-id"])
        creator = shelf.ShelfCreator(tree, tree.basis_tree())
        self.addCleanup(creator.finalize)
        self.assertEqual(
            [
                ("add file", b"bar-id", "directory", "bar"),
                ("add file", b"foo-id", "file", "foo"),
            ],
            sorted(creator.iter_shelvable()),
        )
        ignores._set_user_ignores([])
        in_patterns = [
            "ignored",
        ]
        ignores.add_unique_user_ignores(in_patterns)

        creator.shelve_change(("add file", b"bar-id", "directory", "bar"))
        try:
            creator.transform()
            self.check_shelve_creation(creator, tree)
        except transform.MalformedTransform as err:
            raise KnownFailure(
                "shelving directory with ignored file: see bug #611739"
            ) from err

    def _test_shelve_symlink_creation(
        self, link_name, link_target, shelve_change=False
    ):
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        tree = self.make_branch_and_tree(".")
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.commit("Empty tree")
        os.symlink(link_target, link_name)
        tree.add(link_name, ids=b"foo-id")
        creator = shelf.ShelfCreator(tree, tree.basis_tree())
        self.addCleanup(creator.finalize)
        self.assertEqual(
            [("add file", b"foo-id", "symlink", link_name)],
            list(creator.iter_shelvable()),
        )
        if shelve_change:
            creator.shelve_change(("add file", b"foo-id", "symlink", link_name))
        else:
            creator.shelve_creation(b"foo-id")
        creator.transform()
        s_trans_id = creator.shelf_transform.trans_id_file_id(b"foo-id")
        self.assertPathDoesNotExist(link_name)
        limbo_name = creator.shelf_transform._limbo_name(s_trans_id)
        self.assertEqual(link_target, osutils.readlink(limbo_name))
        ptree = creator.shelf_transform.get_preview_tree()
        self.assertEqual(
            link_target, ptree.get_symlink_target(ptree.id2path(b"foo-id"))
        )

    def test_shelve_symlink_creation(self):
        self._test_shelve_symlink_creation("foo", "bar")

    def test_shelve_unicode_symlink_creation(self):
        self.requireFeature(features.UnicodeFilenameFeature)
        self._test_shelve_symlink_creation("fo\N{EURO SIGN}o", "b\N{EURO SIGN}ar")

    def test_shelve_change_handles_symlink_creation(self):
        self._test_shelve_symlink_creation("foo", "bar", shelve_change=True)

    def _test_shelve_symlink_target_change(
        self, link_name, old_target, new_target, shelve_change=False
    ):
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        tree = self.make_branch_and_tree(".")
        tree.lock_write()
        self.addCleanup(tree.unlock)
        os.symlink(old_target, link_name)
        tree.add(link_name, ids=b"foo-id")
        tree.commit("commit symlink")
        os.unlink(link_name)
        os.symlink(new_target, link_name)
        creator = shelf.ShelfCreator(tree, tree.basis_tree())
        self.addCleanup(creator.finalize)
        self.assertEqual(
            [("modify target", b"foo-id", link_name, old_target, new_target)],
            list(creator.iter_shelvable()),
        )
        if shelve_change:
            creator.shelve_change(
                ("modify target", b"foo-id", link_name, old_target, new_target)
            )
        else:
            creator.shelve_modify_target(b"foo-id")
        creator.transform()
        self.assertEqual(old_target, osutils.readlink(link_name))
        s_trans_id = creator.shelf_transform.trans_id_file_id(b"foo-id")
        limbo_name = creator.shelf_transform._limbo_name(s_trans_id)
        self.assertEqual(new_target, osutils.readlink(limbo_name))
        ptree = creator.shelf_transform.get_preview_tree()
        self.assertEqual(new_target, ptree.get_symlink_target(ptree.id2path(b"foo-id")))

    def test_shelve_symlink_target_change(self):
        self._test_shelve_symlink_target_change("foo", "bar", "baz")

    def test_shelve_unicode_symlink_target_change(self):
        self.requireFeature(features.UnicodeFilenameFeature)
        self._test_shelve_symlink_target_change(
            "fo\N{EURO SIGN}o", "b\N{EURO SIGN}ar", "b\N{EURO SIGN}az"
        )

    def test_shelve_change_handles_symlink_target_change(self):
        self._test_shelve_symlink_target_change("foo", "bar", "baz", shelve_change=True)

    def test_shelve_creation_no_contents(self):
        tree = self.make_branch_and_tree(".")
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.commit("Empty tree")
        self.build_tree(["foo"])
        tree.add("foo", ids=b"foo-id")
        os.unlink("foo")
        creator = shelf.ShelfCreator(tree, tree.basis_tree())
        self.addCleanup(creator.finalize)
        self.assertEqual(
            [("add file", b"foo-id", None, "foo")], sorted(creator.iter_shelvable())
        )
        creator.shelve_creation(b"foo-id")
        creator.transform()
        self.assertRaises(
            StopIteration, next, tree.iter_entries_by_dir(specific_files=["foo"])
        )
        self.assertShelvedFileEqual("", creator, b"foo-id")
        s_trans_id = creator.shelf_transform.trans_id_file_id(b"foo-id")
        self.assertEqual(b"foo-id", creator.shelf_transform.final_file_id(s_trans_id))
        self.assertPathDoesNotExist("foo")

    def prepare_shelve_deletion(self):
        tree = self.make_branch_and_tree("tree")
        tree.lock_write()
        self.addCleanup(tree.unlock)
        self.build_tree_contents([("tree/foo/",), ("tree/foo/bar", b"baz")])
        tree.add(["foo", "foo/bar"], ids=[b"foo-id", b"bar-id"])
        tree.commit("Added file and directory")
        tree.unversion(["foo", "foo/bar"])
        os.unlink("tree/foo/bar")
        os.rmdir("tree/foo")
        creator = shelf.ShelfCreator(tree, tree.basis_tree())
        self.addCleanup(creator.finalize)
        self.assertEqual(
            [
                ("delete file", b"bar-id", "file", "foo/bar"),
                ("delete file", b"foo-id", "directory", "foo"),
            ],
            sorted(creator.iter_shelvable()),
        )
        return creator, tree

    def check_shelve_deletion(self, tree):
        self.assertEqual(tree.id2path(b"foo-id"), "foo")
        self.assertEqual(tree.id2path(b"bar-id"), "foo/bar")
        self.assertFileEqual(b"baz", "tree/foo/bar")

    def test_shelve_deletion(self):
        creator, tree = self.prepare_shelve_deletion()
        creator.shelve_deletion(b"foo-id")
        creator.shelve_deletion(b"bar-id")
        creator.transform()
        self.check_shelve_deletion(tree)

    def test_shelve_change_handles_deletion(self):
        creator, tree = self.prepare_shelve_deletion()
        creator.shelve_change(("delete file", b"foo-id", "directory", "foo"))
        creator.shelve_change(("delete file", b"bar-id", "file", "foo/bar"))
        creator.transform()
        self.check_shelve_deletion(tree)

    def test_shelve_delete_contents(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(
            [
                "tree/foo",
            ]
        )
        tree.add("foo", ids=b"foo-id")
        tree.commit("Added file and directory")
        os.unlink("tree/foo")
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        creator = shelf.ShelfCreator(tree, tree.basis_tree())
        self.addCleanup(creator.finalize)
        self.assertEqual(
            [("delete file", b"foo-id", "file", "foo")],
            sorted(creator.iter_shelvable()),
        )
        creator.shelve_deletion(b"foo-id")
        creator.transform()
        self.assertPathExists("tree/foo")

    def prepare_shelve_change_kind(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree_contents([("tree/foo", b"bar")])
        tree.add("foo", ids=b"foo-id")
        tree.commit("Added file and directory")
        os.unlink("tree/foo")
        os.mkdir("tree/foo")
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        creator = shelf.ShelfCreator(tree, tree.basis_tree())
        self.addCleanup(creator.finalize)
        self.assertEqual(
            [("change kind", b"foo-id", "file", "directory", "foo")],
            sorted(creator.iter_shelvable()),
        )
        return creator

    def check_shelve_change_kind(self, creator):
        self.assertFileEqual(b"bar", "tree/foo")
        s_trans_id = creator.shelf_transform.trans_id_file_id(b"foo-id")
        self.assertEqual("directory", creator.shelf_transform._new_contents[s_trans_id])

    def test_shelve_change_kind(self):
        creator = self.prepare_shelve_change_kind()
        creator.shelve_content_change(b"foo-id")
        creator.transform()
        self.check_shelve_change_kind(creator)

    def test_shelve_change_handles_change_kind(self):
        creator = self.prepare_shelve_change_kind()
        creator.shelve_change(("change kind", b"foo-id", "file", "directory", "foo"))
        creator.transform()
        self.check_shelve_change_kind(creator)

    def test_shelve_change_unknown_change(self):
        tree = self.make_branch_and_tree("tree")
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        creator = shelf.ShelfCreator(tree, tree.basis_tree())
        self.addCleanup(creator.finalize)
        e = self.assertRaises(ValueError, creator.shelve_change, ("unknown",))
        self.assertEqual('Unknown change kind: "unknown"', str(e))

    def test_shelve_unversion(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(
            [
                "tree/foo",
            ]
        )
        tree.add("foo", ids=b"foo-id")
        tree.commit("Added file and directory")
        tree.unversion(["foo"])
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        creator = shelf.ShelfCreator(tree, tree.basis_tree())
        self.addCleanup(creator.finalize)
        self.assertEqual(
            [("delete file", b"foo-id", "file", "foo")],
            sorted(creator.iter_shelvable()),
        )
        creator.shelve_deletion(b"foo-id")
        creator.transform()
        self.assertPathExists("tree/foo")

    def test_shelve_serialization(self):
        tree = self.make_branch_and_tree(".")
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        creator = shelf.ShelfCreator(tree, tree.basis_tree())
        self.addCleanup(creator.finalize)
        shelf_file = open("shelf", "wb")
        self.addCleanup(shelf_file.close)
        try:
            creator.write_shelf(shelf_file)
        finally:
            shelf_file.close()
        self.assertFileEqual(EMPTY_SHELF, "shelf")

    def test_write_shelf(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/foo"])
        tree.add("foo", ids=b"foo-id")
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        creator = shelf.ShelfCreator(tree, tree.basis_tree())
        self.addCleanup(creator.finalize)
        list(creator.iter_shelvable())
        creator.shelve_creation(b"foo-id")
        with open("shelf", "wb") as shelf_file:
            creator.write_shelf(shelf_file)
        parser = pack.ContainerPushParser()
        with open("shelf", "rb") as shelf_file:
            parser.accept_bytes(shelf_file.read())
        tt = tree.preview_transform()
        self.addCleanup(tt.finalize)
        records = iter(parser.read_pending_records())
        # skip revision-id
        next(records)
        tt.deserialize(records)

    def test_shelve_unversioned(self):
        tree = self.make_branch_and_tree("tree")
        with tree.lock_tree_write():
            self.assertRaises(
                errors.PathsNotVersionedError,
                shelf.ShelfCreator,
                tree,
                tree.basis_tree(),
                ["foo"],
            )
        # We should be able to lock/unlock the tree if ShelfCreator cleaned
        # after itself.
        wt = workingtree.WorkingTree.open("tree")
        wt.lock_tree_write()
        wt.unlock()
        # And a second tentative should raise the same error (no
        # limbo/pending_deletion leftovers).
        with tree.lock_tree_write():
            self.assertRaises(
                errors.PathsNotVersionedError,
                shelf.ShelfCreator,
                tree,
                tree.basis_tree(),
                ["foo"],
            )

    def test_shelve_skips_added_root(self):
        """Skip adds of the root when iterating through shelvable changes."""
        tree = self.make_branch_and_tree("tree")
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        creator = shelf.ShelfCreator(tree, tree.basis_tree())
        self.addCleanup(creator.finalize)
        self.assertEqual([], list(creator.iter_shelvable()))


class TestUnshelver(tests.TestCaseWithTransport):
    def test_make_merger(self):
        tree = self.make_branch_and_tree("tree")
        tree.commit("first commit")
        self.build_tree_contents([("tree/foo", b"bar")])
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.add("foo", ids=b"foo-id")
        creator = shelf.ShelfCreator(tree, tree.basis_tree())
        self.addCleanup(creator.finalize)
        list(creator.iter_shelvable())
        creator.shelve_creation(b"foo-id")
        with open("shelf-file", "w+b") as shelf_file:
            creator.write_shelf(shelf_file)
            creator.transform()
            shelf_file.seek(0)
            unshelver = shelf.Unshelver.from_tree_and_shelf(tree, shelf_file)
            unshelver.make_merger().do_merge()
            self.addCleanup(unshelver.finalize)
            self.assertFileEqual(b"bar", "tree/foo")

    def test_unshelve_changed(self):
        tree = self.make_branch_and_tree("tree")
        tree.lock_write()
        self.addCleanup(tree.unlock)
        self.build_tree_contents([("tree/foo", b"a\nb\nc\n")])
        tree.add("foo", ids=b"foo-id")
        tree.commit("first commit")
        self.build_tree_contents([("tree/foo", b"a\nb\nd\n")])
        creator = shelf.ShelfCreator(tree, tree.basis_tree())
        self.addCleanup(creator.finalize)
        list(creator.iter_shelvable())
        creator.shelve_lines(b"foo-id", [b"a\n", b"b\n", b"c\n"])
        shelf_file = open("shelf", "w+b")
        self.addCleanup(shelf_file.close)
        creator.write_shelf(shelf_file)
        creator.transform()
        self.build_tree_contents([("tree/foo", b"z\na\nb\nc\n")])
        shelf_file.seek(0)
        unshelver = shelf.Unshelver.from_tree_and_shelf(tree, shelf_file)
        self.addCleanup(unshelver.finalize)
        unshelver.make_merger().do_merge()
        self.assertFileEqual(b"z\na\nb\nd\n", "tree/foo")

    def test_unshelve_deleted(self):
        tree = self.make_branch_and_tree("tree")
        tree.lock_write()
        self.addCleanup(tree.unlock)
        self.build_tree_contents([("tree/foo/",), ("tree/foo/bar", b"baz")])
        tree.add(["foo", "foo/bar"], ids=[b"foo-id", b"bar-id"])
        tree.commit("Added file and directory")
        tree.unversion(["foo", "foo/bar"])
        os.unlink("tree/foo/bar")
        os.rmdir("tree/foo")
        creator = shelf.ShelfCreator(tree, tree.basis_tree())
        list(creator.iter_shelvable())
        creator.shelve_deletion(b"foo-id")
        creator.shelve_deletion(b"bar-id")
        with open("shelf", "w+b") as shelf_file:
            creator.write_shelf(shelf_file)
            creator.transform()
            creator.finalize()
        # validate the test setup
        self.assertEqual(tree.id2path(b"foo-id"), "foo")
        self.assertEqual(tree.id2path(b"bar-id"), "foo/bar")
        self.assertFileEqual(b"baz", "tree/foo/bar")
        with open("shelf", "r+b") as shelf_file:
            unshelver = shelf.Unshelver.from_tree_and_shelf(tree, shelf_file)
            self.addCleanup(unshelver.finalize)
            unshelver.make_merger().do_merge()
        self.assertRaises(errors.NoSuchId, tree.id2path, b"foo-id")
        self.assertRaises(errors.NoSuchId, tree.id2path, b"bar-id")

    def test_unshelve_base(self):
        tree = self.make_branch_and_tree("tree")
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.commit("rev1", rev_id=b"rev1")
        creator = shelf.ShelfCreator(tree, tree.basis_tree())
        self.addCleanup(creator.finalize)
        manager = tree.get_shelf_manager()
        shelf_id, shelf_file = manager.new_shelf()
        try:
            creator.write_shelf(shelf_file)
        finally:
            shelf_file.close()
        tree.commit("rev2", rev_id=b"rev2")
        shelf_file = manager.read_shelf(1)
        self.addCleanup(shelf_file.close)
        unshelver = shelf.Unshelver.from_tree_and_shelf(tree, shelf_file)
        self.addCleanup(unshelver.finalize)
        self.assertEqual(b"rev1", unshelver.base_tree.get_revision_id())

    def test_unshelve_serialization(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree_contents([("shelf", EMPTY_SHELF)])
        shelf_file = open("shelf", "rb")
        self.addCleanup(shelf_file.close)
        unshelver = shelf.Unshelver.from_tree_and_shelf(tree, shelf_file)
        unshelver.finalize()

    def test_corrupt_shelf(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree_contents([("shelf", EMPTY_SHELF.replace(b"metadata", b"foo"))])
        shelf_file = open("shelf", "rb")
        self.addCleanup(shelf_file.close)
        e = self.assertRaises(
            shelf.ShelfCorrupt, shelf.Unshelver.from_tree_and_shelf, tree, shelf_file
        )
        self.assertEqual("Shelf corrupt.", str(e))

    def test_unshelve_subdir_in_now_removed_dir(self):
        tree = self.make_branch_and_tree(".")
        self.addCleanup(tree.lock_write().unlock)
        self.build_tree(["dir/", "dir/subdir/", "dir/subdir/foo"])
        tree.add(["dir"], ids=[b"dir-id"])
        tree.commit("versioned dir")
        tree.add(["dir/subdir", "dir/subdir/foo"], ids=[b"subdir-id", b"foo-id"])
        creator = shelf.ShelfCreator(tree, tree.basis_tree())
        self.addCleanup(creator.finalize)
        for change in creator.iter_shelvable():
            creator.shelve_change(change)
        shelf_manager = tree.get_shelf_manager()
        shelf_id = shelf_manager.shelve_changes(creator)
        self.assertPathDoesNotExist("dir/subdir")
        tree.remove(["dir"])
        unshelver = shelf_manager.get_unshelver(shelf_id)
        self.addCleanup(unshelver.finalize)
        unshelver.make_merger().do_merge()
        self.assertPathExists("dir/subdir/foo")
        self.assertEqual(b"dir-id", tree.path2id("dir"))
        self.assertEqual(b"subdir-id", tree.path2id("dir/subdir"))
        self.assertEqual(b"foo-id", tree.path2id("dir/subdir/foo"))


class TestShelfManager(tests.TestCaseWithTransport):
    def test_get_shelf_manager(self):
        tree = self.make_branch_and_tree(".")
        manager = tree.get_shelf_manager()
        self.assertEqual(tree._transport.base + "shelf/", manager.transport.base)

    def get_manager(self):
        return self.make_branch_and_tree(".").get_shelf_manager()

    def test_get_shelf_filename(self):
        tree = self.make_branch_and_tree(".")
        manager = tree.get_shelf_manager()
        self.assertEqual("shelf-1", manager.get_shelf_filename(1))

    def test_get_shelf_ids(self):
        tree = self.make_branch_and_tree(".")
        manager = tree.get_shelf_manager()
        self.assertEqual(
            [1, 3], manager.get_shelf_ids(["shelf-1", "shelf-02", "shelf-3"])
        )

    def test_new_shelf(self):
        manager = self.get_manager()
        shelf_id, shelf_file = manager.new_shelf()
        shelf_file.close()
        self.assertEqual(1, shelf_id)
        shelf_id, shelf_file = manager.new_shelf()
        shelf_file.close()
        self.assertEqual(2, shelf_id)
        manager.delete_shelf(1)
        shelf_id, shelf_file = manager.new_shelf()
        shelf_file.close()
        self.assertEqual(3, shelf_id)

    def test_active_shelves(self):
        manager = self.get_manager()
        self.assertEqual([], manager.active_shelves())
        shelf_id, shelf_file = manager.new_shelf()
        shelf_file.close()
        self.assertEqual([1], manager.active_shelves())

    def test_delete_shelf(self):
        manager = self.get_manager()
        shelf_id, shelf_file = manager.new_shelf()
        shelf_file.close()
        self.assertEqual([1], manager.active_shelves())
        manager.delete_shelf(1)
        self.assertEqual([], manager.active_shelves())

    def test_last_shelf(self):
        manager = self.get_manager()
        self.assertIs(None, manager.last_shelf())
        shelf_id, shelf_file = manager.new_shelf()
        shelf_file.close()
        self.assertEqual(1, manager.last_shelf())

    def test_read_shelf(self):
        manager = self.get_manager()
        shelf_id, shelf_file = manager.new_shelf()
        try:
            shelf_file.write(b"foo")
        finally:
            shelf_file.close()
        shelf_id, shelf_file = manager.new_shelf()
        try:
            shelf_file.write(b"bar")
        finally:
            shelf_file.close()
        shelf_file = manager.read_shelf(1)
        try:
            self.assertEqual(b"foo", shelf_file.read())
        finally:
            shelf_file.close()
        shelf_file = manager.read_shelf(2)
        try:
            self.assertEqual(b"bar", shelf_file.read())
        finally:
            shelf_file.close()

    def test_read_non_existant(self):
        manager = self.get_manager()
        e = self.assertRaises(shelf.NoSuchShelfId, manager.read_shelf, 1)
        self.assertEqual('No changes are shelved with id "1".', str(e))

    def test_shelve_changes(self):
        tree = self.make_branch_and_tree("tree")
        tree.commit("no-change commit")
        tree.lock_write()
        self.addCleanup(tree.unlock)
        self.build_tree_contents([("tree/foo", b"bar")])
        self.assertFileEqual(b"bar", "tree/foo")
        tree.add("foo", ids=b"foo-id")
        creator = shelf.ShelfCreator(tree, tree.basis_tree())
        self.addCleanup(creator.finalize)
        list(creator.iter_shelvable())
        creator.shelve_creation(b"foo-id")
        shelf_manager = tree.get_shelf_manager()
        shelf_id = shelf_manager.shelve_changes(creator)
        self.assertPathDoesNotExist("tree/foo")
        unshelver = shelf_manager.get_unshelver(shelf_id)
        self.addCleanup(unshelver.finalize)
        unshelver.make_merger().do_merge()
        self.assertFileEqual(b"bar", "tree/foo")

    def test_get_metadata(self):
        tree = self.make_branch_and_tree(".")
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        creator = shelf.ShelfCreator(tree, tree.basis_tree())
        self.addCleanup(creator.finalize)
        shelf_manager = tree.get_shelf_manager()
        shelf_id = shelf_manager.shelve_changes(creator, "foo")
        metadata = shelf_manager.get_metadata(shelf_id)
        self.assertEqual("foo", metadata[b"message"])
        self.assertEqual(b"null:", metadata[b"revision_id"])
