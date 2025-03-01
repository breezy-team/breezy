# Copyright (C) 2008-2011, 2016 Canonical Ltd
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
import sys
from io import BytesIO
from textwrap import dedent

from .. import errors, revision, shelf, shelf_ui, tests
from . import features, script


class ExpectShelver(shelf_ui.Shelver):
    """A variant of Shelver that intercepts console activity, for testing."""

    def __init__(
        self,
        work_tree,
        target_tree,
        diff_writer=None,
        auto=False,
        auto_apply=False,
        file_list=None,
        message=None,
        destroy=False,
        reporter=None,
    ):
        shelf_ui.Shelver.__init__(
            self,
            work_tree,
            target_tree,
            diff_writer,
            auto,
            auto_apply,
            file_list,
            message,
            destroy,
            reporter=reporter,
        )
        self.expected = []
        self.diff_writer = BytesIO()

    def expect(self, message, response):
        self.expected.append((message, response))

    def prompt(self, message, choices, default):
        try:
            expected_message, response = self.expected.pop(0)
        except IndexError:
            raise AssertionError("Unexpected prompt: {}".format(message))
        if message != expected_message:
            raise AssertionError("Wrong prompt: {}".format(message))
        if choices != "&yes\n&No\n&finish\n&quit":
            raise AssertionError("Wrong choices: {}".format(choices))
        return response


LINES_AJ = b"a\nb\nc\nd\ne\nf\ng\nh\ni\nj\n"


LINES_ZY = b"z\nb\nc\nd\ne\nf\ng\nh\ni\ny\n"


LINES_AY = b"a\nb\nc\nd\ne\nf\ng\nh\ni\ny\n"


class ShelfTestCase(tests.TestCaseWithTransport):
    def create_shelvable_tree(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree_contents([("tree/foo", LINES_AJ)])
        tree.add("foo", ids=b"foo-id")
        tree.commit("added foo")
        self.build_tree_contents([("tree/foo", LINES_ZY)])
        return tree


class TestShelver(ShelfTestCase):
    def test_unexpected_prompt_failure(self):
        tree = self.create_shelvable_tree()
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(tree, tree.basis_tree())
        self.addCleanup(shelver.finalize)
        e = self.assertRaises(AssertionError, shelver.run)
        self.assertEqual("Unexpected prompt: Shelve?", str(e))

    def test_wrong_prompt_failure(self):
        tree = self.create_shelvable_tree()
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(tree, tree.basis_tree())
        self.addCleanup(shelver.finalize)
        shelver.expect("foo", 0)
        e = self.assertRaises(AssertionError, shelver.run)
        self.assertEqual("Wrong prompt: Shelve?", str(e))

    def test_shelve_not_diff(self):
        tree = self.create_shelvable_tree()
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(tree, tree.basis_tree())
        self.addCleanup(shelver.finalize)
        shelver.expect("Shelve?", 1)
        shelver.expect("Shelve?", 1)
        # No final shelving prompt because no changes were selected
        shelver.run()
        self.assertFileEqual(LINES_ZY, "tree/foo")

    def test_shelve_diff_no(self):
        tree = self.create_shelvable_tree()
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(tree, tree.basis_tree())
        self.addCleanup(shelver.finalize)
        shelver.expect("Shelve?", 0)
        shelver.expect("Shelve?", 0)
        shelver.expect("Shelve 2 change(s)?", 1)
        shelver.run()
        self.assertFileEqual(LINES_ZY, "tree/foo")

    def test_shelve_diff(self):
        tree = self.create_shelvable_tree()
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(tree, tree.basis_tree())
        self.addCleanup(shelver.finalize)
        shelver.expect("Shelve?", 0)
        shelver.expect("Shelve?", 0)
        shelver.expect("Shelve 2 change(s)?", 0)
        shelver.run()
        self.assertFileEqual(LINES_AJ, "tree/foo")

    def test_shelve_one_diff(self):
        tree = self.create_shelvable_tree()
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(tree, tree.basis_tree())
        self.addCleanup(shelver.finalize)
        shelver.expect("Shelve?", 0)
        shelver.expect("Shelve?", 1)
        shelver.expect("Shelve 1 change(s)?", 0)
        shelver.run()
        self.assertFileEqual(LINES_AY, "tree/foo")

    def test_shelve_binary_change(self):
        tree = self.create_shelvable_tree()
        self.build_tree_contents([("tree/foo", b"\x00")])
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(tree, tree.basis_tree())
        self.addCleanup(shelver.finalize)
        shelver.expect("Shelve binary changes?", 0)
        shelver.expect("Shelve 1 change(s)?", 0)
        shelver.run()
        self.assertFileEqual(LINES_AJ, "tree/foo")

    def test_shelve_rename(self):
        tree = self.create_shelvable_tree()
        tree.rename_one("foo", "bar")
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(tree, tree.basis_tree())
        self.addCleanup(shelver.finalize)
        shelver.expect('Shelve renaming "foo" => "bar"?', 0)
        shelver.expect("Shelve?", 0)
        shelver.expect("Shelve?", 0)
        shelver.expect("Shelve 3 change(s)?", 0)
        shelver.run()
        self.assertFileEqual(LINES_AJ, "tree/foo")

    def test_shelve_deletion(self):
        tree = self.create_shelvable_tree()
        os.unlink("tree/foo")
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(tree, tree.basis_tree())
        self.addCleanup(shelver.finalize)
        shelver.expect('Shelve removing file "foo"?', 0)
        shelver.expect("Shelve 1 change(s)?", 0)
        shelver.run()
        self.assertFileEqual(LINES_AJ, "tree/foo")

    def test_shelve_creation(self):
        tree = self.make_branch_and_tree("tree")
        tree.commit("add tree root")
        self.build_tree(["tree/foo"])
        tree.add("foo")
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(tree, tree.basis_tree())
        self.addCleanup(shelver.finalize)
        shelver.expect('Shelve adding file "foo"?', 0)
        shelver.expect("Shelve 1 change(s)?", 0)
        shelver.run()
        self.assertPathDoesNotExist("tree/foo")

    def test_shelve_kind_change(self):
        tree = self.create_shelvable_tree()
        os.unlink("tree/foo")
        os.mkdir("tree/foo")
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(tree, tree.basis_tree())
        self.addCleanup(shelver.finalize)
        shelver.expect('Shelve changing "foo" from file to directory?', 0)
        shelver.expect("Shelve 1 change(s)?", 0)

    def test_shelve_modify_target(self):
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        tree = self.create_shelvable_tree()
        os.symlink("bar", "tree/baz")
        tree.add("baz", ids=b"baz-id")
        tree.commit("Add symlink")
        os.unlink("tree/baz")
        os.symlink("vax", "tree/baz")
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(tree, tree.basis_tree())
        self.addCleanup(shelver.finalize)
        shelver.expect('Shelve changing target of "baz" from "bar" to "vax"?', 0)
        shelver.expect("Shelve 1 change(s)?", 0)
        shelver.run()
        self.assertEqual("bar", os.readlink("tree/baz"))

    def test_shelve_finish(self):
        tree = self.create_shelvable_tree()
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(tree, tree.basis_tree())
        self.addCleanup(shelver.finalize)
        shelver.expect("Shelve?", 2)
        shelver.expect("Shelve 2 change(s)?", 0)
        shelver.run()
        self.assertFileEqual(LINES_AJ, "tree/foo")

    def test_shelve_quit(self):
        tree = self.create_shelvable_tree()
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(tree, tree.basis_tree())
        self.addCleanup(shelver.finalize)
        shelver.expect("Shelve?", 3)
        self.assertRaises(errors.UserAbort, shelver.run)
        self.assertFileEqual(LINES_ZY, "tree/foo")

    def test_shelve_all(self):
        self.create_shelvable_tree()
        shelver = ExpectShelver.from_args(sys.stdout, all=True, directory="tree")
        try:
            shelver.run()
        finally:
            shelver.finalize()
        self.assertFileEqual(LINES_AJ, "tree/foo")

    def test_shelve_filename(self):
        tree = self.create_shelvable_tree()
        self.build_tree(["tree/bar"])
        tree.add("bar")
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(tree, tree.basis_tree(), file_list=["bar"])
        self.addCleanup(shelver.finalize)
        shelver.expect('Shelve adding file "bar"?', 0)
        shelver.expect("Shelve 1 change(s)?", 0)
        shelver.run()

    def test_shelve_destroy(self):
        tree = self.create_shelvable_tree()
        shelver = shelf_ui.Shelver.from_args(
            sys.stdout, all=True, directory="tree", destroy=True
        )
        self.addCleanup(shelver.finalize)
        shelver.run()
        self.assertIs(None, tree.get_shelf_manager().last_shelf())
        self.assertFileEqual(LINES_AJ, "tree/foo")

    @staticmethod
    def shelve_all(tree, target_revision_id):
        tree.lock_write()
        try:
            target = tree.branch.repository.revision_tree(target_revision_id)
            shelver = shelf_ui.Shelver(tree, target, auto=True, auto_apply=True)
            try:
                shelver.run()
            finally:
                shelver.finalize()
        finally:
            tree.unlock()

    def test_shelve_old_root_preserved(self):
        tree1 = self.make_branch_and_tree("tree1")
        tree1.commit("add root")
        tree1_root_id = tree1.path2id("")
        tree2 = self.make_branch_and_tree("tree2")
        rev2 = tree2.commit("add root")
        self.assertNotEqual(tree1_root_id, tree2.path2id(""))
        tree1.merge_from_branch(tree2.branch, from_revision=revision.NULL_REVISION)
        tree1.commit("merging in tree2")
        self.assertEqual(tree1_root_id, tree1.path2id(""))
        # This is essentially assertNotRaises(InconsistentDelta)
        # With testtools 0.9.9, it can be rewritten as:
        # with ExpectedException(AssertionError,
        #                        'InconsistentDelta not raised'):
        #     with ExpectedException(errors.InconsistentDelta, ''):
        #         self.shelve_all(tree1, rev2)
        e = self.assertRaises(
            AssertionError,
            self.assertRaises,
            errors.InconsistentDelta,
            self.shelve_all,
            tree1,
            rev2,
        )
        self.assertContainsRe("InconsistentDelta not raised", str(e))

    def test_shelve_split(self):
        outer_tree = self.make_branch_and_tree("outer")
        outer_tree.commit("Add root")
        inner_tree = self.make_branch_and_tree("outer/inner")
        rev2 = inner_tree.commit("Add root")
        outer_tree.subsume(inner_tree)
        # This is essentially assertNotRaises(ValueError).
        # The ValueError is 'None is not a valid file id'.
        self.expectFailure(
            "Cannot shelve a join back to the inner tree.",
            self.assertRaises,
            AssertionError,
            self.assertRaises,
            ValueError,
            self.shelve_all,
            outer_tree,
            rev2,
        )


class TestApplyReporter(ShelfTestCase):
    def test_shelve_not_diff(self):
        tree = self.create_shelvable_tree()
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(
            tree, tree.basis_tree(), reporter=shelf_ui.ApplyReporter()
        )
        self.addCleanup(shelver.finalize)
        shelver.expect("Apply change?", 1)
        shelver.expect("Apply change?", 1)
        # No final shelving prompt because no changes were selected
        shelver.run()
        self.assertFileEqual(LINES_ZY, "tree/foo")

    def test_shelve_diff_no(self):
        tree = self.create_shelvable_tree()
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(
            tree, tree.basis_tree(), reporter=shelf_ui.ApplyReporter()
        )
        self.addCleanup(shelver.finalize)
        shelver.expect("Apply change?", 0)
        shelver.expect("Apply change?", 0)
        shelver.expect("Apply 2 change(s)?", 1)
        shelver.run()
        self.assertFileEqual(LINES_ZY, "tree/foo")

    def test_shelve_diff(self):
        tree = self.create_shelvable_tree()
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(
            tree, tree.basis_tree(), reporter=shelf_ui.ApplyReporter()
        )
        self.addCleanup(shelver.finalize)
        shelver.expect("Apply change?", 0)
        shelver.expect("Apply change?", 0)
        shelver.expect("Apply 2 change(s)?", 0)
        shelver.run()
        self.assertFileEqual(LINES_AJ, "tree/foo")

    def test_shelve_binary_change(self):
        tree = self.create_shelvable_tree()
        self.build_tree_contents([("tree/foo", b"\x00")])
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(
            tree, tree.basis_tree(), reporter=shelf_ui.ApplyReporter()
        )
        self.addCleanup(shelver.finalize)
        shelver.expect("Apply binary changes?", 0)
        shelver.expect("Apply 1 change(s)?", 0)
        shelver.run()
        self.assertFileEqual(LINES_AJ, "tree/foo")

    def test_shelve_rename(self):
        tree = self.create_shelvable_tree()
        tree.rename_one("foo", "bar")
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(
            tree, tree.basis_tree(), reporter=shelf_ui.ApplyReporter()
        )
        self.addCleanup(shelver.finalize)
        shelver.expect('Rename "bar" => "foo"?', 0)
        shelver.expect("Apply change?", 0)
        shelver.expect("Apply change?", 0)
        shelver.expect("Apply 3 change(s)?", 0)
        shelver.run()
        self.assertFileEqual(LINES_AJ, "tree/foo")

    def test_shelve_deletion(self):
        tree = self.create_shelvable_tree()
        os.unlink("tree/foo")
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(
            tree, tree.basis_tree(), reporter=shelf_ui.ApplyReporter()
        )
        self.addCleanup(shelver.finalize)
        shelver.expect('Add file "foo"?', 0)
        shelver.expect("Apply 1 change(s)?", 0)
        shelver.run()
        self.assertFileEqual(LINES_AJ, "tree/foo")

    def test_shelve_creation(self):
        tree = self.make_branch_and_tree("tree")
        tree.commit("add tree root")
        self.build_tree(["tree/foo"])
        tree.add("foo")
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(
            tree, tree.basis_tree(), reporter=shelf_ui.ApplyReporter()
        )
        self.addCleanup(shelver.finalize)
        shelver.expect('Delete file "foo"?', 0)
        shelver.expect("Apply 1 change(s)?", 0)
        shelver.run()
        self.assertPathDoesNotExist("tree/foo")

    def test_shelve_kind_change(self):
        tree = self.create_shelvable_tree()
        os.unlink("tree/foo")
        os.mkdir("tree/foo")
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(
            tree, tree.basis_tree(), reporter=shelf_ui.ApplyReporter()
        )
        self.addCleanup(shelver.finalize)
        shelver.expect('Change "foo" from directory to a file?', 0)
        shelver.expect("Apply 1 change(s)?", 0)

    def test_shelve_modify_target(self):
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        tree = self.create_shelvable_tree()
        os.symlink("bar", "tree/baz")
        tree.add("baz", ids=b"baz-id")
        tree.commit("Add symlink")
        os.unlink("tree/baz")
        os.symlink("vax", "tree/baz")
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(
            tree, tree.basis_tree(), reporter=shelf_ui.ApplyReporter()
        )
        self.addCleanup(shelver.finalize)
        shelver.expect('Change target of "baz" from "vax" to "bar"?', 0)
        shelver.expect("Apply 1 change(s)?", 0)
        shelver.run()
        self.assertEqual("bar", os.readlink("tree/baz"))


class TestUnshelver(tests.TestCaseWithTransport):
    def create_tree_with_shelf(self):
        tree = self.make_branch_and_tree("tree")
        tree.lock_write()
        try:
            self.build_tree_contents([("tree/foo", LINES_AJ)])
            tree.add("foo", ids=b"foo-id")
            tree.commit("added foo")
            self.build_tree_contents([("tree/foo", LINES_ZY)])
            shelver = shelf_ui.Shelver(
                tree, tree.basis_tree(), auto_apply=True, auto=True
            )
            try:
                shelver.run()
            finally:
                shelver.finalize()
        finally:
            tree.unlock()
        return tree

    def test_unshelve(self):
        tree = self.create_tree_with_shelf()
        tree.lock_write()
        self.addCleanup(tree.unlock)
        manager = tree.get_shelf_manager()
        shelf_ui.Unshelver(tree, manager, 1, True, True, True).run()
        self.assertFileEqual(LINES_ZY, "tree/foo")

    def test_unshelve_args(self):
        tree = self.create_tree_with_shelf()
        unshelver = shelf_ui.Unshelver.from_args(directory="tree")
        try:
            unshelver.run()
        finally:
            unshelver.tree.unlock()
        self.assertFileEqual(LINES_ZY, "tree/foo")
        self.assertIs(None, tree.get_shelf_manager().last_shelf())

    def test_unshelve_args_dry_run(self):
        tree = self.create_tree_with_shelf()
        unshelver = shelf_ui.Unshelver.from_args(directory="tree", action="dry-run")
        try:
            unshelver.run()
        finally:
            unshelver.tree.unlock()
        self.assertFileEqual(LINES_AJ, "tree/foo")
        self.assertEqual(1, tree.get_shelf_manager().last_shelf())

    def test_unshelve_args_preview(self):
        tree = self.create_tree_with_shelf()
        write_diff_to = BytesIO()
        unshelver = shelf_ui.Unshelver.from_args(
            directory="tree", action="preview", write_diff_to=write_diff_to
        )
        try:
            unshelver.run()
        finally:
            unshelver.tree.unlock()
        # The changes were not unshelved.
        self.assertFileEqual(LINES_AJ, "tree/foo")
        self.assertEqual(1, tree.get_shelf_manager().last_shelf())

        # But the diff was written to write_diff_to.
        diff = write_diff_to.getvalue()
        expected = dedent("""\
            @@ -1,4 +1,4 @@
            -a
            +z
             b
             c
             d
            @@ -7,4 +7,4 @@
             g
             h
             i
            -j
            +y

            """)
        self.assertEqualDiff(expected.encode("utf-8"), diff[-len(expected) :])

    def test_unshelve_args_delete_only(self):
        tree = self.make_branch_and_tree("tree")
        manager = tree.get_shelf_manager()
        shelf_file = manager.new_shelf()[1]
        try:
            shelf_file.write(b"garbage")
        finally:
            shelf_file.close()
        unshelver = shelf_ui.Unshelver.from_args(directory="tree", action="delete-only")
        try:
            unshelver.run()
        finally:
            unshelver.tree.unlock()
        self.assertIs(None, manager.last_shelf())

    def test_unshelve_args_invalid_shelf_id(self):
        tree = self.make_branch_and_tree("tree")
        manager = tree.get_shelf_manager()
        shelf_file = manager.new_shelf()[1]
        try:
            shelf_file.write(b"garbage")
        finally:
            shelf_file.close()
        self.assertRaises(
            shelf.InvalidShelfId,
            shelf_ui.Unshelver.from_args,
            directory="tree",
            action="delete-only",
            shelf_id="foo",
        )


class TestUnshelveScripts(TestUnshelver, script.TestCaseWithTransportAndScript):
    def test_unshelve_messages_keep(self):
        self.create_tree_with_shelf()
        self.run_script("""
$ cd tree
$ brz unshelve --keep
2>Using changes with id "1".
2> M  foo
2>All changes applied successfully.
""")

    def test_unshelve_messages_delete(self):
        self.create_tree_with_shelf()
        self.run_script("""
$ cd tree
$ brz unshelve --delete-only
2>Deleted changes with id "1".
""")

    def test_unshelve_messages_apply(self):
        self.create_tree_with_shelf()
        self.run_script("""
$ cd tree
$ brz unshelve --apply
2>Using changes with id "1".
2> M  foo
2>All changes applied successfully.
2>Deleted changes with id "1".
""")

    def test_unshelve_messages_dry_run(self):
        self.create_tree_with_shelf()
        self.run_script("""
$ cd tree
$ brz unshelve --dry-run
2>Using changes with id "1".
2> M  foo
""")
