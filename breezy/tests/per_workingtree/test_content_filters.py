# Copyright (C) 2008, 2009, 2010, 2012, 2016 Canonical Ltd
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

"""Tests for content filtering conformance."""

import os

from breezy.filters import ContentFilter
from breezy.tests.per_workingtree import TestCaseWithWorkingTree

from ...controldir import ControlDir
from ...switch import switch
from ...workingtree import WorkingTree


def _converter_helper(chunks, fn):
    result = []
    for chunk in chunks:
        result.append(getattr(chunk, fn)())
    return iter(result)


def _swapcase(chunks, context=None):
    """A converter that swaps the case of text."""
    return _converter_helper(chunks, "swapcase")


def _uppercase(chunks, context=None):
    """A converter that converts text to uppercase."""
    return _converter_helper(chunks, "upper")


def _lowercase(chunks, context=None):
    """A converter that converts text to lowercase."""
    return _converter_helper(chunks, "lower")


_trailer_string = b"\nend string\n"


def _append_text(chunks, context=None):
    """A content filter that appends a string to the end of the file.

    This tests filters that change the length.
    """
    return chunks + [_trailer_string]


def _remove_appended_text(chunks, context=None):
    """Remove the appended text."""
    text = b"".join(chunks)
    if text.endswith(_trailer_string):
        text = text[: -len(_trailer_string)]
    return [text]


class TestWorkingTreeWithContentFilters(TestCaseWithWorkingTree):
    def create_cf_tree(self, txt_reader, txt_writer, dir="."):
        tree = self.make_branch_and_tree(dir)

        def _content_filter_stack(path=None, file_id=None):
            if path.endswith(".txt"):
                return [ContentFilter(txt_reader, txt_writer)]
            else:
                return []

        tree._content_filter_stack = _content_filter_stack
        self.build_tree_contents(
            [(dir + "/file1.txt", b"Foo Txt"), (dir + "/file2.bin", b"Foo Bin")]
        )
        tree.add(["file1.txt", "file2.bin"])
        tree.commit("commit raw content")
        return tree, "file1.txt", "file2.bin"

    def create_cf_tree_with_two_revisions(self, txt_reader, txt_writer, dir="."):
        tree = self.make_branch_and_tree(dir)

        def _content_filter_stack(path=None, file_id=None):
            if path.endswith(".txt"):
                return [ContentFilter(txt_reader, txt_writer)]
            else:
                return []

        tree._content_filter_stack = _content_filter_stack
        self.build_tree_contents(
            [
                (dir + "/file1.txt", b"Foo Txt"),
                (dir + "/file2.bin", b"Foo Bin"),
                (dir + "/file3.txt", b"Bar Txt"),
            ]
        )
        tree.add(["file1.txt", "file2.bin", "file3.txt"])
        tree.commit("commit raw content")
        # Commit another revision with various changes. We make sure
        # the change includes a modification, an addition and a deletion.
        # Renames are more complex and need a separate set of tests later.
        self.build_tree_contents(
            [
                (dir + "/file1.txt", b"Foo ROCKS!"),
                (dir + "/file4.txt", b"Hello World"),
            ]
        )
        tree.add(["file4.txt"])
        tree.remove(["file3.txt"], keep_files=False)
        tree.commit("change, add and rename stuff")
        return tree, "file1.txt", "file2.bin", "file3.txt", "file4.txt"

    def patch_in_content_filter(self):
        # Patch in a custom, symmetric content filter stack. It's pretty gross
        # that we need to monkey-patch a class method to do this, bit it's
        # the easiest way currently given we don't have easy access to the
        # WorkingTree after it is created but before the filter stack is used
        # to populate content.
        def new_stack(tree, path=None, file_id=None):
            if path.endswith(".txt"):
                return [ContentFilter(_swapcase, _swapcase)]
            else:
                return []

        self.overrideAttr(WorkingTree, "_content_filter_stack", new_stack)

    def assert_basis_content(self, expected_content, branch, path):
        # Note: We need to use try/finally here instead of addCleanup()
        # as the latter leaves the read lock in place too long
        basis = branch.basis_tree()
        with basis.lock_read():
            self.assertEqual(expected_content, basis.get_file_text(path))

    def test_symmetric_content_filtering(self):
        # test handling when read then write gives back the initial content
        tree, txt_path, bin_path = self.create_cf_tree(
            txt_reader=_swapcase, txt_writer=_swapcase
        )
        # Check that the basis tree has the expected content
        basis = tree.basis_tree()
        basis.lock_read()
        self.addCleanup(basis.unlock)
        expected = b"fOO tXT" if tree.supports_content_filtering() else b"Foo Txt"
        self.assertEqual(expected, basis.get_file_text(txt_path))
        self.assertEqual(b"Foo Bin", basis.get_file_text(bin_path))
        # Check that the working tree has the original content
        tree.lock_read()
        self.addCleanup(tree.unlock)
        with tree.get_file(txt_path, filtered=False) as f:
            self.assertEqual(b"Foo Txt", f.read())
        with tree.get_file(bin_path, filtered=False) as f:
            self.assertEqual(b"Foo Bin", f.read())

    def test_readonly_content_filtering(self):
        # test handling with a read filter but no write filter
        tree, txt_path, bin_path = self.create_cf_tree(
            txt_reader=_uppercase, txt_writer=None
        )
        # Check that the basis tree has the expected content
        basis = tree.basis_tree()
        basis.lock_read()
        self.addCleanup(basis.unlock)
        expected = b"FOO TXT" if tree.supports_content_filtering() else b"Foo Txt"
        self.assertEqual(expected, basis.get_file_text(txt_path))
        self.assertEqual(b"Foo Bin", basis.get_file_text(bin_path))
        # We expect the workingtree content to be unchanged (for now at least)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        with tree.get_file(txt_path, filtered=False) as f:
            self.assertEqual(b"Foo Txt", f.read())
        with tree.get_file(bin_path, filtered=False) as f:
            self.assertEqual(b"Foo Bin", f.read())

    def test_branch_source_filtered_target_not(self):
        # Create a source branch with content filtering
        source, txt_path, _bin_path = self.create_cf_tree(
            txt_reader=_uppercase, txt_writer=_lowercase, dir="source"
        )
        if not source.supports_content_filtering():
            return
        self.assertFileEqual(b"Foo Txt", "source/file1.txt")
        self.assert_basis_content(b"FOO TXT", source, txt_path)

        # Now branch it
        self.run_bzr("branch source target")
        target = WorkingTree.open("target")
        # Even though the content in source and target are different
        # due to different filters, iter_changes should be clean
        self.assertFileEqual(b"FOO TXT", "target/file1.txt")
        changes = target.changes_from(source.basis_tree())
        self.assertFalse(changes.has_changed())

    def test_branch_source_not_filtered_target_is(self):
        # Create a source branch with content filtering
        source, txt_path, _bin_path = self.create_cf_tree(
            txt_reader=None, txt_writer=None, dir="source"
        )
        if not source.supports_content_filtering():
            return
        self.assertFileEqual(b"Foo Txt", "source/file1.txt")
        self.assert_basis_content(b"Foo Txt", source, txt_path)

        # Now patch in content filtering and branch the source
        self.patch_in_content_filter()
        self.run_bzr("branch source target")
        target = WorkingTree.open("target")
        # Even though the content in source and target are different
        # due to different filters, iter_changes should be clean
        self.assertFileEqual(b"fOO tXT", "target/file1.txt")
        changes = target.changes_from(source.basis_tree())
        self.assertFalse(changes.has_changed())

    def test_path_content_summary(self):
        """path_content_summary should always talk about the canonical form."""
        # see https://bugs.launchpad.net/bzr/+bug/415508
        #
        # set up a tree where the canonical form has a string added to the
        # end
        source, txt_path, _bin_path = self.create_cf_tree(
            txt_reader=_append_text, txt_writer=_remove_appended_text, dir="source"
        )
        if not source.supports_content_filtering():
            return
        source.lock_read()
        self.addCleanup(source.unlock)

        expected_canonical_form = b"Foo Txt\nend string\n"
        with source.get_file(txt_path, filtered=True) as f:
            self.assertEqual(f.read(), expected_canonical_form)
        with source.get_file(txt_path, filtered=False) as f:
            self.assertEqual(f.read(), b"Foo Txt")

        # results are: kind, size, executable, sha1_or_link_target
        result = source.path_content_summary("file1.txt")

        self.assertEqual(result, ("file", None, False, None))

        # we could give back the length of the canonical form, but in general
        # that will be expensive to compute, so it's acceptable to just return
        # None.

    def test_content_filtering_applied_on_pull(self):
        # Create a source branch with two revisions
        source, path1, path2, path3, path4 = self.create_cf_tree_with_two_revisions(
            txt_reader=None, txt_writer=None, dir="source"
        )
        if not source.supports_content_filtering():
            return
        self.assertFileEqual(b"Foo ROCKS!", "source/file1.txt")
        self.assert_basis_content(b"Foo ROCKS!", source, path1)

        # Now patch in content filtering and branch from revision 1
        self.patch_in_content_filter()
        self.run_bzr("branch -r1 source target")
        target = WorkingTree.open("target")
        self.assert_basis_content(b"Foo Txt", target, path1)
        self.assertFileEqual(b"fOO tXT", "target/file1.txt")
        self.assert_basis_content(b"Foo Bin", target, path2)
        self.assertFileEqual(b"Foo Bin", "target/file2.bin")
        self.assert_basis_content(b"Bar Txt", target, path3)
        self.assertFileEqual(b"bAR tXT", "target/file3.txt")

        # Pull the latter change and check the target tree is updated
        self.run_bzr("pull -d target")
        self.assert_basis_content(b"Foo ROCKS!", target, path1)
        self.assertFileEqual(b"fOO rocks!", "target/file1.txt")
        self.assert_basis_content(b"Foo Bin", target, path2)
        self.assert_basis_content(b"Hello World", target, path4)
        self.assertFileEqual(b"hELLO wORLD", "target/file4.txt")

    def test_content_filtering_applied_on_merge(self):
        # Create a source branch with two revisions
        source, path1, path2, _path3, path4 = self.create_cf_tree_with_two_revisions(
            txt_reader=None, txt_writer=None, dir="source"
        )
        if not source.supports_content_filtering():
            return
        self.assert_basis_content(b"Foo ROCKS!", source, path1)
        self.assertFileEqual(b"Foo ROCKS!", "source/file1.txt")
        self.assert_basis_content(b"Foo Bin", source, path2)
        self.assert_basis_content(b"Hello World", source, path4)
        self.assertFileEqual(b"Hello World", "source/file4.txt")

        # Now patch in content filtering and branch from revision 1
        self.patch_in_content_filter()
        self.run_bzr("branch -r1 source target")
        target = WorkingTree.open("target")
        self.assert_basis_content(b"Foo Txt", target, path1)
        self.assertFileEqual(b"fOO tXT", "target/file1.txt")
        self.assertFileEqual(b"Foo Bin", "target/file2.bin")
        self.assertFileEqual(b"bAR tXT", "target/file3.txt")

        # Merge the latter change and check the target tree is updated
        self.run_bzr("merge -d target source")
        self.assertFileEqual(b"fOO rocks!", "target/file1.txt")
        self.assertFileEqual(b"hELLO wORLD", "target/file4.txt")

        # Commit the merge and check the right content is stored
        target.commit("merge file1.txt changes from source")
        self.assert_basis_content(b"Foo ROCKS!", target, path1)
        self.assert_basis_content(b"Hello World", target, path4)

    def test_content_filtering_applied_on_switch(self):
        # Create a source branch with two revisions
        source, _path1, _path2, _path3, _path4 = self.create_cf_tree_with_two_revisions(
            txt_reader=None, txt_writer=None, dir="branch-a"
        )
        if not source.supports_content_filtering():
            return

        # Now patch in content filtering and branch from revision 1
        self.patch_in_content_filter()
        self.run_bzr("branch -r1 branch-a branch-b")

        # Now create a lightweight checkout referring to branch-b
        self.run_bzr("checkout --lightweight branch-b checkout")
        self.assertFileEqual(b"fOO tXT", "checkout/file1.txt")

        # Switch it to branch-b and check the tree is updated
        checkout_control_dir = ControlDir.open_containing("checkout")[0]
        switch(checkout_control_dir, source.branch)
        self.assertFileEqual(b"fOO rocks!", "checkout/file1.txt")
        self.assertFileEqual(b"hELLO wORLD", "checkout/file4.txt")

    def test_content_filtering_applied_on_revert_delete(self):
        # Create a source branch with content filtering
        source, txt_path, _bin_path = self.create_cf_tree(
            txt_reader=_uppercase, txt_writer=_lowercase, dir="source"
        )
        if not source.supports_content_filtering():
            return
        self.assertFileEqual(b"Foo Txt", "source/file1.txt")
        self.assert_basis_content(b"FOO TXT", source, txt_path)

        # Now delete the file, revert it and check the content
        os.unlink("source/file1.txt")
        self.assertFalse(os.path.exists("source/file1.txt"))
        source.revert(["file1.txt"])
        self.assertTrue(os.path.exists("source/file1.txt"))
        # Note: we don't get back exactly what was in the tree
        # previously because lower(upper(text)) is a lossy transformation
        self.assertFileEqual(b"foo txt", "source/file1.txt")

    def test_content_filtering_applied_on_revert_rename(self):
        # Create a source branch with content filtering
        source, txt_path, _bin_path = self.create_cf_tree(
            txt_reader=_uppercase, txt_writer=_lowercase, dir="source"
        )
        if not source.supports_content_filtering():
            return
        self.assertFileEqual(b"Foo Txt", "source/file1.txt")
        self.assert_basis_content(b"FOO TXT", source, txt_path)

        # Now modify & rename a file, revert it and check the content
        self.build_tree_contents([("source/file1.txt", b"Foo Txt with new content")])
        source.rename_one("file1.txt", "file1.bin")
        self.assertTrue(os.path.exists("source/file1.bin"))
        self.assertFalse(os.path.exists("source/file1.txt"))
        self.assertFileEqual(b"Foo Txt with new content", "source/file1.bin")
        source.revert(["file1.bin"])
        self.assertFalse(os.path.exists("source/file1.bin"))
        self.assertTrue(os.path.exists("source/file1.txt"))
        # Note: we don't get back exactly what was in the tree
        # previously because lower(upper(text)) is a lossy transformation
        self.assertFileEqual(b"foo txt", "source/file1.txt")
