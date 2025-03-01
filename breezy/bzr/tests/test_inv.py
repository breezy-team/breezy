# Copyright (C) 2005-2012, 2016 Canonical Ltd
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


from ... import errors, osutils, repository, revision, tests, workingtree
from ...tests.scenarios import load_tests_apply_scenarios
from .. import chk_map, groupcompress, inventory
from ..inventory import (
    ROOT_ID,
    CHKInventory,
    DuplicateFileId,
    InvalidEntryName,
    Inventory,
    InventoryDirectory,
    InventoryEntry,
    InventoryFile,
    TreeReference,
    mutable_inventory_from_tree,
)
from . import TestCase, TestCaseWithTransport

load_tests = load_tests_apply_scenarios


def delta_application_scenarios():
    scenarios = [
        ("Inventory", {"apply_delta": apply_inventory_Inventory}),
    ]
    # Working tree basis delta application
    # Repository add_inv_by_delta.
    # Reduce form of the per_repository test logic - that logic needs to be
    # be able to get /just/ repositories whereas these tests are fine with
    # just creating trees.
    for _, format in repository.format_registry.iteritems():
        if format.supports_full_versioned_files:
            scenarios.append(
                (
                    str(format.__name__),
                    {
                        "apply_delta": apply_inventory_Repository_add_inventory_by_delta,
                        "format": format,
                    },
                )
            )
    for getter in workingtree.format_registry._get_all_lazy():
        try:
            format = getter()
            if callable(format):
                format = format()
        except ImportError:
            pass  # Format with unmet dependency
        repo_fmt = format._matchingcontroldir.repository_format
        if not repo_fmt.supports_full_versioned_files:
            continue
        scenarios.append(
            (
                str(format.__class__.__name__) + ".update_basis_by_delta",
                {"apply_delta": apply_inventory_WT_basis, "format": format},
            )
        )
        scenarios.append(
            (
                str(format.__class__.__name__) + ".apply_inventory_delta",
                {"apply_delta": apply_inventory_WT, "format": format},
            )
        )
    return scenarios


def create_texts_for_inv(repo, inv):
    for _path, ie in inv.iter_entries():
        if ie.text_size:
            lines = [b"a" * ie.text_size]
        else:
            lines = []
        repo.texts.add_lines((ie.file_id, ie.revision), [], lines)


def apply_inventory_Inventory(self, basis, delta, invalid_delta=True):
    """Apply delta to basis and return the result.

    :param basis: An inventory to be used as the basis.
    :param delta: The inventory delta to apply:
    :return: An inventory resulting from the application.
    """
    basis.apply_delta(delta)
    return basis


def apply_inventory_WT(self, basis, delta, invalid_delta=True):
    """Apply delta to basis and return the result.

    This sets the tree state to be basis, and then calls apply_inventory_delta.

    :param basis: An inventory to be used as the basis.
    :param delta: The inventory delta to apply:
    :return: An inventory resulting from the application.
    """
    control = self.make_controldir("tree", format=self.format._matchingcontroldir)
    control.create_repository()
    control.create_branch()
    tree = self.format.initialize(control)
    tree.lock_write()
    try:
        tree._write_inventory(basis)
    finally:
        tree.unlock()
    # Fresh object, reads disk again.
    tree = tree.controldir.open_workingtree()
    tree.lock_write()
    try:
        tree.apply_inventory_delta(delta)
    finally:
        tree.unlock()
    # reload tree - ensure we get what was written.
    tree = tree.controldir.open_workingtree()
    tree.lock_read()
    self.addCleanup(tree.unlock)
    if not invalid_delta:
        tree._validate()
    return tree.root_inventory


def _create_repo_revisions(repo, basis, delta, invalid_delta):
    with repository.WriteGroup(repo):
        rev = revision.Revision(
            b"basis",
            timestamp=0,
            timezone=None,
            message="",
            committer="foo@example.com",
        )
        basis.revision_id = b"basis"
        create_texts_for_inv(repo, basis)
        repo.add_revision(b"basis", rev, basis)
        if invalid_delta:
            # We don't want to apply the delta to the basis, because we expect
            # the delta is invalid.
            result_inv = basis
            result_inv.revision_id = b"result"
            target_entries = None
        else:
            result_inv = basis.create_by_apply_delta(delta, b"result")
            create_texts_for_inv(repo, result_inv)
            target_entries = list(result_inv.iter_entries_by_dir())
        rev = revision.Revision(
            b"result",
            timestamp=0,
            timezone=None,
            message="",
            committer="foo@example.com",
        )
        repo.add_revision(b"result", rev, result_inv)
    return target_entries


def _get_basis_entries(tree):
    basis_tree = tree.basis_tree()
    with basis_tree.lock_read():
        return list(basis_tree.inventory.iter_entries_by_dir())


def _populate_different_tree(tree, basis, delta):
    """Put all entries into tree, but at a unique location."""
    added_ids = set()
    tree.add(["unique-dir"], ["directory"], [b"unique-dir-id"])
    for _path, ie in basis.iter_entries_by_dir():
        if ie.file_id in added_ids:
            continue
        # We want a unique path for each of these, we use the file-id
        tree.add(["unique-dir/" + ie.file_id], [ie.kind], [ie.file_id])
        added_ids.add(ie.file_id)
    for _old_path, _new_path, file_id, ie in delta:
        if file_id in added_ids:
            continue
        tree.add(["unique-dir/" + file_id], [ie.kind], [file_id])


def apply_inventory_WT_basis(test, basis, delta, invalid_delta=True):
    """Apply delta to basis and return the result.

    This sets the parent and then calls update_basis_by_delta.
    It also puts the basis in the repository under both 'basis' and 'result' to
    allow safety checks made by the WT to succeed, and finally ensures that all
    items in the delta with a new path are present in the WT before calling
    update_basis_by_delta.

    :param basis: An inventory to be used as the basis.
    :param delta: The inventory delta to apply:
    :return: An inventory resulting from the application.
    """
    control = test.make_controldir("tree", format=test.format._matchingcontroldir)
    control.create_repository()
    control.create_branch()
    tree = test.format.initialize(control)
    tree.lock_write()
    try:
        target_entries = _create_repo_revisions(
            tree.branch.repository, basis, delta, invalid_delta
        )
        # Set the basis state as the trees current state
        tree._write_inventory(basis)
        # This reads basis from the repo and puts it into the tree's local
        # cache, if it has one.
        tree.set_parent_ids([b"basis"])
    finally:
        tree.unlock()
    # Fresh lock, reads disk again.
    with tree.lock_write():
        tree.update_basis_by_delta(b"result", delta)
        if not invalid_delta:
            tree._validate()
    # reload tree - ensure we get what was written.
    tree = tree.controldir.open_workingtree()
    basis_tree = tree.basis_tree()
    basis_tree.lock_read()
    test.addCleanup(basis_tree.unlock)
    basis_inv = basis_tree.root_inventory
    if target_entries:
        basis_entries = list(basis_inv.iter_entries_by_dir())
        test.assertEqual(target_entries, basis_entries)
    return basis_inv


def apply_inventory_Repository_add_inventory_by_delta(
    self, basis, delta, invalid_delta=True
):
    """Apply delta to basis and return the result.

    This inserts basis as a whole inventory and then uses
    add_inventory_by_delta to add delta.

    :param basis: An inventory to be used as the basis.
    :param delta: The inventory delta to apply:
    :return: An inventory resulting from the application.
    """
    format = self.format()
    control = self.make_controldir("tree", format=format._matchingcontroldir)
    repo = format.initialize(control)
    with repo.lock_write(), repository.WriteGroup(repo):
        rev = revision.Revision(
            b"basis",
            timestamp=0,
            timezone=None,
            message="",
            committer="foo@example.com",
        )
        basis.revision_id = b"basis"
        create_texts_for_inv(repo, basis)
        repo.add_revision(b"basis", rev, basis)
    with repo.lock_write(), repository.WriteGroup(repo):
        repo.add_inventory_by_delta(b"basis", delta, b"result", [b"basis"])
    # Fresh lock, reads disk again.
    repo = repo.controldir.open_repository()
    repo.lock_read()
    self.addCleanup(repo.unlock)
    return repo.get_inventory(b"result")


class TestInventoryUpdates(TestCase):
    def test_creation_from_root_id(self):
        # iff a root id is passed to the constructor, a root directory is made
        inv = inventory.Inventory(root_id=b"tree-root")
        self.assertNotEqual(None, inv.root)
        self.assertEqual(b"tree-root", inv.root.file_id)

    def test_add_path_of_root(self):
        # if no root id is given at creation time, there is no root directory
        inv = inventory.Inventory(root_id=None)
        self.assertIs(None, inv.root)
        # add a root entry by adding its path
        ie = inv.add_path("", "directory", b"my-root")
        ie.revision = b"test-rev"
        self.assertEqual(b"my-root", ie.file_id)
        self.assertIs(ie, inv.root)

    def test_add_path(self):
        inv = inventory.Inventory(root_id=b"tree_root")
        ie = inv.add_path("hello", "file", b"hello-id")
        self.assertEqual(b"hello-id", ie.file_id)
        self.assertEqual("file", ie.kind)

    def test_copy(self):
        """Make sure copy() works and creates a deep copy."""
        inv = inventory.Inventory(root_id=b"some-tree-root")
        ie = inv.add_path("hello", "file", b"hello-id")
        inv2 = inv.copy()
        inv.root.file_id = b"some-new-root"
        ie.name = "file2"
        self.assertEqual(b"some-tree-root", inv2.root.file_id)
        self.assertEqual("hello", inv2.get_entry(b"hello-id").name)

    def test_copy_empty(self):
        """Make sure an empty inventory can be copied."""
        inv = inventory.Inventory(root_id=None)
        inv2 = inv.copy()
        self.assertIs(None, inv2.root)

    def test_copy_copies_root_revision(self):
        """Make sure the revision of the root gets copied."""
        inv = inventory.Inventory(root_id=b"someroot")
        inv.root.revision = b"therev"
        inv2 = inv.copy()
        self.assertEqual(b"someroot", inv2.root.file_id)
        self.assertEqual(b"therev", inv2.root.revision)

    def test_create_tree_reference(self):
        inv = inventory.Inventory(b"tree-root-123")
        inv.add(
            TreeReference(
                b"nested-id",
                "nested",
                parent_id=b"tree-root-123",
                revision=b"rev",
                reference_revision=b"rev2",
            )
        )

    def test_error_encoding(self):
        inv = inventory.Inventory(b"tree-root")
        inv.add(InventoryFile(b"a-id", "\u1234", b"tree-root"))
        e = self.assertRaises(
            errors.InconsistentDelta,
            inv.add,
            InventoryFile(b"b-id", "\u1234", b"tree-root"),
        )
        self.assertContainsRe(str(e), "\\u1234")

    def test_add_recursive(self):
        parent = InventoryDirectory(b"src-id", "src", b"tree-root")
        child = InventoryFile(b"hello-id", "hello.c", b"src-id")
        parent.children[child.file_id] = child
        inv = inventory.Inventory(b"tree-root")
        inv.add(parent)
        self.assertEqual("src/hello.c", inv.id2path(b"hello-id"))


class TestDeltaApplication(TestCaseWithTransport):
    scenarios = delta_application_scenarios()

    def get_empty_inventory(self, reference_inv=None):
        """Get an empty inventory.

        Note that tests should not depend on the revision of the root for
        setting up test conditions, as it has to be flexible to accomodate non
        rich root repositories.

        :param reference_inv: If not None, get the revision for the root from
            this inventory. This is useful for dealing with older repositories
            that routinely discarded the root entry data. If None, the root's
            revision is set to 'basis'.
        """
        inv = inventory.Inventory()
        if reference_inv is not None:
            inv.root.revision = reference_inv.root.revision
        else:
            inv.root.revision = b"basis"
        return inv

    def make_file_ie(self, file_id=b"file-id", name="name", parent_id=None):
        ie_file = inventory.InventoryFile(file_id, name, parent_id)
        ie_file.revision = b"result"
        ie_file.text_size = 0
        ie_file.text_sha1 = b""
        return ie_file

    def test_empty_delta(self):
        inv = self.get_empty_inventory()
        delta = []
        inv = self.apply_delta(self, inv, delta)
        inv2 = self.get_empty_inventory(inv)
        self.assertEqual([], inv2._make_delta(inv))

    def test_None_file_id(self):
        inv = self.get_empty_inventory()
        dir1 = inventory.InventoryDirectory(b"dirid", "dir1", inv.root.file_id)
        dir1.file_id = None
        dir1.revision = b"result"
        delta = [(None, "dir1", None, dir1)]
        self.assertRaises(errors.InconsistentDelta, self.apply_delta, self, inv, delta)

    def test_unicode_file_id(self):
        inv = self.get_empty_inventory()
        dir1 = inventory.InventoryDirectory(b"dirid", "dir1", inv.root.file_id)
        dir1.file_id = "dirid"
        dir1.revision = b"result"
        delta = [(None, "dir1", dir1.file_id, dir1)]
        self.assertRaises(errors.InconsistentDelta, self.apply_delta, self, inv, delta)

    def test_repeated_file_id(self):
        inv = self.get_empty_inventory()
        file1 = inventory.InventoryFile(b"id", "path1", inv.root.file_id)
        file1.revision = b"result"
        file1.text_size = 0
        file1.text_sha1 = b""
        file2 = file1.copy()
        file2.name = "path2"
        delta = [(None, "path1", b"id", file1), (None, "path2", b"id", file2)]
        self.assertRaises(errors.InconsistentDelta, self.apply_delta, self, inv, delta)

    def test_repeated_new_path(self):
        inv = self.get_empty_inventory()
        file1 = inventory.InventoryFile(b"id1", "path", inv.root.file_id)
        file1.revision = b"result"
        file1.text_size = 0
        file1.text_sha1 = b""
        file2 = file1.copy()
        file2.file_id = b"id2"
        delta = [(None, "path", b"id1", file1), (None, "path", b"id2", file2)]
        self.assertRaises(errors.InconsistentDelta, self.apply_delta, self, inv, delta)

    def test_repeated_old_path(self):
        inv = self.get_empty_inventory()
        file1 = inventory.InventoryFile(b"id1", "path", inv.root.file_id)
        file1.revision = b"result"
        file1.text_size = 0
        file1.text_sha1 = b""
        # We can't *create* a source inventory with the same path, but
        # a badly generated partial delta might claim the same source twice.
        # This would be buggy in two ways: the path is repeated in the delta,
        # And the path for one of the file ids doesn't match the source
        # location. Alternatively, we could have a repeated fileid, but that
        # is separately checked for.
        file2 = inventory.InventoryFile(b"id2", "path2", inv.root.file_id)
        file2.revision = b"result"
        file2.text_size = 0
        file2.text_sha1 = b""
        inv.add(file1)
        inv.add(file2)
        delta = [("path", None, b"id1", None), ("path", None, b"id2", None)]
        self.assertRaises(errors.InconsistentDelta, self.apply_delta, self, inv, delta)

    def test_mismatched_id_entry_id(self):
        inv = self.get_empty_inventory()
        file1 = inventory.InventoryFile(b"id1", "path", inv.root.file_id)
        file1.revision = b"result"
        file1.text_size = 0
        file1.text_sha1 = b""
        delta = [(None, "path", b"id", file1)]
        self.assertRaises(errors.InconsistentDelta, self.apply_delta, self, inv, delta)

    def test_mismatched_new_path_entry_None(self):
        inv = self.get_empty_inventory()
        delta = [(None, "path", b"id", None)]
        self.assertRaises(errors.InconsistentDelta, self.apply_delta, self, inv, delta)

    def test_mismatched_new_path_None_entry(self):
        inv = self.get_empty_inventory()
        file1 = inventory.InventoryFile(b"id1", "path", inv.root.file_id)
        file1.revision = b"result"
        file1.text_size = 0
        file1.text_sha1 = b""
        delta = [("path", None, b"id1", file1)]
        self.assertRaises(errors.InconsistentDelta, self.apply_delta, self, inv, delta)

    def test_parent_is_not_directory(self):
        inv = self.get_empty_inventory()
        file1 = inventory.InventoryFile(b"id1", "path", inv.root.file_id)
        file1.revision = b"result"
        file1.text_size = 0
        file1.text_sha1 = b""
        file2 = inventory.InventoryFile(b"id2", "path2", b"id1")
        file2.revision = b"result"
        file2.text_size = 0
        file2.text_sha1 = b""
        inv.add(file1)
        delta = [(None, "path/path2", b"id2", file2)]
        self.assertRaises(errors.InconsistentDelta, self.apply_delta, self, inv, delta)

    def test_parent_is_missing(self):
        inv = self.get_empty_inventory()
        file2 = inventory.InventoryFile(b"id2", "path2", b"missingparent")
        file2.revision = b"result"
        file2.text_size = 0
        file2.text_sha1 = b""
        delta = [(None, "path/path2", b"id2", file2)]
        self.assertRaises(errors.InconsistentDelta, self.apply_delta, self, inv, delta)

    def test_new_parent_path_has_wrong_id(self):
        inv = self.get_empty_inventory()
        parent1 = inventory.InventoryDirectory(b"p-1", "dir", inv.root.file_id)
        parent1.revision = b"result"
        parent2 = inventory.InventoryDirectory(b"p-2", "dir2", inv.root.file_id)
        parent2.revision = b"result"
        file1 = inventory.InventoryFile(b"id", "path", b"p-2")
        file1.revision = b"result"
        file1.text_size = 0
        file1.text_sha1 = b""
        inv.add(parent1)
        inv.add(parent2)
        # This delta claims that file1 is at dir/path, but actually its at
        # dir2/path if you follow the inventory parent structure.
        delta = [(None, "dir/path", b"id", file1)]
        self.assertRaises(errors.InconsistentDelta, self.apply_delta, self, inv, delta)

    def test_old_parent_path_is_wrong(self):
        inv = self.get_empty_inventory()
        parent1 = inventory.InventoryDirectory(b"p-1", "dir", inv.root.file_id)
        parent1.revision = b"result"
        parent2 = inventory.InventoryDirectory(b"p-2", "dir2", inv.root.file_id)
        parent2.revision = b"result"
        file1 = inventory.InventoryFile(b"id", "path", b"p-2")
        file1.revision = b"result"
        file1.text_size = 0
        file1.text_sha1 = b""
        inv.add(parent1)
        inv.add(parent2)
        inv.add(file1)
        # This delta claims that file1 was at dir/path, but actually it was at
        # dir2/path if you follow the inventory parent structure.
        delta = [("dir/path", None, b"id", None)]
        self.assertRaises(errors.InconsistentDelta, self.apply_delta, self, inv, delta)

    def test_old_parent_path_is_for_other_id(self):
        inv = self.get_empty_inventory()
        parent1 = inventory.InventoryDirectory(b"p-1", "dir", inv.root.file_id)
        parent1.revision = b"result"
        parent2 = inventory.InventoryDirectory(b"p-2", "dir2", inv.root.file_id)
        parent2.revision = b"result"
        file1 = inventory.InventoryFile(b"id", "path", b"p-2")
        file1.revision = b"result"
        file1.text_size = 0
        file1.text_sha1 = b""
        file2 = inventory.InventoryFile(b"id2", "path", b"p-1")
        file2.revision = b"result"
        file2.text_size = 0
        file2.text_sha1 = b""
        inv.add(parent1)
        inv.add(parent2)
        inv.add(file1)
        inv.add(file2)
        # This delta claims that file1 was at dir/path, but actually it was at
        # dir2/path if you follow the inventory parent structure. At dir/path
        # is another entry we should not delete.
        delta = [("dir/path", None, b"id", None)]
        self.assertRaises(errors.InconsistentDelta, self.apply_delta, self, inv, delta)

    def test_add_existing_id_new_path(self):
        inv = self.get_empty_inventory()
        parent1 = inventory.InventoryDirectory(b"p-1", "dir1", inv.root.file_id)
        parent1.revision = b"result"
        parent2 = inventory.InventoryDirectory(b"p-1", "dir2", inv.root.file_id)
        parent2.revision = b"result"
        inv.add(parent1)
        delta = [(None, "dir2", b"p-1", parent2)]
        self.assertRaises(errors.InconsistentDelta, self.apply_delta, self, inv, delta)

    def test_add_new_id_existing_path(self):
        inv = self.get_empty_inventory()
        parent1 = inventory.InventoryDirectory(b"p-1", "dir1", inv.root.file_id)
        parent1.revision = b"result"
        parent2 = inventory.InventoryDirectory(b"p-2", "dir1", inv.root.file_id)
        parent2.revision = b"result"
        inv.add(parent1)
        delta = [(None, "dir1", b"p-2", parent2)]
        self.assertRaises(errors.InconsistentDelta, self.apply_delta, self, inv, delta)

    def test_remove_dir_leaving_dangling_child(self):
        inv = self.get_empty_inventory()
        dir1 = inventory.InventoryDirectory(b"p-1", "dir1", inv.root.file_id)
        dir1.revision = b"result"
        dir2 = inventory.InventoryDirectory(b"p-2", "child1", b"p-1")
        dir2.revision = b"result"
        dir3 = inventory.InventoryDirectory(b"p-3", "child2", b"p-1")
        dir3.revision = b"result"
        inv.add(dir1)
        inv.add(dir2)
        inv.add(dir3)
        delta = [("dir1", None, b"p-1", None), ("dir1/child2", None, b"p-3", None)]
        self.assertRaises(errors.InconsistentDelta, self.apply_delta, self, inv, delta)

    def test_add_file(self):
        inv = self.get_empty_inventory()
        file1 = inventory.InventoryFile(b"file-id", "path", inv.root.file_id)
        file1.revision = b"result"
        file1.text_size = 0
        file1.text_sha1 = b""
        delta = [(None, "path", b"file-id", file1)]
        res_inv = self.apply_delta(self, inv, delta, invalid_delta=False)
        self.assertEqual(b"file-id", res_inv.get_entry(b"file-id").file_id)

    def test_remove_file(self):
        inv = self.get_empty_inventory()
        file1 = inventory.InventoryFile(b"file-id", "path", inv.root.file_id)
        file1.revision = b"result"
        file1.text_size = 0
        file1.text_sha1 = b""
        inv.add(file1)
        delta = [("path", None, b"file-id", None)]
        res_inv = self.apply_delta(self, inv, delta, invalid_delta=False)
        self.assertEqual(None, res_inv.path2id("path"))
        self.assertRaises(errors.NoSuchId, res_inv.id2path, b"file-id")

    def test_rename_file(self):
        inv = self.get_empty_inventory()
        file1 = self.make_file_ie(name="path", parent_id=inv.root.file_id)
        inv.add(file1)
        file2 = self.make_file_ie(name="path2", parent_id=inv.root.file_id)
        delta = [("path", "path2", b"file-id", file2)]
        res_inv = self.apply_delta(self, inv, delta, invalid_delta=False)
        self.assertEqual(None, res_inv.path2id("path"))
        self.assertEqual(b"file-id", res_inv.path2id("path2"))

    def test_replaced_at_new_path(self):
        inv = self.get_empty_inventory()
        file1 = self.make_file_ie(file_id=b"id1", parent_id=inv.root.file_id)
        inv.add(file1)
        file2 = self.make_file_ie(file_id=b"id2", parent_id=inv.root.file_id)
        delta = [("name", None, b"id1", None), (None, "name", b"id2", file2)]
        res_inv = self.apply_delta(self, inv, delta, invalid_delta=False)
        self.assertEqual(b"id2", res_inv.path2id("name"))

    def test_rename_dir(self):
        inv = self.get_empty_inventory()
        dir1 = inventory.InventoryDirectory(b"dir-id", "dir1", inv.root.file_id)
        dir1.revision = b"basis"
        file1 = self.make_file_ie(parent_id=b"dir-id")
        inv.add(dir1)
        inv.add(file1)
        dir2 = inventory.InventoryDirectory(b"dir-id", "dir2", inv.root.file_id)
        dir2.revision = b"result"
        delta = [("dir1", "dir2", b"dir-id", dir2)]
        res_inv = self.apply_delta(self, inv, delta, invalid_delta=False)
        # The file should be accessible under the new path
        self.assertEqual(b"file-id", res_inv.path2id("dir2/name"))

    def test_renamed_dir_with_renamed_child(self):
        inv = self.get_empty_inventory()
        dir1 = inventory.InventoryDirectory(b"dir-id", "dir1", inv.root.file_id)
        dir1.revision = b"basis"
        file1 = self.make_file_ie(b"file-id-1", "name1", parent_id=b"dir-id")
        file2 = self.make_file_ie(b"file-id-2", "name2", parent_id=b"dir-id")
        inv.add(dir1)
        inv.add(file1)
        inv.add(file2)
        dir2 = inventory.InventoryDirectory(b"dir-id", "dir2", inv.root.file_id)
        dir2.revision = b"result"
        file2b = self.make_file_ie(b"file-id-2", "name2", inv.root.file_id)
        delta = [
            ("dir1", "dir2", b"dir-id", dir2),
            ("dir1/name2", "name2", b"file-id-2", file2b),
        ]
        res_inv = self.apply_delta(self, inv, delta, invalid_delta=False)
        # The file should be accessible under the new path
        self.assertEqual(b"file-id-1", res_inv.path2id("dir2/name1"))
        self.assertEqual(None, res_inv.path2id("dir2/name2"))
        self.assertEqual(b"file-id-2", res_inv.path2id("name2"))

    def test_is_root(self):
        """Ensure our root-checking code is accurate."""
        inv = inventory.Inventory(b"TREE_ROOT")
        self.assertTrue(inv.is_root(b"TREE_ROOT"))
        self.assertFalse(inv.is_root(b"booga"))
        inv.root.file_id = b"booga"
        self.assertFalse(inv.is_root(b"TREE_ROOT"))
        self.assertTrue(inv.is_root(b"booga"))
        # works properly even if no root is set
        inv.root = None
        self.assertFalse(inv.is_root(b"TREE_ROOT"))
        self.assertFalse(inv.is_root(b"booga"))

    def test_entries_for_empty_inventory(self):
        """Test that entries() will not fail for an empty inventory."""
        inv = Inventory(root_id=None)
        self.assertEqual([], inv.entries())


class TestInventoryEntry(TestCase):
    def test_file_invalid_entry_name(self):
        self.assertRaises(
            InvalidEntryName, inventory.InventoryFile, b"123", "a/hello.c", ROOT_ID
        )

    def test_file_backslash(self):
        file = inventory.InventoryFile(b"123", "h\\ello.c", ROOT_ID)
        self.assertEqual(file.name, "h\\ello.c")

    def test_file_kind_character(self):
        file = inventory.InventoryFile(b"123", "hello.c", ROOT_ID)
        self.assertEqual(file.kind_character(), "")

    def test_dir_kind_character(self):
        dir = inventory.InventoryDirectory(b"123", "hello.c", ROOT_ID)
        self.assertEqual(dir.kind_character(), "/")

    def test_link_kind_character(self):
        dir = inventory.InventoryLink(b"123", "hello.c", ROOT_ID)
        self.assertEqual(dir.kind_character(), "")

    def test_tree_ref_kind_character(self):
        dir = TreeReference(b"123", "hello.c", ROOT_ID)
        self.assertEqual(dir.kind_character(), "+")

    def test_dir_detect_changes(self):
        left = inventory.InventoryDirectory(b"123", "hello.c", ROOT_ID)
        right = inventory.InventoryDirectory(b"123", "hello.c", ROOT_ID)
        self.assertEqual((False, False), left.detect_changes(right))
        self.assertEqual((False, False), right.detect_changes(left))

    def test_file_detect_changes(self):
        left = inventory.InventoryFile(b"123", "hello.c", ROOT_ID)
        left.text_sha1 = 123
        right = inventory.InventoryFile(b"123", "hello.c", ROOT_ID)
        right.text_sha1 = 123
        self.assertEqual((False, False), left.detect_changes(right))
        self.assertEqual((False, False), right.detect_changes(left))
        left.executable = True
        self.assertEqual((False, True), left.detect_changes(right))
        self.assertEqual((False, True), right.detect_changes(left))
        right.text_sha1 = 321
        self.assertEqual((True, True), left.detect_changes(right))
        self.assertEqual((True, True), right.detect_changes(left))

    def test_symlink_detect_changes(self):
        left = inventory.InventoryLink(b"123", "hello.c", ROOT_ID)
        left.symlink_target = "foo"
        right = inventory.InventoryLink(b"123", "hello.c", ROOT_ID)
        right.symlink_target = "foo"
        self.assertEqual((False, False), left.detect_changes(right))
        self.assertEqual((False, False), right.detect_changes(left))
        left.symlink_target = "different"
        self.assertEqual((True, False), left.detect_changes(right))
        self.assertEqual((True, False), right.detect_changes(left))

    def test_file_has_text(self):
        file = inventory.InventoryFile(b"123", "hello.c", ROOT_ID)
        self.assertTrue(file.has_text())

    def test_directory_has_text(self):
        dir = inventory.InventoryDirectory(b"123", "hello.c", ROOT_ID)
        self.assertFalse(dir.has_text())

    def test_link_has_text(self):
        link = inventory.InventoryLink(b"123", "hello.c", ROOT_ID)
        self.assertFalse(link.has_text())

    def test_make_entry(self):
        self.assertIsInstance(
            inventory.make_entry("file", "name", ROOT_ID), inventory.InventoryFile
        )
        self.assertIsInstance(
            inventory.make_entry("symlink", "name", ROOT_ID), inventory.InventoryLink
        )
        self.assertIsInstance(
            inventory.make_entry("directory", "name", ROOT_ID),
            inventory.InventoryDirectory,
        )

    def test_make_entry_non_normalized(self):
        orig_normalized_filename = osutils.normalized_filename

        try:
            osutils.normalized_filename = osutils._accessible_normalized_filename
            entry = inventory.make_entry("file", "a\u030a", ROOT_ID)
            self.assertEqual("\xe5", entry.name)
            self.assertIsInstance(entry, inventory.InventoryFile)

            osutils.normalized_filename = osutils._inaccessible_normalized_filename
            self.assertRaises(
                errors.InvalidNormalization,
                inventory.make_entry,
                "file",
                "a\u030a",
                ROOT_ID,
            )
        finally:
            osutils.normalized_filename = orig_normalized_filename


class TestDescribeChanges(TestCase):
    def test_describe_change(self):
        # we need to test the following change combinations:
        # rename
        # reparent
        # modify
        # gone
        # added
        # renamed/reparented and modified
        # change kind (perhaps can't be done yet?)
        # also, merged in combination with all of these?
        old_a = InventoryFile(b"a-id", "a_file", ROOT_ID)
        old_a.text_sha1 = b"123132"
        old_a.text_size = 0
        new_a = InventoryFile(b"a-id", "a_file", ROOT_ID)
        new_a.text_sha1 = b"123132"
        new_a.text_size = 0

        self.assertChangeDescription("unchanged", old_a, new_a)

        new_a.text_size = 10
        new_a.text_sha1 = b"abcabc"
        self.assertChangeDescription("modified", old_a, new_a)

        self.assertChangeDescription("added", None, new_a)
        self.assertChangeDescription("removed", old_a, None)
        # perhaps a bit questionable but seems like the most reasonable thing...
        self.assertChangeDescription("unchanged", None, None)

        # in this case it's both renamed and modified; show a rename and
        # modification:
        new_a.name = "newfilename"
        self.assertChangeDescription("modified and renamed", old_a, new_a)

        # reparenting is 'renaming'
        new_a.name = old_a.name
        new_a.parent_id = b"somedir-id"
        self.assertChangeDescription("modified and renamed", old_a, new_a)

        # reset the content values so its not modified
        new_a.text_size = old_a.text_size
        new_a.text_sha1 = old_a.text_sha1
        new_a.name = old_a.name

        new_a.name = "newfilename"
        self.assertChangeDescription("renamed", old_a, new_a)

        # reparenting is 'renaming'
        new_a.name = old_a.name
        new_a.parent_id = b"somedir-id"
        self.assertChangeDescription("renamed", old_a, new_a)

    def assertChangeDescription(self, expected_change, old_ie, new_ie):
        change = InventoryEntry.describe_change(old_ie, new_ie)
        self.assertEqual(expected_change, change)


class TestCHKInventory(tests.TestCaseWithMemoryTransport):
    def get_chk_bytes(self):
        factory = groupcompress.make_pack_factory(True, True, 1)
        trans = self.get_transport("")
        return factory(trans)

    def read_bytes(self, chk_bytes, key):
        stream = chk_bytes.get_record_stream([key], "unordered", True)
        return next(stream).get_bytes_as("fulltext")

    def test_deserialise_gives_CHKInventory(self):
        inv = Inventory()
        inv.revision_id = b"revid"
        inv.root.revision = b"rootrev"
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv)
        lines = chk_inv.to_lines()
        new_inv = CHKInventory.deserialise(chk_bytes, lines, (b"revid",))
        self.assertEqual(b"revid", new_inv.revision_id)
        self.assertEqual("directory", new_inv.root.kind)
        self.assertEqual(inv.root.file_id, new_inv.root.file_id)
        self.assertEqual(inv.root.parent_id, new_inv.root.parent_id)
        self.assertEqual(inv.root.name, new_inv.root.name)
        self.assertEqual(b"rootrev", new_inv.root.revision)
        self.assertEqual(b"plain", new_inv._search_key_name)

    def test_deserialise_wrong_revid(self):
        inv = Inventory()
        inv.revision_id = b"revid"
        inv.root.revision = b"rootrev"
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv)
        lines = chk_inv.to_lines()
        self.assertRaises(
            ValueError, CHKInventory.deserialise, chk_bytes, lines, (b"revid2",)
        )

    def test_captures_rev_root_byid(self):
        inv = Inventory()
        inv.revision_id = b"foo"
        inv.root.revision = b"bar"
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv)
        lines = chk_inv.to_lines()
        self.assertEqual(
            [
                b"chkinventory:\n",
                b"revision_id: foo\n",
                b"root_id: TREE_ROOT\n",
                b"parent_id_basename_to_file_id: sha1:eb23f0ad4b07f48e88c76d4c94292be57fb2785f\n",
                b"id_to_entry: sha1:debfe920f1f10e7929260f0534ac9a24d7aabbb4\n",
            ],
            lines,
        )
        chk_inv = CHKInventory.deserialise(chk_bytes, lines, (b"foo",))
        self.assertEqual(b"plain", chk_inv._search_key_name)

    def test_captures_parent_id_basename_index(self):
        inv = Inventory()
        inv.revision_id = b"foo"
        inv.root.revision = b"bar"
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv)
        lines = chk_inv.to_lines()
        self.assertEqual(
            [
                b"chkinventory:\n",
                b"revision_id: foo\n",
                b"root_id: TREE_ROOT\n",
                b"parent_id_basename_to_file_id: sha1:eb23f0ad4b07f48e88c76d4c94292be57fb2785f\n",
                b"id_to_entry: sha1:debfe920f1f10e7929260f0534ac9a24d7aabbb4\n",
            ],
            lines,
        )
        chk_inv = CHKInventory.deserialise(chk_bytes, lines, (b"foo",))
        self.assertEqual(b"plain", chk_inv._search_key_name)

    def test_captures_search_key_name(self):
        inv = Inventory()
        inv.revision_id = b"foo"
        inv.root.revision = b"bar"
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(
            chk_bytes, inv, search_key_name=b"hash-16-way"
        )
        lines = chk_inv.to_lines()
        self.assertEqual(
            [
                b"chkinventory:\n",
                b"search_key_name: hash-16-way\n",
                b"root_id: TREE_ROOT\n",
                b"parent_id_basename_to_file_id: sha1:eb23f0ad4b07f48e88c76d4c94292be57fb2785f\n",
                b"revision_id: foo\n",
                b"id_to_entry: sha1:debfe920f1f10e7929260f0534ac9a24d7aabbb4\n",
            ],
            lines,
        )
        chk_inv = CHKInventory.deserialise(chk_bytes, lines, (b"foo",))
        self.assertEqual(b"hash-16-way", chk_inv._search_key_name)

    def test_directory_children_on_demand(self):
        inv = Inventory()
        inv.revision_id = b"revid"
        inv.root.revision = b"rootrev"
        inv.add(InventoryFile(b"fileid", "file", inv.root.file_id))
        inv.get_entry(b"fileid").revision = b"filerev"
        inv.get_entry(b"fileid").executable = True
        inv.get_entry(b"fileid").text_sha1 = b"ffff"
        inv.get_entry(b"fileid").text_size = 1
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv)
        lines = chk_inv.to_lines()
        new_inv = CHKInventory.deserialise(chk_bytes, lines, (b"revid",))
        root_entry = new_inv.get_entry(inv.root.file_id)
        self.assertEqual(None, root_entry._children)
        self.assertEqual({"file"}, set(root_entry.children))
        file_direct = new_inv.get_entry(b"fileid")
        file_found = root_entry.children["file"]
        self.assertEqual(file_direct.kind, file_found.kind)
        self.assertEqual(file_direct.file_id, file_found.file_id)
        self.assertEqual(file_direct.parent_id, file_found.parent_id)
        self.assertEqual(file_direct.name, file_found.name)
        self.assertEqual(file_direct.revision, file_found.revision)
        self.assertEqual(file_direct.text_sha1, file_found.text_sha1)
        self.assertEqual(file_direct.text_size, file_found.text_size)
        self.assertEqual(file_direct.executable, file_found.executable)

    def test_from_inventory_maximum_size(self):
        # from_inventory supports the maximum_size parameter.
        inv = Inventory()
        inv.revision_id = b"revid"
        inv.root.revision = b"rootrev"
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv, 120)
        chk_inv.id_to_entry._ensure_root()
        self.assertEqual(120, chk_inv.id_to_entry._root_node.maximum_size)
        self.assertEqual(1, chk_inv.id_to_entry._root_node._key_width)
        p_id_basename = chk_inv.parent_id_basename_to_file_id
        p_id_basename._ensure_root()
        self.assertEqual(120, p_id_basename._root_node.maximum_size)
        self.assertEqual(2, p_id_basename._root_node._key_width)

    def test_iter_all_ids(self):
        inv = Inventory()
        inv.revision_id = b"revid"
        inv.root.revision = b"rootrev"
        inv.add(InventoryFile(b"fileid", "file", inv.root.file_id))
        inv.get_entry(b"fileid").revision = b"filerev"
        inv.get_entry(b"fileid").executable = True
        inv.get_entry(b"fileid").text_sha1 = b"ffff"
        inv.get_entry(b"fileid").text_size = 1
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv)
        lines = chk_inv.to_lines()
        new_inv = CHKInventory.deserialise(chk_bytes, lines, (b"revid",))
        fileids = sorted(new_inv.iter_all_ids())
        self.assertEqual([inv.root.file_id, b"fileid"], fileids)

    def test__len__(self):
        inv = Inventory()
        inv.revision_id = b"revid"
        inv.root.revision = b"rootrev"
        inv.add(InventoryFile(b"fileid", "file", inv.root.file_id))
        inv.get_entry(b"fileid").revision = b"filerev"
        inv.get_entry(b"fileid").executable = True
        inv.get_entry(b"fileid").text_sha1 = b"ffff"
        inv.get_entry(b"fileid").text_size = 1
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv)
        self.assertEqual(2, len(chk_inv))

    def test_get_entry(self):
        inv = Inventory()
        inv.revision_id = b"revid"
        inv.root.revision = b"rootrev"
        inv.add(InventoryFile(b"fileid", "file", inv.root.file_id))
        inv.get_entry(b"fileid").revision = b"filerev"
        inv.get_entry(b"fileid").executable = True
        inv.get_entry(b"fileid").text_sha1 = b"ffff"
        inv.get_entry(b"fileid").text_size = 1
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv)
        lines = chk_inv.to_lines()
        new_inv = CHKInventory.deserialise(chk_bytes, lines, (b"revid",))
        root_entry = new_inv.get_entry(inv.root.file_id)
        file_entry = new_inv.get_entry(b"fileid")
        self.assertEqual("directory", root_entry.kind)
        self.assertEqual(inv.root.file_id, root_entry.file_id)
        self.assertEqual(inv.root.parent_id, root_entry.parent_id)
        self.assertEqual(inv.root.name, root_entry.name)
        self.assertEqual(b"rootrev", root_entry.revision)
        self.assertEqual("file", file_entry.kind)
        self.assertEqual(b"fileid", file_entry.file_id)
        self.assertEqual(inv.root.file_id, file_entry.parent_id)
        self.assertEqual("file", file_entry.name)
        self.assertEqual(b"filerev", file_entry.revision)
        self.assertEqual(b"ffff", file_entry.text_sha1)
        self.assertEqual(1, file_entry.text_size)
        self.assertEqual(True, file_entry.executable)
        self.assertRaises(errors.NoSuchId, new_inv.get_entry, "missing")

    def test_has_id_true(self):
        inv = Inventory()
        inv.revision_id = b"revid"
        inv.root.revision = b"rootrev"
        inv.add(InventoryFile(b"fileid", "file", inv.root.file_id))
        inv.get_entry(b"fileid").revision = b"filerev"
        inv.get_entry(b"fileid").executable = True
        inv.get_entry(b"fileid").text_sha1 = b"ffff"
        inv.get_entry(b"fileid").text_size = 1
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv)
        self.assertTrue(chk_inv.has_id(b"fileid"))
        self.assertTrue(chk_inv.has_id(inv.root.file_id))

    def test_has_id_not(self):
        inv = Inventory()
        inv.revision_id = b"revid"
        inv.root.revision = b"rootrev"
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv)
        self.assertFalse(chk_inv.has_id(b"fileid"))

    def test_id2path(self):
        inv = Inventory()
        inv.revision_id = b"revid"
        inv.root.revision = b"rootrev"
        direntry = InventoryDirectory(b"dirid", "dir", inv.root.file_id)
        fileentry = InventoryFile(b"fileid", "file", b"dirid")
        inv.add(direntry)
        inv.add(fileentry)
        inv.get_entry(b"fileid").revision = b"filerev"
        inv.get_entry(b"fileid").executable = True
        inv.get_entry(b"fileid").text_sha1 = b"ffff"
        inv.get_entry(b"fileid").text_size = 1
        inv.get_entry(b"dirid").revision = b"filerev"
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv)
        lines = chk_inv.to_lines()
        new_inv = CHKInventory.deserialise(chk_bytes, lines, (b"revid",))
        self.assertEqual("", new_inv.id2path(inv.root.file_id))
        self.assertEqual("dir", new_inv.id2path(b"dirid"))
        self.assertEqual("dir/file", new_inv.id2path(b"fileid"))

    def test_path2id(self):
        inv = Inventory()
        inv.revision_id = b"revid"
        inv.root.revision = b"rootrev"
        direntry = InventoryDirectory(b"dirid", "dir", inv.root.file_id)
        fileentry = InventoryFile(b"fileid", "file", b"dirid")
        inv.add(direntry)
        inv.add(fileentry)
        inv.get_entry(b"fileid").revision = b"filerev"
        inv.get_entry(b"fileid").executable = True
        inv.get_entry(b"fileid").text_sha1 = b"ffff"
        inv.get_entry(b"fileid").text_size = 1
        inv.get_entry(b"dirid").revision = b"filerev"
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv)
        lines = chk_inv.to_lines()
        new_inv = CHKInventory.deserialise(chk_bytes, lines, (b"revid",))
        self.assertEqual(inv.root.file_id, new_inv.path2id(""))
        self.assertEqual(b"dirid", new_inv.path2id("dir"))
        self.assertEqual(b"fileid", new_inv.path2id("dir/file"))

    def test_create_by_apply_delta_sets_root(self):
        inv = Inventory()
        inv.root.revision = b"myrootrev"
        inv.revision_id = b"revid"
        chk_bytes = self.get_chk_bytes()
        base_inv = CHKInventory.from_inventory(chk_bytes, inv)
        inv.add_path("", "directory", b"myrootid", None)
        inv.revision_id = b"expectedid"
        inv.root.revision = b"myrootrev"
        reference_inv = CHKInventory.from_inventory(chk_bytes, inv)
        delta = [
            ("", None, base_inv.root.file_id, None),
            (None, "", b"myrootid", inv.root),
        ]
        new_inv = base_inv.create_by_apply_delta(delta, b"expectedid")
        self.assertEqual(reference_inv.root, new_inv.root)

    def test_create_by_apply_delta_empty_add_child(self):
        inv = Inventory()
        inv.revision_id = b"revid"
        inv.root.revision = b"rootrev"
        chk_bytes = self.get_chk_bytes()
        base_inv = CHKInventory.from_inventory(chk_bytes, inv)
        a_entry = InventoryFile(b"A-id", "A", inv.root.file_id)
        a_entry.revision = b"filerev"
        a_entry.executable = True
        a_entry.text_sha1 = b"ffff"
        a_entry.text_size = 1
        inv.add(a_entry)
        inv.revision_id = b"expectedid"
        reference_inv = CHKInventory.from_inventory(chk_bytes, inv)
        delta = [(None, "A", b"A-id", a_entry)]
        new_inv = base_inv.create_by_apply_delta(delta, b"expectedid")
        # new_inv should be the same as reference_inv.
        self.assertEqual(reference_inv.revision_id, new_inv.revision_id)
        self.assertEqual(reference_inv.root_id, new_inv.root_id)
        reference_inv.id_to_entry._ensure_root()
        new_inv.id_to_entry._ensure_root()
        self.assertEqual(
            reference_inv.id_to_entry._root_node._key,
            new_inv.id_to_entry._root_node._key,
        )

    def test_create_by_apply_delta_empty_add_child_updates_parent_id(self):
        inv = Inventory()
        inv.revision_id = b"revid"
        inv.root.revision = b"rootrev"
        chk_bytes = self.get_chk_bytes()
        base_inv = CHKInventory.from_inventory(chk_bytes, inv)
        a_entry = InventoryFile(b"A-id", "A", inv.root.file_id)
        a_entry.revision = b"filerev"
        a_entry.executable = True
        a_entry.text_sha1 = b"ffff"
        a_entry.text_size = 1
        inv.add(a_entry)
        inv.revision_id = b"expectedid"
        reference_inv = CHKInventory.from_inventory(chk_bytes, inv)
        delta = [(None, "A", b"A-id", a_entry)]
        new_inv = base_inv.create_by_apply_delta(delta, b"expectedid")
        reference_inv.id_to_entry._ensure_root()
        reference_inv.parent_id_basename_to_file_id._ensure_root()
        new_inv.id_to_entry._ensure_root()
        new_inv.parent_id_basename_to_file_id._ensure_root()
        # new_inv should be the same as reference_inv.
        self.assertEqual(reference_inv.revision_id, new_inv.revision_id)
        self.assertEqual(reference_inv.root_id, new_inv.root_id)
        self.assertEqual(
            reference_inv.id_to_entry._root_node._key,
            new_inv.id_to_entry._root_node._key,
        )
        self.assertEqual(
            reference_inv.parent_id_basename_to_file_id._root_node._key,
            new_inv.parent_id_basename_to_file_id._root_node._key,
        )

    def test_iter_changes(self):
        # Low level bootstrapping smoke test; comprehensive generic tests via
        # InterTree are coming.
        inv = Inventory()
        inv.revision_id = b"revid"
        inv.root.revision = b"rootrev"
        inv.add(InventoryFile(b"fileid", "file", inv.root.file_id))
        inv.get_entry(b"fileid").revision = b"filerev"
        inv.get_entry(b"fileid").executable = True
        inv.get_entry(b"fileid").text_sha1 = b"ffff"
        inv.get_entry(b"fileid").text_size = 1
        inv2 = Inventory()
        inv2.revision_id = b"revid2"
        inv2.root.revision = b"rootrev"
        inv2.add(InventoryFile(b"fileid", "file", inv.root.file_id))
        inv2.get_entry(b"fileid").revision = b"filerev2"
        inv2.get_entry(b"fileid").executable = False
        inv2.get_entry(b"fileid").text_sha1 = b"bbbb"
        inv2.get_entry(b"fileid").text_size = 2
        # get fresh objects.
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv)
        lines = chk_inv.to_lines()
        inv_1 = CHKInventory.deserialise(chk_bytes, lines, (b"revid",))
        chk_inv2 = CHKInventory.from_inventory(chk_bytes, inv2)
        lines = chk_inv2.to_lines()
        inv_2 = CHKInventory.deserialise(chk_bytes, lines, (b"revid2",))
        self.assertEqual(
            [
                (
                    b"fileid",
                    ("file", "file"),
                    True,
                    (True, True),
                    (b"TREE_ROOT", b"TREE_ROOT"),
                    ("file", "file"),
                    ("file", "file"),
                    (False, True),
                )
            ],
            list(inv_1.iter_changes(inv_2)),
        )

    def test_parent_id_basename_to_file_id_index_enabled(self):
        inv = Inventory()
        inv.revision_id = b"revid"
        inv.root.revision = b"rootrev"
        inv.add(InventoryFile(b"fileid", "file", inv.root.file_id))
        inv.get_entry(b"fileid").revision = b"filerev"
        inv.get_entry(b"fileid").executable = True
        inv.get_entry(b"fileid").text_sha1 = b"ffff"
        inv.get_entry(b"fileid").text_size = 1
        # get fresh objects.
        chk_bytes = self.get_chk_bytes()
        tmp_inv = CHKInventory.from_inventory(chk_bytes, inv)
        lines = tmp_inv.to_lines()
        chk_inv = CHKInventory.deserialise(chk_bytes, lines, (b"revid",))
        self.assertIsInstance(chk_inv.parent_id_basename_to_file_id, chk_map.CHKMap)
        self.assertEqual(
            {(b"", b""): b"TREE_ROOT", (b"TREE_ROOT", b"file"): b"fileid"},
            dict(chk_inv.parent_id_basename_to_file_id.iteritems()),
        )

    def test_file_entry_to_bytes(self):
        inv = CHKInventory(None)
        ie = inventory.InventoryFile(b"file-id", "filename", b"parent-id")
        ie.executable = True
        ie.revision = b"file-rev-id"
        ie.text_sha1 = b"abcdefgh"
        ie.text_size = 100
        bytes = inv._entry_to_bytes(ie)
        self.assertEqual(
            b"file: file-id\nparent-id\nfilename\nfile-rev-id\nabcdefgh\n100\nY",
            bytes,
        )
        ie2 = inv._bytes_to_entry(bytes)
        self.assertEqual(ie, ie2)
        self.assertIsInstance(ie2.name, str)
        self.assertEqual(
            (b"filename", b"file-id", b"file-rev-id"), inv._bytes_to_utf8name_key(bytes)
        )

    def test_file2_entry_to_bytes(self):
        inv = CHKInventory(None)
        # \u30a9 == 'omega'
        ie = inventory.InventoryFile(b"file-id", "\u03a9name", b"parent-id")
        ie.executable = False
        ie.revision = b"file-rev-id"
        ie.text_sha1 = b"123456"
        ie.text_size = 25
        bytes = inv._entry_to_bytes(ie)
        self.assertEqual(
            b"file: file-id\nparent-id\n\xce\xa9name\nfile-rev-id\n123456\n25\nN",
            bytes,
        )
        ie2 = inv._bytes_to_entry(bytes)
        self.assertEqual(ie, ie2)
        self.assertIsInstance(ie2.name, str)
        self.assertEqual(
            (b"\xce\xa9name", b"file-id", b"file-rev-id"),
            inv._bytes_to_utf8name_key(bytes),
        )

    def test_dir_entry_to_bytes(self):
        inv = CHKInventory(None)
        ie = inventory.InventoryDirectory(b"dir-id", "dirname", b"parent-id")
        ie.revision = b"dir-rev-id"
        bytes = inv._entry_to_bytes(ie)
        self.assertEqual(b"dir: dir-id\nparent-id\ndirname\ndir-rev-id", bytes)
        ie2 = inv._bytes_to_entry(bytes)
        self.assertEqual(ie, ie2)
        self.assertIsInstance(ie2.name, str)
        self.assertEqual(
            (b"dirname", b"dir-id", b"dir-rev-id"), inv._bytes_to_utf8name_key(bytes)
        )

    def test_dir2_entry_to_bytes(self):
        inv = CHKInventory(None)
        ie = inventory.InventoryDirectory(b"dir-id", "dir\u03a9name", None)
        ie.revision = b"dir-rev-id"
        bytes = inv._entry_to_bytes(ie)
        self.assertEqual(b"dir: dir-id\n\ndir\xce\xa9name\ndir-rev-id", bytes)
        ie2 = inv._bytes_to_entry(bytes)
        self.assertEqual(ie, ie2)
        self.assertIsInstance(ie2.name, str)
        self.assertIs(ie2.parent_id, None)
        self.assertEqual(
            (b"dir\xce\xa9name", b"dir-id", b"dir-rev-id"),
            inv._bytes_to_utf8name_key(bytes),
        )

    def test_symlink_entry_to_bytes(self):
        inv = CHKInventory(None)
        ie = inventory.InventoryLink(b"link-id", "linkname", b"parent-id")
        ie.revision = b"link-rev-id"
        ie.symlink_target = "target/path"
        bytes = inv._entry_to_bytes(ie)
        self.assertEqual(
            b"symlink: link-id\nparent-id\nlinkname\nlink-rev-id\ntarget/path",
            bytes,
        )
        ie2 = inv._bytes_to_entry(bytes)
        self.assertEqual(ie, ie2)
        self.assertIsInstance(ie2.name, str)
        self.assertIsInstance(ie2.symlink_target, str)
        self.assertEqual(
            (b"linkname", b"link-id", b"link-rev-id"), inv._bytes_to_utf8name_key(bytes)
        )

    def test_symlink2_entry_to_bytes(self):
        inv = CHKInventory(None)
        ie = inventory.InventoryLink(b"link-id", "link\u03a9name", b"parent-id")
        ie.revision = b"link-rev-id"
        ie.symlink_target = "target/\u03a9path"
        bytes = inv._entry_to_bytes(ie)
        self.assertEqual(
            b"symlink: link-id\nparent-id\nlink\xce\xa9name\n"
            b"link-rev-id\ntarget/\xce\xa9path",
            bytes,
        )
        ie2 = inv._bytes_to_entry(bytes)
        self.assertEqual(ie, ie2)
        self.assertIsInstance(ie2.name, str)
        self.assertIsInstance(ie2.symlink_target, str)
        self.assertEqual(
            (b"link\xce\xa9name", b"link-id", b"link-rev-id"),
            inv._bytes_to_utf8name_key(bytes),
        )

    def test_tree_reference_entry_to_bytes(self):
        inv = CHKInventory(None)
        ie = inventory.TreeReference(b"tree-root-id", "tree\u03a9name", b"parent-id")
        ie.revision = b"tree-rev-id"
        ie.reference_revision = b"ref-rev-id"
        bytes = inv._entry_to_bytes(ie)
        self.assertEqual(
            b"tree: tree-root-id\nparent-id\ntree\xce\xa9name\ntree-rev-id\nref-rev-id",
            bytes,
        )
        ie2 = inv._bytes_to_entry(bytes)
        self.assertEqual(ie, ie2)
        self.assertIsInstance(ie2.name, str)
        self.assertEqual(
            (b"tree\xce\xa9name", b"tree-root-id", b"tree-rev-id"),
            inv._bytes_to_utf8name_key(bytes),
        )

    def make_basic_utf8_inventory(self):
        inv = Inventory()
        inv.revision_id = b"revid"
        inv.root.revision = b"rootrev"
        root_id = inv.root.file_id
        inv.add(InventoryFile(b"fileid", "f\xefle", root_id))
        inv.get_entry(b"fileid").revision = b"filerev"
        inv.get_entry(b"fileid").text_sha1 = b"ffff"
        inv.get_entry(b"fileid").text_size = 0
        inv.add(InventoryDirectory(b"dirid", "dir-\N{EURO SIGN}", root_id))
        inv.get_entry(b"dirid").revision = b"dirrev"
        inv.add(InventoryFile(b"childid", "ch\xefld", b"dirid"))
        inv.get_entry(b"childid").revision = b"filerev"
        inv.get_entry(b"childid").text_sha1 = b"ffff"
        inv.get_entry(b"childid").text_size = 0
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv)
        lines = chk_inv.to_lines()
        return CHKInventory.deserialise(chk_bytes, lines, (b"revid",))

    def test__preload_handles_utf8(self):
        new_inv = self.make_basic_utf8_inventory()
        self.assertEqual({}, new_inv._fileid_to_entry_cache)
        self.assertFalse(new_inv._fully_cached)
        new_inv._preload_cache()
        self.assertEqual(
            sorted([new_inv.root_id, b"fileid", b"dirid", b"childid"]),
            sorted(new_inv._fileid_to_entry_cache.keys()),
        )
        ie_root = new_inv._fileid_to_entry_cache[new_inv.root_id]
        self.assertEqual(
            ["dir-\N{EURO SIGN}", "f\xefle"], sorted(ie_root._children.keys())
        )
        ie_dir = new_inv._fileid_to_entry_cache[b"dirid"]
        self.assertEqual(["ch\xefld"], sorted(ie_dir._children.keys()))

    def test__preload_populates_cache(self):
        inv = Inventory()
        inv.revision_id = b"revid"
        inv.root.revision = b"rootrev"
        root_id = inv.root.file_id
        inv.add(InventoryFile(b"fileid", "file", root_id))
        inv.get_entry(b"fileid").revision = b"filerev"
        inv.get_entry(b"fileid").executable = True
        inv.get_entry(b"fileid").text_sha1 = b"ffff"
        inv.get_entry(b"fileid").text_size = 1
        inv.add(InventoryDirectory(b"dirid", "dir", root_id))
        inv.get_entry(b"dirid").revision = b"dirrev"
        inv.add(InventoryFile(b"childid", "child", b"dirid"))
        inv.get_entry(b"childid").revision = b"filerev"
        inv.get_entry(b"childid").executable = False
        inv.get_entry(b"childid").text_sha1 = b"dddd"
        inv.get_entry(b"childid").text_size = 1
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv)
        lines = chk_inv.to_lines()
        new_inv = CHKInventory.deserialise(chk_bytes, lines, (b"revid",))
        self.assertEqual({}, new_inv._fileid_to_entry_cache)
        self.assertFalse(new_inv._fully_cached)
        new_inv._preload_cache()
        self.assertEqual(
            sorted([root_id, b"fileid", b"dirid", b"childid"]),
            sorted(new_inv._fileid_to_entry_cache.keys()),
        )
        self.assertTrue(new_inv._fully_cached)
        ie_root = new_inv._fileid_to_entry_cache[root_id]
        self.assertEqual(["dir", "file"], sorted(ie_root._children.keys()))
        ie_dir = new_inv._fileid_to_entry_cache[b"dirid"]
        self.assertEqual(["child"], sorted(ie_dir._children.keys()))

    def test__preload_handles_partially_evaluated_inventory(self):
        new_inv = self.make_basic_utf8_inventory()
        ie = new_inv.get_entry(new_inv.root_id)
        self.assertIs(None, ie._children)
        self.assertEqual(["dir-\N{EURO SIGN}", "f\xefle"], sorted(ie.children.keys()))
        # Accessing .children loads _children
        self.assertEqual(["dir-\N{EURO SIGN}", "f\xefle"], sorted(ie._children.keys()))
        new_inv._preload_cache()
        # No change
        self.assertEqual(["dir-\N{EURO SIGN}", "f\xefle"], sorted(ie._children.keys()))
        ie_dir = new_inv.get_entry(b"dirid")
        self.assertEqual(["ch\xefld"], sorted(ie_dir._children.keys()))

    def test_filter_change_in_renamed_subfolder(self):
        inv = Inventory(b"tree-root")
        inv.root.revision = b"rootrev"
        src_ie = inv.add_path("src", "directory", b"src-id")
        src_ie.revision = b"srcrev"
        sub_ie = inv.add_path("src/sub/", "directory", b"sub-id")
        sub_ie.revision = b"subrev"
        a_ie = inv.add_path("src/sub/a", "file", b"a-id")
        a_ie.revision = b"filerev"
        a_ie.text_sha1 = osutils.sha_string(b"content\n")
        a_ie.text_size = len(b"content\n")
        chk_bytes = self.get_chk_bytes()
        inv = CHKInventory.from_inventory(chk_bytes, inv)
        inv = inv.create_by_apply_delta(
            [
                ("src/sub/a", "src/sub/a", b"a-id", a_ie),
                ("src", "src2", b"src-id", src_ie),
            ],
            b"new-rev-2",
        )
        new_inv = inv.filter([b"a-id", b"src-id"])
        self.assertEqual(
            [
                ("", b"tree-root"),
                ("src", b"src-id"),
                ("src/sub", b"sub-id"),
                ("src/sub/a", b"a-id"),
            ],
            [(path, ie.file_id) for path, ie in new_inv.iter_entries()],
        )


class TestCHKInventoryExpand(tests.TestCaseWithMemoryTransport):
    def get_chk_bytes(self):
        factory = groupcompress.make_pack_factory(True, True, 1)
        trans = self.get_transport("")
        return factory(trans)

    def make_dir(self, inv, name, parent_id, revision):
        ie = inv.make_entry("directory", name, parent_id, name.encode("utf-8") + b"-id")
        ie.revision = revision
        inv.add(ie)

    def make_file(self, inv, name, parent_id, revision, content=b"content\n"):
        ie = inv.make_entry("file", name, parent_id, name.encode("utf-8") + b"-id")
        ie.text_sha1 = osutils.sha_string(content)
        ie.text_size = len(content)
        ie.revision = revision
        inv.add(ie)

    def make_simple_inventory(self):
        inv = Inventory(b"TREE_ROOT")
        inv.revision_id = b"revid"
        inv.root.revision = b"rootrev"
        # /                 TREE_ROOT
        # dir1/             dir1-id
        #   sub-file1       sub-file1-id
        #   sub-file2       sub-file2-id
        #   sub-dir1/       sub-dir1-id
        #     subsub-file1  subsub-file1-id
        # dir2/             dir2-id
        #   sub2-file1      sub2-file1-id
        # top               top-id
        self.make_dir(inv, "dir1", b"TREE_ROOT", b"dirrev")
        self.make_dir(inv, "dir2", b"TREE_ROOT", b"dirrev")
        self.make_dir(inv, "sub-dir1", b"dir1-id", b"dirrev")
        self.make_file(inv, "top", b"TREE_ROOT", b"filerev")
        self.make_file(inv, "sub-file1", b"dir1-id", b"filerev")
        self.make_file(inv, "sub-file2", b"dir1-id", b"filerev")
        self.make_file(inv, "subsub-file1", b"sub-dir1-id", b"filerev")
        self.make_file(inv, "sub2-file1", b"dir2-id", b"filerev")
        chk_bytes = self.get_chk_bytes()
        #  use a small maximum_size to force internal paging structures
        chk_inv = CHKInventory.from_inventory(
            chk_bytes, inv, maximum_size=100, search_key_name=b"hash-255-way"
        )
        lines = chk_inv.to_lines()
        return CHKInventory.deserialise(chk_bytes, lines, (b"revid",))

    def assert_Getitems(self, expected_fileids, inv, file_ids):
        self.assertEqual(
            sorted(expected_fileids),
            sorted([ie.file_id for ie in inv._getitems(file_ids)]),
        )

    def assertExpand(self, all_ids, inv, file_ids):
        (val_all_ids, val_children) = inv._expand_fileids_to_parents_and_children(
            file_ids
        )
        self.assertEqual(set(all_ids), val_all_ids)
        entries = inv._getitems(val_all_ids)
        expected_children = {}
        for entry in entries:
            s = expected_children.setdefault(entry.parent_id, [])
            s.append(entry.file_id)
        val_children = {k: sorted(v) for k, v in val_children.items()}
        expected_children = {k: sorted(v) for k, v in expected_children.items()}
        self.assertEqual(expected_children, val_children)

    def test_make_simple_inventory(self):
        inv = self.make_simple_inventory()
        layout = []
        for path, entry in inv.iter_entries_by_dir():
            layout.append((path, entry.file_id))
        self.assertEqual(
            [
                ("", b"TREE_ROOT"),
                ("dir1", b"dir1-id"),
                ("dir2", b"dir2-id"),
                ("top", b"top-id"),
                ("dir1/sub-dir1", b"sub-dir1-id"),
                ("dir1/sub-file1", b"sub-file1-id"),
                ("dir1/sub-file2", b"sub-file2-id"),
                ("dir1/sub-dir1/subsub-file1", b"subsub-file1-id"),
                ("dir2/sub2-file1", b"sub2-file1-id"),
            ],
            layout,
        )

    def test__getitems(self):
        inv = self.make_simple_inventory()
        # Reading from disk
        self.assert_Getitems([b"dir1-id"], inv, [b"dir1-id"])
        self.assertTrue(b"dir1-id" in inv._fileid_to_entry_cache)
        self.assertFalse(b"sub-file2-id" in inv._fileid_to_entry_cache)
        # From cache
        self.assert_Getitems([b"dir1-id"], inv, [b"dir1-id"])
        # Mixed
        self.assert_Getitems(
            [b"dir1-id", b"sub-file2-id"], inv, [b"dir1-id", b"sub-file2-id"]
        )
        self.assertTrue(b"dir1-id" in inv._fileid_to_entry_cache)
        self.assertTrue(b"sub-file2-id" in inv._fileid_to_entry_cache)

    def test_single_file(self):
        inv = self.make_simple_inventory()
        self.assertExpand([b"TREE_ROOT", b"top-id"], inv, [b"top-id"])

    def test_get_all_parents(self):
        inv = self.make_simple_inventory()
        self.assertExpand(
            [
                b"TREE_ROOT",
                b"dir1-id",
                b"sub-dir1-id",
                b"subsub-file1-id",
            ],
            inv,
            [b"subsub-file1-id"],
        )

    def test_get_children(self):
        inv = self.make_simple_inventory()
        self.assertExpand(
            [
                b"TREE_ROOT",
                b"dir1-id",
                b"sub-dir1-id",
                b"sub-file1-id",
                b"sub-file2-id",
                b"subsub-file1-id",
            ],
            inv,
            [b"dir1-id"],
        )

    def test_from_root(self):
        inv = self.make_simple_inventory()
        self.assertExpand(
            [
                b"TREE_ROOT",
                b"dir1-id",
                b"dir2-id",
                b"sub-dir1-id",
                b"sub-file1-id",
                b"sub-file2-id",
                b"sub2-file1-id",
                b"subsub-file1-id",
                b"top-id",
            ],
            inv,
            [b"TREE_ROOT"],
        )

    def test_top_level_file(self):
        inv = self.make_simple_inventory()
        self.assertExpand([b"TREE_ROOT", b"top-id"], inv, [b"top-id"])

    def test_subsub_file(self):
        inv = self.make_simple_inventory()
        self.assertExpand(
            [b"TREE_ROOT", b"dir1-id", b"sub-dir1-id", b"subsub-file1-id"],
            inv,
            [b"subsub-file1-id"],
        )

    def test_sub_and_root(self):
        inv = self.make_simple_inventory()
        self.assertExpand(
            [b"TREE_ROOT", b"dir1-id", b"sub-dir1-id", b"top-id", b"subsub-file1-id"],
            inv,
            [b"top-id", b"subsub-file1-id"],
        )


class TestMutableInventoryFromTree(TestCaseWithTransport):
    def test_empty(self):
        repository = self.make_repository(".")
        tree = repository.revision_tree(revision.NULL_REVISION)
        inv = mutable_inventory_from_tree(tree)
        self.assertEqual(revision.NULL_REVISION, inv.revision_id)
        self.assertEqual(0, len(inv))

    def test_some_files(self):
        wt = self.make_branch_and_tree(".")
        self.build_tree(["a"])
        wt.add(["a"], ids=[b"thefileid"])
        revid = wt.commit("commit")
        tree = wt.branch.repository.revision_tree(revid)
        inv = mutable_inventory_from_tree(tree)
        self.assertEqual(revid, inv.revision_id)
        self.assertEqual(2, len(inv))
        self.assertEqual("a", inv.get_entry(b"thefileid").name)
        # The inventory should be mutable and independent of
        # the original tree
        self.assertFalse(tree.root_inventory.get_entry(b"thefileid").executable)
        inv.get_entry(b"thefileid").executable = True
        self.assertFalse(tree.root_inventory.get_entry(b"thefileid").executable)


class ErrorTests(TestCase):
    def test_duplicate_file_id(self):
        error = DuplicateFileId("a_file_id", "foo")
        self.assertEqualDiff(
            "File id {a_file_id} already exists in inventory as foo", str(error)
        )
