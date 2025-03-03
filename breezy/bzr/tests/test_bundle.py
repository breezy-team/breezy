# Copyright (C) 2005-2013, 2016 Canonical Ltd
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

import bz2
import os
import sys
import tempfile
from io import BytesIO

from ... import diff, errors, merge, osutils, tests, treebuilder
from ... import revision as _mod_revision
from ... import transport as _mod_transport
from ...tests import features, test_commit
from ...tree import InterTree
from .. import bzrdir, inventory, knitrepo
from ..bundle.apply_bundle import install_bundle, merge_bundle
from ..bundle.bundle_data import BundleTree
from ..bundle.serializer import read_bundle, v09, v4, write_bundle
from ..bundle.serializer.v08 import BundleSerializerV08
from ..bundle.serializer.v09 import BundleSerializerV09
from ..bundle.serializer.v4 import BundleSerializerV4
from ..inventorytree import InventoryTree


def get_text(vf, key):
    """Get the fulltext for a given revision id that is present in the vf."""
    stream = vf.get_record_stream([key], "unordered", True)
    record = next(stream)
    return record.get_bytes_as("fulltext")


def get_inventory_text(repo, revision_id):
    """Get the fulltext for the inventory at revision id."""
    with repo.lock_read():
        return get_text(repo.inventories, (revision_id,))


class MockTree(InventoryTree):
    def __init__(self):
        from ..inventory import ROOT_ID, InventoryDirectory

        object.__init__(self)
        self.paths = {ROOT_ID: ""}
        self.ids = {"": ROOT_ID}
        self.contents = {}
        self.root = InventoryDirectory(ROOT_ID, "", None)

    inventory = property(lambda x: x)
    root_inventory = property(lambda x: x)

    def get_root_id(self):
        return self.root.file_id

    def all_file_ids(self):
        return set(self.paths.keys())

    def all_versioned_paths(self):
        return set(self.paths.values())

    def is_executable(self, path):
        # Not all the files are executable.
        return False

    def __getitem__(self, file_id):
        if file_id == self.root.file_id:
            return self.root
        else:
            return self.make_entry(file_id, self.paths[file_id])

    def get_entry_by_path(self, path):
        return self[self.path2id(path)]

    def parent_id(self, file_id):
        parent_dir = os.path.dirname(self.paths[file_id])
        if parent_dir == "":
            return None
        return self.ids[parent_dir]

    def iter_entries(self):
        for path, file_id in self.ids.items():
            yield path, self[file_id]

    def kind(self, path):
        if path in self.contents:
            kind = "file"
        else:
            kind = "directory"
        return kind

    def make_entry(self, file_id, path):
        from ..inventory import InventoryDirectory, InventoryFile, InventoryLink

        if not isinstance(file_id, bytes):
            raise TypeError(file_id)
        name = os.path.basename(path)
        kind = self.kind(path)
        parent_id = self.parent_id(file_id)
        text_sha_1, text_size = self.contents_stats(path)
        if kind == "directory":
            ie = InventoryDirectory(file_id, name, parent_id)
        elif kind == "file":
            ie = InventoryFile(file_id, name, parent_id)
            ie.text_sha1 = text_sha_1
            ie.text_size = text_size
        elif kind == "symlink":
            ie = InventoryLink(file_id, name, parent_id)
        else:
            raise errors.BzrError("unknown kind {!r}".format(kind))
        return ie

    def add_dir(self, file_id, path):
        if not isinstance(file_id, bytes):
            raise TypeError(file_id)
        self.paths[file_id] = path
        self.ids[path] = file_id

    def add_file(self, file_id, path, contents):
        if not isinstance(file_id, bytes):
            raise TypeError(file_id)
        self.add_dir(file_id, path)
        self.contents[path] = contents

    def path2id(self, path):
        return self.ids.get(path)

    def id2path(self, file_id, recurse="down"):
        try:
            return self.paths[file_id]
        except KeyError as e:
            raise errors.NoSuchId(file_id, self) from e

    def get_file(self, path):
        result = BytesIO()
        try:
            result.write(self.contents[path])
        except KeyError as e:
            raise _mod_transport.NoSuchFile(path) from e
        result.seek(0, 0)
        return result

    def get_file_revision(self, path):
        return self.inventory.get_entry_by_path(path).revision

    def get_file_size(self, path):
        return self.inventory.get_entry_by_path(path).text_size

    def get_file_sha1(self, path, file_id=None):
        return self.inventory.get_entry_by_path(path).text_sha1

    def contents_stats(self, path):
        if path not in self.contents:
            return None, None
        text_sha1 = osutils.sha_file(self.get_file(path))
        return text_sha1, len(self.contents[path])


class BTreeTester(tests.TestCase):
    """A simple unittest tester for the BundleTree class."""

    def make_tree_1(self):
        mtree = MockTree()
        mtree.add_dir(b"a", "grandparent")
        mtree.add_dir(b"b", "grandparent/parent")
        mtree.add_file(b"c", "grandparent/parent/file", b"Hello\n")
        mtree.add_dir(b"d", "grandparent/alt_parent")
        return BundleTree(mtree, b""), mtree

    def test_renames(self):
        """Ensure that file renames have the proper effect on children."""
        btree = self.make_tree_1()[0]
        self.assertEqual(btree.old_path("grandparent"), "grandparent")
        self.assertEqual(btree.old_path("grandparent/parent"), "grandparent/parent")
        self.assertEqual(
            btree.old_path("grandparent/parent/file"), "grandparent/parent/file"
        )

        self.assertEqual(btree.id2path(b"a"), "grandparent")
        self.assertEqual(btree.id2path(b"b"), "grandparent/parent")
        self.assertEqual(btree.id2path(b"c"), "grandparent/parent/file")

        self.assertEqual(btree.path2id("grandparent"), b"a")
        self.assertEqual(btree.path2id("grandparent/parent"), b"b")
        self.assertEqual(btree.path2id("grandparent/parent/file"), b"c")

        self.assertIs(btree.path2id("grandparent2"), None)
        self.assertIs(btree.path2id("grandparent2/parent"), None)
        self.assertIs(btree.path2id("grandparent2/parent/file"), None)

        btree.note_rename("grandparent", "grandparent2")
        self.assertIs(btree.old_path("grandparent"), None)
        self.assertIs(btree.old_path("grandparent/parent"), None)
        self.assertIs(btree.old_path("grandparent/parent/file"), None)

        self.assertEqual(btree.id2path(b"a"), "grandparent2")
        self.assertEqual(btree.id2path(b"b"), "grandparent2/parent")
        self.assertEqual(btree.id2path(b"c"), "grandparent2/parent/file")

        self.assertEqual(btree.path2id("grandparent2"), b"a")
        self.assertEqual(btree.path2id("grandparent2/parent"), b"b")
        self.assertEqual(btree.path2id("grandparent2/parent/file"), b"c")

        self.assertTrue(btree.path2id("grandparent") is None)
        self.assertTrue(btree.path2id("grandparent/parent") is None)
        self.assertTrue(btree.path2id("grandparent/parent/file") is None)

        btree.note_rename("grandparent/parent", "grandparent2/parent2")
        self.assertEqual(btree.id2path(b"a"), "grandparent2")
        self.assertEqual(btree.id2path(b"b"), "grandparent2/parent2")
        self.assertEqual(btree.id2path(b"c"), "grandparent2/parent2/file")

        self.assertEqual(btree.path2id("grandparent2"), b"a")
        self.assertEqual(btree.path2id("grandparent2/parent2"), b"b")
        self.assertEqual(btree.path2id("grandparent2/parent2/file"), b"c")

        self.assertTrue(btree.path2id("grandparent2/parent") is None)
        self.assertTrue(btree.path2id("grandparent2/parent/file") is None)

        btree.note_rename("grandparent/parent/file", "grandparent2/parent2/file2")
        self.assertEqual(btree.id2path(b"a"), "grandparent2")
        self.assertEqual(btree.id2path(b"b"), "grandparent2/parent2")
        self.assertEqual(btree.id2path(b"c"), "grandparent2/parent2/file2")

        self.assertEqual(btree.path2id("grandparent2"), b"a")
        self.assertEqual(btree.path2id("grandparent2/parent2"), b"b")
        self.assertEqual(btree.path2id("grandparent2/parent2/file2"), b"c")

        self.assertTrue(btree.path2id("grandparent2/parent2/file") is None)

    def test_moves(self):
        """Ensure that file moves have the proper effect on children."""
        btree = self.make_tree_1()[0]
        btree.note_rename("grandparent/parent/file", "grandparent/alt_parent/file")
        self.assertEqual(btree.id2path(b"c"), "grandparent/alt_parent/file")
        self.assertEqual(btree.path2id("grandparent/alt_parent/file"), b"c")
        self.assertTrue(btree.path2id("grandparent/parent/file") is None)

    def unified_diff(self, old, new):
        out = BytesIO()
        diff.internal_diff("old", old, "new", new, out)
        out.seek(0, 0)
        return out.read()

    def make_tree_2(self):
        btree = self.make_tree_1()[0]
        btree.note_rename("grandparent/parent/file", "grandparent/alt_parent/file")
        self.assertRaises(errors.NoSuchId, btree.id2path, b"e")
        self.assertFalse(btree.is_versioned("grandparent/parent/file"))
        btree.note_id(b"e", "grandparent/parent/file")
        return btree

    def test_adds(self):
        """File/inventory adds."""
        btree = self.make_tree_2()
        add_patch = self.unified_diff([], [b"Extra cheese\n"])
        btree.note_patch("grandparent/parent/file", add_patch)
        btree.note_id(b"f", "grandparent/parent/symlink", kind="symlink")
        btree.note_target("grandparent/parent/symlink", "venus")
        self.adds_test(btree)

    def adds_test(self, btree):
        self.assertEqual(btree.id2path(b"e"), "grandparent/parent/file")
        self.assertEqual(btree.path2id("grandparent/parent/file"), b"e")
        with btree.get_file("grandparent/parent/file") as f:
            self.assertEqual(f.read(), b"Extra cheese\n")
        self.assertEqual(
            btree.get_symlink_target("grandparent/parent/symlink"), "venus"
        )

    def make_tree_3(self):
        btree, mtree = self.make_tree_1()
        mtree.add_file(b"e", "grandparent/parent/topping", b"Anchovies\n")
        btree.note_rename("grandparent/parent/file", "grandparent/alt_parent/file")
        btree.note_rename(
            "grandparent/parent/topping", "grandparent/alt_parent/stopping"
        )
        return btree

    def get_file_test(self, btree):
        with btree.get_file(btree.id2path(b"e")) as f:
            self.assertEqual(f.read(), b"Lemon\n")
        with btree.get_file(btree.id2path(b"c")) as f:
            self.assertEqual(f.read(), b"Hello\n")

    def test_get_file(self):
        """Get file contents."""
        btree = self.make_tree_3()
        mod_patch = self.unified_diff([b"Anchovies\n"], [b"Lemon\n"])
        btree.note_patch("grandparent/alt_parent/stopping", mod_patch)
        self.get_file_test(btree)

    def test_delete(self):
        """Deletion by bundle."""
        btree = self.make_tree_1()[0]
        with btree.get_file(btree.id2path(b"c")) as f:
            self.assertEqual(f.read(), b"Hello\n")
        btree.note_deletion("grandparent/parent/file")
        self.assertRaises(errors.NoSuchId, btree.id2path, b"c")
        self.assertFalse(btree.is_versioned("grandparent/parent/file"))

    def sorted_ids(self, tree):
        ids = sorted(tree.all_file_ids())
        return ids

    def test_iteration(self):
        """Ensure that iteration through ids works properly."""
        btree = self.make_tree_1()[0]
        self.assertEqual(
            self.sorted_ids(btree), [inventory.ROOT_ID, b"a", b"b", b"c", b"d"]
        )
        btree.note_deletion("grandparent/parent/file")
        btree.note_id(b"e", "grandparent/alt_parent/fool", kind="directory")
        btree.note_last_changed("grandparent/alt_parent/fool", "revisionidiguess")
        self.assertEqual(
            self.sorted_ids(btree), [inventory.ROOT_ID, b"a", b"b", b"d", b"e"]
        )


class BundleTester1(tests.TestCaseWithTransport):
    def test_mismatched_bundle(self):
        format = bzrdir.BzrDirMetaFormat1()
        format.repository_format = knitrepo.RepositoryFormatKnit3()
        serializer = BundleSerializerV08("0.8")
        b = self.make_branch(".", format=format)
        self.assertRaises(
            errors.IncompatibleBundleFormat,
            serializer.write,
            b.repository,
            [],
            {},
            BytesIO(),
        )

    def test_matched_bundle(self):
        """Don't raise IncompatibleBundleFormat for knit2 and bundle0.9."""
        format = bzrdir.BzrDirMetaFormat1()
        format.repository_format = knitrepo.RepositoryFormatKnit3()
        serializer = BundleSerializerV09("0.9")
        b = self.make_branch(".", format=format)
        serializer.write(b.repository, [], {}, BytesIO())

    def test_mismatched_model(self):
        """Try copying a bundle from knit2 to knit1."""
        format = bzrdir.BzrDirMetaFormat1()
        format.repository_format = knitrepo.RepositoryFormatKnit3()
        source = self.make_branch_and_tree("source", format=format)
        source.commit("one", rev_id=b"one-id")
        source.commit("two", rev_id=b"two-id")
        text = BytesIO()
        write_bundle(source.branch.repository, b"two-id", b"null:", text, format="0.9")
        text.seek(0)

        format = bzrdir.BzrDirMetaFormat1()
        format.repository_format = knitrepo.RepositoryFormatKnit1()
        target = self.make_branch("target", format=format)
        self.assertRaises(
            errors.IncompatibleRevision,
            install_bundle,
            target.repository,
            read_bundle(text),
        )


class BundleTester:
    def bzrdir_format(self):
        format = bzrdir.BzrDirMetaFormat1()
        format.repository_format = knitrepo.RepositoryFormatKnit1()
        return format

    def make_branch_and_tree(self, path, format=None):
        if format is None:
            format = self.bzrdir_format()
        return tests.TestCaseWithTransport.make_branch_and_tree(self, path, format)

    def make_branch(self, path, format=None, name=None):
        if format is None:
            format = self.bzrdir_format()
        return tests.TestCaseWithTransport.make_branch(self, path, format, name=name)

    def create_bundle_text(self, base_rev_id, rev_id):
        bundle_txt = BytesIO()
        rev_ids = write_bundle(
            self.b1.repository, rev_id, base_rev_id, bundle_txt, format=self.format
        )
        bundle_txt.seek(0)
        self.assertEqual(
            bundle_txt.readline(),
            b"# Bazaar revision bundle v%s\n" % self.format.encode("ascii"),
        )
        self.assertEqual(bundle_txt.readline(), b"#\n")

        self.b1.repository.get_revision(rev_id)
        self.assertEqual(bundle_txt.readline().decode("utf-8"), "# message:\n")
        bundle_txt.seek(0)
        return bundle_txt, rev_ids

    def get_valid_bundle(self, base_rev_id, rev_id, checkout_dir=None):
        """Create a bundle from base_rev_id -> rev_id in built-in branch.
        Make sure that the text generated is valid, and that it
        can be applied against the base, and generate the same information.

        :return: The in-memory bundle
        """
        bundle_txt, rev_ids = self.create_bundle_text(base_rev_id, rev_id)

        # This should also validate the generated bundle
        bundle = read_bundle(bundle_txt)
        repository = self.b1.repository
        for bundle_rev in bundle.real_revisions:
            # These really should have already been checked when we read the
            # bundle, since it computes the sha1 hash for the revision, which
            # only will match if everything is okay, but lets be explicit about
            # it
            branch_rev = repository.get_revision(bundle_rev.revision_id)
            for a in (
                "inventory_sha1",
                "revision_id",
                "parent_ids",
                "timestamp",
                "timezone",
                "message",
                "committer",
                "parent_ids",
                "properties",
            ):
                self.assertEqual(getattr(branch_rev, a), getattr(bundle_rev, a))
            self.assertEqual(len(branch_rev.parent_ids), len(bundle_rev.parent_ids))
        self.assertEqual(rev_ids, [r.revision_id for r in bundle.real_revisions])
        self.valid_apply_bundle(base_rev_id, bundle, checkout_dir=checkout_dir)

        return bundle

    def get_invalid_bundle(self, base_rev_id, rev_id):
        """Create a bundle from base_rev_id -> rev_id in built-in branch.
        Munge the text so that it's invalid.

        :return: The in-memory bundle
        """
        bundle_txt, rev_ids = self.create_bundle_text(base_rev_id, rev_id)
        new_text = bundle_txt.getvalue().replace(b"executable:no", b"executable:yes")
        bundle_txt = BytesIO(new_text)
        bundle = read_bundle(bundle_txt)
        self.valid_apply_bundle(base_rev_id, bundle)
        return bundle

    def test_non_bundle(self):
        self.assertRaises(errors.NotABundle, read_bundle, BytesIO(b"#!/bin/sh\n"))

    def test_malformed(self):
        self.assertRaises(
            errors.BadBundle, read_bundle, BytesIO(b"# Bazaar revision bundle v")
        )

    def test_crlf_bundle(self):
        try:
            read_bundle(BytesIO(b"# Bazaar revision bundle v0.8\r\n"))
        except errors.BadBundle:
            # It is currently permitted for bundles with crlf line endings to
            # make read_bundle raise a BadBundle, but this should be fixed.
            # Anything else, especially NotABundle, is an error.
            pass

    def get_checkout(self, rev_id, checkout_dir=None):
        """Get a new tree, with the specified revision in it."""
        if checkout_dir is None:
            checkout_dir = tempfile.mkdtemp(prefix="test-branch-", dir=".")
            checkout_dir = os.path.relpath(checkout_dir, os.getcwd())
        else:
            if not os.path.exists(checkout_dir):
                os.mkdir(checkout_dir)
        tree = self.make_branch_and_tree(checkout_dir)
        s = BytesIO()
        ancestors = write_bundle(
            self.b1.repository, rev_id, b"null:", s, format=self.format
        )
        s.seek(0)
        self.assertIsInstance(s.getvalue(), bytes)
        install_bundle(tree.branch.repository, read_bundle(s))
        for ancestor in ancestors:
            old = self.b1.repository.revision_tree(ancestor)
            new = tree.branch.repository.revision_tree(ancestor)
            with old.lock_read(), new.lock_read():
                # Check that there aren't any inventory level changes
                delta = new.changes_from(old)
                self.assertFalse(
                    delta.has_changed(),
                    "Revision {} not copied correctly.".format(ancestor),
                )

                # Now check that the file contents are all correct
                for path in old.all_versioned_paths():
                    try:
                        old_file = old.get_file(path)
                    except _mod_transport.NoSuchFile:
                        continue
                    self.assertEqual(old_file.read(), new.get_file(path).read())
        if not _mod_revision.is_null(rev_id):
            tree.branch.generate_revision_history(rev_id)
            tree.update()
            delta = tree.changes_from(self.b1.repository.revision_tree(rev_id))
            self.assertFalse(
                delta.has_changed(), "Working tree has modifications: {}".format(delta)
            )
        return tree

    def valid_apply_bundle(self, base_rev_id, info, checkout_dir=None):
        """Get the base revision, apply the changes, and make
        sure everything matches the builtin branch.
        """
        to_tree = self.get_checkout(base_rev_id, checkout_dir=checkout_dir)
        to_tree.lock_write()
        try:
            self._valid_apply_bundle(base_rev_id, info, to_tree)
        finally:
            to_tree.unlock()

    def _valid_apply_bundle(self, base_rev_id, info, to_tree):
        original_parents = to_tree.get_parent_ids()
        repository = to_tree.branch.repository
        original_parents = to_tree.get_parent_ids()
        self.assertIs(repository.has_revision(base_rev_id), True)
        for rev in info.real_revisions:
            self.assertTrue(
                not repository.has_revision(rev.revision_id),
                "Revision {{{}}} present before applying bundle".format(
                    rev.revision_id
                ),
            )
        merge_bundle(info, to_tree, True, merge.Merge3Merger, False, False)

        for rev in info.real_revisions:
            self.assertTrue(
                repository.has_revision(rev.revision_id),
                "Missing revision {{{}}} after applying bundle".format(rev.revision_id),
            )

        self.assertTrue(to_tree.branch.repository.has_revision(info.target))
        # Do we also want to verify that all the texts have been added?

        self.assertEqual(original_parents + [info.target], to_tree.get_parent_ids())

        rev = info.real_revisions[-1]
        base_tree = self.b1.repository.revision_tree(rev.revision_id)
        to_tree = to_tree.branch.repository.revision_tree(rev.revision_id)

        # TODO: make sure the target tree is identical to base tree
        #       we might also check the working tree.

        base_files = list(base_tree.list_files())
        to_files = list(to_tree.list_files())
        self.assertEqual(len(base_files), len(to_files))
        for base_file, to_file in zip(base_files, to_files):
            self.assertEqual(base_file, to_file)

        for path, _status, _kind, _entry in base_files:
            # Check that the meta information is the same
            to_path = InterTree.get(base_tree, to_tree).find_target_path(path)
            self.assertEqual(
                base_tree.get_file_size(path), to_tree.get_file_size(to_path)
            )
            self.assertEqual(
                base_tree.get_file_sha1(path), to_tree.get_file_sha1(to_path)
            )
            # Check that the contents are the same
            # This is pretty expensive
            # self.assertEqual(base_tree.get_file(fileid).read(),
            #         to_tree.get_file(fileid).read())

    def test_bundle(self):
        self.tree1 = self.make_branch_and_tree("b1")
        self.b1 = self.tree1.branch

        self.build_tree_contents([("b1/one", b"one\n")])
        self.tree1.add("one", ids=b"one-id")
        self.tree1.set_root_id(b"root-id")
        self.tree1.commit("add one", rev_id=b"a@cset-0-1")

        self.get_valid_bundle(b"null:", b"a@cset-0-1")

        # Make sure we can handle files with spaces, tabs, other
        # bogus characters
        self.build_tree(
            [
                "b1/with space.txt",
                "b1/dir/",
                "b1/dir/filein subdir.c",
                "b1/dir/WithCaps.txt",
                "b1/dir/ pre space",
                "b1/sub/",
                "b1/sub/sub/",
                "b1/sub/sub/nonempty.txt",
            ]
        )
        self.build_tree_contents(
            [("b1/sub/sub/emptyfile.txt", b""), ("b1/dir/nolastnewline.txt", b"bloop")]
        )
        tt = self.tree1.transform()
        tt.new_file("executable", tt.root, [b"#!/bin/sh\n"], b"exe-1", True)
        tt.apply()
        # have to fix length of file-id so that we can predictably rewrite
        # a (length-prefixed) record containing it later.
        self.tree1.add("with space.txt", ids=b"withspace-id")
        self.tree1.add(
            [
                "dir",
                "dir/filein subdir.c",
                "dir/WithCaps.txt",
                "dir/ pre space",
                "dir/nolastnewline.txt",
                "sub",
                "sub/sub",
                "sub/sub/nonempty.txt",
                "sub/sub/emptyfile.txt",
            ]
        )
        self.tree1.commit("add whitespace", rev_id=b"a@cset-0-2")

        self.get_valid_bundle(b"a@cset-0-1", b"a@cset-0-2")

        # Check a rollup bundle
        self.get_valid_bundle(b"null:", b"a@cset-0-2")

        # Now delete entries
        self.tree1.remove(["sub/sub/nonempty.txt", "sub/sub/emptyfile.txt", "sub/sub"])
        tt = self.tree1.transform()
        trans_id = tt.trans_id_tree_path("executable")
        tt.set_executability(False, trans_id)
        tt.apply()
        self.tree1.commit("removed", rev_id=b"a@cset-0-3")

        self.get_valid_bundle(b"a@cset-0-2", b"a@cset-0-3")
        self.assertRaises(
            (
                errors.TestamentMismatch,
                errors.VersionedFileInvalidChecksum,
                errors.BadBundle,
            ),
            self.get_invalid_bundle,
            b"a@cset-0-2",
            b"a@cset-0-3",
        )
        # Check a rollup bundle
        self.get_valid_bundle(b"null:", b"a@cset-0-3")

        # Now move the directory
        self.tree1.rename_one("dir", "sub/dir")
        self.tree1.commit("rename dir", rev_id=b"a@cset-0-4")

        self.get_valid_bundle(b"a@cset-0-3", b"a@cset-0-4")
        # Check a rollup bundle
        self.get_valid_bundle(b"null:", b"a@cset-0-4")

        # Modified files
        with open("b1/sub/dir/WithCaps.txt", "ab") as f:
            f.write(b"\nAdding some text\n")
        with open("b1/sub/dir/ pre space", "ab") as f:
            f.write(b"\r\nAdding some\r\nDOS format lines\r\n")
        with open("b1/sub/dir/nolastnewline.txt", "ab") as f:
            f.write(b"\n")
        self.tree1.rename_one("sub/dir/ pre space", "sub/ start space")
        self.tree1.commit("Modified files", rev_id=b"a@cset-0-5")
        self.get_valid_bundle(b"a@cset-0-4", b"a@cset-0-5")

        self.tree1.rename_one("sub/dir/WithCaps.txt", "temp")
        self.tree1.rename_one("with space.txt", "WithCaps.txt")
        self.tree1.rename_one("temp", "with space.txt")
        self.tree1.commit("swap filenames", rev_id=b"a@cset-0-6", verbose=False)
        self.get_valid_bundle(b"a@cset-0-5", b"a@cset-0-6")
        other = self.get_checkout(b"a@cset-0-5")
        tree1_inv = get_inventory_text(self.tree1.branch.repository, b"a@cset-0-5")
        tree2_inv = get_inventory_text(other.branch.repository, b"a@cset-0-5")
        self.assertEqualDiff(tree1_inv, tree2_inv)
        other.rename_one("sub/dir/nolastnewline.txt", "sub/nolastnewline.txt")
        other.commit("rename file", rev_id=b"a@cset-0-6b")
        self.tree1.merge_from_branch(other.branch)
        self.tree1.commit("Merge", rev_id=b"a@cset-0-7", verbose=False)
        self.get_valid_bundle(b"a@cset-0-6", b"a@cset-0-7")

    def _test_symlink_bundle(self, link_name, link_target, new_link_target):
        link_id = b"link-1"

        self.requireFeature(features.SymlinkFeature(self.test_dir))
        self.tree1 = self.make_branch_and_tree("b1")
        self.b1 = self.tree1.branch

        tt = self.tree1.transform()
        tt.new_symlink(link_name, tt.root, link_target, link_id)
        tt.apply()
        self.tree1.commit("add symlink", rev_id=b"l@cset-0-1")
        bundle = self.get_valid_bundle(b"null:", b"l@cset-0-1")
        if getattr(bundle, "revision_tree", None) is not None:
            # Not all bundle formats supports revision_tree
            bund_tree = bundle.revision_tree(self.b1.repository, b"l@cset-0-1")
            self.assertEqual(link_target, bund_tree.get_symlink_target(link_name))

        tt = self.tree1.transform()
        trans_id = tt.trans_id_tree_path(link_name)
        tt.adjust_path("link2", tt.root, trans_id)
        tt.delete_contents(trans_id)
        tt.create_symlink(new_link_target, trans_id)
        tt.apply()
        self.tree1.commit("rename and change symlink", rev_id=b"l@cset-0-2")
        bundle = self.get_valid_bundle(b"l@cset-0-1", b"l@cset-0-2")
        if getattr(bundle, "revision_tree", None) is not None:
            # Not all bundle formats supports revision_tree
            bund_tree = bundle.revision_tree(self.b1.repository, b"l@cset-0-2")
            self.assertEqual(new_link_target, bund_tree.get_symlink_target("link2"))

        tt = self.tree1.transform()
        trans_id = tt.trans_id_tree_path("link2")
        tt.delete_contents(trans_id)
        tt.create_symlink("jupiter", trans_id)
        tt.apply()
        self.tree1.commit("just change symlink target", rev_id=b"l@cset-0-3")
        bundle = self.get_valid_bundle(b"l@cset-0-2", b"l@cset-0-3")

        tt = self.tree1.transform()
        trans_id = tt.trans_id_tree_path("link2")
        tt.delete_contents(trans_id)
        tt.apply()
        self.tree1.commit("Delete symlink", rev_id=b"l@cset-0-4")
        bundle = self.get_valid_bundle(b"l@cset-0-3", b"l@cset-0-4")

    def test_symlink_bundle(self):
        self._test_symlink_bundle("link", "bar/foo", "mars")

    def test_unicode_symlink_bundle(self):
        self.requireFeature(features.UnicodeFilenameFeature)
        self._test_symlink_bundle(
            "\N{EURO SIGN}link", "bar/\N{EURO SIGN}foo", "mars\N{EURO SIGN}"
        )

    def test_binary_bundle(self):
        self.tree1 = self.make_branch_and_tree("b1")
        self.b1 = self.tree1.branch
        tt = self.tree1.transform()

        # Add
        tt.new_file("file", tt.root, [b"\x00\n\x00\r\x01\n\x02\r\xff"], b"binary-1")
        tt.new_file("file2", tt.root, [b"\x01\n\x02\r\x03\n\x04\r\xff"], b"binary-2")
        tt.apply()
        self.tree1.commit("add binary", rev_id=b"b@cset-0-1")
        self.get_valid_bundle(b"null:", b"b@cset-0-1")

        # Delete
        tt = self.tree1.transform()
        trans_id = tt.trans_id_tree_path("file")
        tt.delete_contents(trans_id)
        tt.apply()
        self.tree1.commit("delete binary", rev_id=b"b@cset-0-2")
        self.get_valid_bundle(b"b@cset-0-1", b"b@cset-0-2")

        # Rename & modify
        tt = self.tree1.transform()
        trans_id = tt.trans_id_tree_path("file2")
        tt.adjust_path("file3", tt.root, trans_id)
        tt.delete_contents(trans_id)
        tt.create_file([b"file\rcontents\x00\n\x00"], trans_id)
        tt.apply()
        self.tree1.commit("rename and modify binary", rev_id=b"b@cset-0-3")
        self.get_valid_bundle(b"b@cset-0-2", b"b@cset-0-3")

        # Modify
        tt = self.tree1.transform()
        trans_id = tt.trans_id_tree_path("file3")
        tt.delete_contents(trans_id)
        tt.create_file([b"\x00file\rcontents"], trans_id)
        tt.apply()
        self.tree1.commit("just modify binary", rev_id=b"b@cset-0-4")
        self.get_valid_bundle(b"b@cset-0-3", b"b@cset-0-4")

        # Rollup
        self.get_valid_bundle(b"null:", b"b@cset-0-4")

    def test_last_modified(self):
        self.tree1 = self.make_branch_and_tree("b1")
        self.b1 = self.tree1.branch
        tt = self.tree1.transform()
        tt.new_file("file", tt.root, [b"file"], b"file")
        tt.apply()
        self.tree1.commit("create file", rev_id=b"a@lmod-0-1")

        tt = self.tree1.transform()
        trans_id = tt.trans_id_tree_path("file")
        tt.delete_contents(trans_id)
        tt.create_file([b"file2"], trans_id)
        tt.apply()
        self.tree1.commit("modify text", rev_id=b"a@lmod-0-2a")

        other = self.get_checkout(b"a@lmod-0-1")
        tt = other.transform()
        trans_id = tt.trans_id_tree_path("file2")
        tt.delete_contents(trans_id)
        tt.create_file([b"file2"], trans_id)
        tt.apply()
        other.commit("modify text in another tree", rev_id=b"a@lmod-0-2b")
        self.tree1.merge_from_branch(other.branch)
        self.tree1.commit("Merge", rev_id=b"a@lmod-0-3", verbose=False)
        self.tree1.commit("Merge", rev_id=b"a@lmod-0-4")
        self.get_valid_bundle(b"a@lmod-0-2a", b"a@lmod-0-4")

    def test_hide_history(self):
        self.tree1 = self.make_branch_and_tree("b1")
        self.b1 = self.tree1.branch

        with open("b1/one", "wb") as f:
            f.write(b"one\n")
        self.tree1.add("one")
        self.tree1.commit("add file", rev_id=b"a@cset-0-1")
        with open("b1/one", "wb") as f:
            f.write(b"two\n")
        self.tree1.commit("modify", rev_id=b"a@cset-0-2")
        with open("b1/one", "wb") as f:
            f.write(b"three\n")
        self.tree1.commit("modify", rev_id=b"a@cset-0-3")
        bundle_file = BytesIO()
        write_bundle(
            self.tree1.branch.repository,
            b"a@cset-0-3",
            b"a@cset-0-1",
            bundle_file,
            format=self.format,
        )
        self.assertNotContainsRe(bundle_file.getvalue(), b"\btwo\b")
        self.assertContainsRe(self.get_raw(bundle_file), b"one")
        self.assertContainsRe(self.get_raw(bundle_file), b"three")

    def test_bundle_same_basis(self):
        """Ensure using the basis as the target doesn't cause an error."""
        self.tree1 = self.make_branch_and_tree("b1")
        self.tree1.commit("add file", rev_id=b"a@cset-0-1")
        bundle_file = BytesIO()
        write_bundle(
            self.tree1.branch.repository, b"a@cset-0-1", b"a@cset-0-1", bundle_file
        )

    @staticmethod
    def get_raw(bundle_file):
        return bundle_file.getvalue()

    def test_unicode_bundle(self):
        self.requireFeature(features.UnicodeFilenameFeature)
        # Handle international characters
        os.mkdir("b1")
        f = open("b1/with Dod\N{EURO SIGN}", "wb")

        self.tree1 = self.make_branch_and_tree("b1")
        self.b1 = self.tree1.branch

        f.write(
            ("A file\nWith international man of mystery\nWilliam Dod\xe9\n").encode()
        )
        f.close()

        self.tree1.add(["with Dod\N{EURO SIGN}"], ids=[b"withdod-id"])
        self.tree1.commit(
            "i18n commit from William Dod\xe9",
            rev_id=b"i18n-1",
            committer="William Dod\xe9",
        )

        # Add
        self.get_valid_bundle(b"null:", b"i18n-1")

        # Modified
        f = open("b1/with Dod\N{EURO SIGN}", "wb")
        f.write("Modified \xb5\n".encode())
        f.close()
        self.tree1.commit("modified", rev_id=b"i18n-2")

        self.get_valid_bundle(b"i18n-1", b"i18n-2")

        # Renamed
        self.tree1.rename_one("with Dod\N{EURO SIGN}", "B\N{EURO SIGN}gfors")
        self.tree1.commit(
            "renamed, the new i18n man", rev_id=b"i18n-3", committer="Erik B\xe5gfors"
        )

        self.get_valid_bundle(b"i18n-2", b"i18n-3")

        # Removed
        self.tree1.remove(["B\N{EURO SIGN}gfors"])
        self.tree1.commit("removed", rev_id=b"i18n-4")

        self.get_valid_bundle(b"i18n-3", b"i18n-4")

        # Rollup
        self.get_valid_bundle(b"null:", b"i18n-4")

    def test_whitespace_bundle(self):
        if sys.platform in ("win32", "cygwin"):
            raise tests.TestSkipped(
                "Windows doesn't support filenames with tabs or trailing spaces"
            )
        self.tree1 = self.make_branch_and_tree("b1")
        self.b1 = self.tree1.branch

        self.build_tree(["b1/trailing space "])
        self.tree1.add(["trailing space "])
        # TODO: jam 20060701 Check for handling files with '\t' characters
        #       once we actually support them

        # Added
        self.tree1.commit("funky whitespace", rev_id=b"white-1")

        self.get_valid_bundle(b"null:", b"white-1")

        # Modified
        with open("b1/trailing space ", "ab") as f:
            f.write(b"add some text\n")
        self.tree1.commit("add text", rev_id=b"white-2")

        self.get_valid_bundle(b"white-1", b"white-2")

        # Renamed
        self.tree1.rename_one("trailing space ", " start and end space ")
        self.tree1.commit("rename", rev_id=b"white-3")

        self.get_valid_bundle(b"white-2", b"white-3")

        # Removed
        self.tree1.remove([" start and end space "])
        self.tree1.commit("removed", rev_id=b"white-4")

        self.get_valid_bundle(b"white-3", b"white-4")

        # Now test a complet roll-up
        self.get_valid_bundle(b"null:", b"white-4")

    def test_alt_timezone_bundle(self):
        self.tree1 = self.make_branch_and_memory_tree("b1")
        self.b1 = self.tree1.branch
        builder = treebuilder.TreeBuilder()

        self.tree1.lock_write()
        builder.start_tree(self.tree1)
        builder.build(["newfile"])
        builder.finish_tree()

        # Asia/Colombo offset = 5 hours 30 minutes
        self.tree1.commit(
            "non-hour offset timezone",
            rev_id=b"tz-1",
            timezone=19800,
            timestamp=1152544886.0,
        )

        bundle = self.get_valid_bundle(b"null:", b"tz-1")

        rev = bundle.revisions[0]
        self.assertEqual("Mon 2006-07-10 20:51:26.000000000 +0530", rev.date)
        self.assertEqual(19800, rev.timezone)
        self.assertEqual(1152544886.0, rev.timestamp)
        self.tree1.unlock()

    def test_bundle_root_id(self):
        self.tree1 = self.make_branch_and_tree("b1")
        self.b1 = self.tree1.branch
        self.tree1.commit("message", rev_id=b"revid1")
        bundle = self.get_valid_bundle(b"null:", b"revid1")
        tree = self.get_bundle_tree(bundle, b"revid1")
        root_revision = tree.get_file_revision("")
        self.assertEqual(b"revid1", root_revision)

    def test_install_revisions(self):
        self.tree1 = self.make_branch_and_tree("b1")
        self.b1 = self.tree1.branch
        self.tree1.commit("message", rev_id=b"rev2a")
        bundle = self.get_valid_bundle(b"null:", b"rev2a")
        branch2 = self.make_branch("b2")
        self.assertFalse(branch2.repository.has_revision(b"rev2a"))
        target_revision = bundle.install_revisions(branch2.repository)
        self.assertTrue(branch2.repository.has_revision(b"rev2a"))
        self.assertEqual(b"rev2a", target_revision)

    def test_bundle_empty_property(self):
        """Test serializing revision properties with an empty value."""
        tree = self.make_branch_and_memory_tree("tree")
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.add([""], ids=[b"TREE_ROOT"])
        tree.commit("One", revprops={"one": "two", "empty": ""}, rev_id=b"rev1")
        self.b1 = tree.branch
        bundle_sio, revision_ids = self.create_bundle_text(b"null:", b"rev1")
        bundle = read_bundle(bundle_sio)
        revision_info = bundle.revisions[0]
        self.assertEqual(b"rev1", revision_info.revision_id)
        rev = revision_info.as_revision()
        self.assertEqual(
            {"branch-nick": "tree", "empty": "", "one": "two"}, rev.properties
        )

    def test_bundle_sorted_properties(self):
        """For stability the writer should write properties in sorted order."""
        tree = self.make_branch_and_memory_tree("tree")
        tree.lock_write()
        self.addCleanup(tree.unlock)

        tree.add([""], ids=[b"TREE_ROOT"])
        tree.commit(
            "One", rev_id=b"rev1", revprops={"a": "4", "b": "3", "c": "2", "d": "1"}
        )
        self.b1 = tree.branch
        bundle_sio, revision_ids = self.create_bundle_text(b"null:", b"rev1")
        bundle = read_bundle(bundle_sio)
        revision_info = bundle.revisions[0]
        self.assertEqual(b"rev1", revision_info.revision_id)
        rev = revision_info.as_revision()
        self.assertEqual(
            {"branch-nick": "tree", "a": "4", "b": "3", "c": "2", "d": "1"},
            rev.properties,
        )

    def test_bundle_unicode_properties(self):
        """We should be able to round trip a non-ascii property."""
        tree = self.make_branch_and_memory_tree("tree")
        tree.lock_write()
        self.addCleanup(tree.unlock)

        tree.add([""], ids=[b"TREE_ROOT"])
        # Revisions themselves do not require anything about revision property
        # keys, other than that they are a basestring, and do not contain
        # whitespace.
        # However, Testaments assert than they are str(), and thus should not
        # be Unicode.
        tree.commit(
            "One", rev_id=b"rev1", revprops={"omega": "\u03a9", "alpha": "\u03b1"}
        )
        self.b1 = tree.branch
        bundle_sio, revision_ids = self.create_bundle_text(b"null:", b"rev1")
        bundle = read_bundle(bundle_sio)
        revision_info = bundle.revisions[0]
        self.assertEqual(b"rev1", revision_info.revision_id)
        rev = revision_info.as_revision()
        self.assertEqual(
            {"branch-nick": "tree", "omega": "\u03a9", "alpha": "\u03b1"},
            rev.properties,
        )

    def test_bundle_with_ghosts(self):
        tree = self.make_branch_and_tree("tree")
        self.b1 = tree.branch
        self.build_tree_contents([("tree/file", b"content1")])
        tree.add(["file"])
        tree.commit("rev1")
        self.build_tree_contents([("tree/file", b"content2")])
        tree.add_parent_tree_id(b"ghost")
        tree.commit("rev2", rev_id=b"rev2")
        self.get_valid_bundle(b"null:", b"rev2")

    def make_simple_tree(self, format=None):
        tree = self.make_branch_and_tree("b1", format=format)
        self.b1 = tree.branch
        self.build_tree(["b1/file"])
        tree.add("file")
        return tree

    def test_across_serializers(self):
        tree = self.make_simple_tree("knit")
        tree.commit("hello", rev_id=b"rev1")
        tree.commit("hello", rev_id=b"rev2")
        bundle = read_bundle(self.create_bundle_text(b"null:", b"rev2")[0])
        repo = self.make_repository("repo", format="dirstate-with-subtree")
        bundle.install_revisions(repo)
        inv_text = b"".join(repo._get_inventory_xml(b"rev2"))
        self.assertNotContainsRe(inv_text, b'format="5"')
        self.assertContainsRe(inv_text, b'format="7"')

    def make_repo_with_installed_revisions(self):
        tree = self.make_simple_tree("knit")
        tree.commit("hello", rev_id=b"rev1")
        tree.commit("hello", rev_id=b"rev2")
        bundle = read_bundle(self.create_bundle_text(b"null:", b"rev2")[0])
        repo = self.make_repository("repo", format="dirstate-with-subtree")
        bundle.install_revisions(repo)
        return repo

    def test_across_models(self):
        repo = self.make_repo_with_installed_revisions()
        inv = repo.get_inventory(b"rev2")
        self.assertEqual(b"rev2", inv.root.revision)
        root_id = inv.root.file_id
        repo.lock_read()
        self.addCleanup(repo.unlock)
        self.assertEqual(
            {(root_id, b"rev1"): (), (root_id, b"rev2"): ((root_id, b"rev1"),)},
            repo.texts.get_parent_map([(root_id, b"rev1"), (root_id, b"rev2")]),
        )

    def test_inv_hash_across_serializers(self):
        repo = self.make_repo_with_installed_revisions()
        recorded_inv_sha1 = repo.get_revision(b"rev2").inventory_sha1
        xml = b"".join(repo._get_inventory_xml(b"rev2"))
        self.assertEqual(osutils.sha_string(xml), recorded_inv_sha1)

    def test_across_models_incompatible(self):
        tree = self.make_simple_tree("dirstate-with-subtree")
        tree.commit("hello", rev_id=b"rev1")
        tree.commit("hello", rev_id=b"rev2")
        try:
            bundle = read_bundle(self.create_bundle_text(b"null:", b"rev1")[0])
        except errors.IncompatibleBundleFormat as e:
            raise tests.TestSkipped("Format 0.8 doesn't work with knit3") from e
        repo = self.make_repository("repo", format="knit")
        bundle.install_revisions(repo)

        bundle = read_bundle(self.create_bundle_text(b"null:", b"rev2")[0])
        self.assertRaises(errors.IncompatibleRevision, bundle.install_revisions, repo)

    def test_get_merge_request(self):
        tree = self.make_simple_tree()
        tree.commit("hello", rev_id=b"rev1")
        tree.commit("hello", rev_id=b"rev2")
        bundle = read_bundle(self.create_bundle_text(b"null:", b"rev1")[0])
        result = bundle.get_merge_request(tree.branch.repository)
        self.assertEqual((None, b"rev1", "inapplicable"), result)

    def test_with_subtree(self):
        tree = self.make_branch_and_tree("tree", format="dirstate-with-subtree")
        self.b1 = tree.branch
        self.make_branch_and_tree("tree/subtree", format="dirstate-with-subtree")
        tree.add("subtree")
        tree.commit("hello", rev_id=b"rev1")
        try:
            bundle = read_bundle(self.create_bundle_text(b"null:", b"rev1")[0])
        except errors.IncompatibleBundleFormat as e:
            raise tests.TestSkipped("Format 0.8 doesn't work with knit3") from e
        if isinstance(bundle, v09.BundleInfo09):
            raise tests.TestSkipped("Format 0.9 doesn't work with subtrees")
        repo = self.make_repository("repo", format="knit")
        self.assertRaises(errors.IncompatibleRevision, bundle.install_revisions, repo)
        repo2 = self.make_repository("repo2", format="dirstate-with-subtree")
        bundle.install_revisions(repo2)

    def test_revision_id_with_slash(self):
        self.tree1 = self.make_branch_and_tree("tree")
        self.b1 = self.tree1.branch
        try:
            self.tree1.commit("Revision/id/with/slashes", rev_id=b"rev/id")
        except ValueError as e:
            raise tests.TestSkipped(
                "Repository doesn't support revision ids with slashes"
            ) from e
        self.get_valid_bundle(b"null:", b"rev/id")

    def test_skip_file(self):
        """Make sure we don't accidentally write to the wrong versionedfile."""
        self.tree1 = self.make_branch_and_tree("tree")
        self.b1 = self.tree1.branch
        # rev1 is not present in bundle, done by fetch
        self.build_tree_contents([("tree/file2", b"contents1")])
        self.tree1.add("file2", ids=b"file2-id")
        self.tree1.commit("rev1", rev_id=b"reva")
        self.build_tree_contents([("tree/file3", b"contents2")])
        # rev2 is present in bundle, and done by fetch
        # having file1 in the bunle causes file1's versionedfile to be opened.
        self.tree1.add("file3", ids=b"file3-id")
        rev2 = self.tree1.commit("rev2")
        # Updating file2 should not cause an attempt to add to file1's vf
        target = self.tree1.controldir.sprout("target").open_workingtree()
        self.build_tree_contents([("tree/file2", b"contents3")])
        self.tree1.commit("rev3", rev_id=b"rev3")
        bundle = self.get_valid_bundle(b"reva", b"rev3")
        if getattr(bundle, "get_bundle_reader", None) is None:
            raise tests.TestSkipped("Bundle format cannot provide reader")
        file_ids = {
            (f, r)
            for b, m, k, r, f in bundle.get_bundle_reader().iter_records()
            if f is not None
        }
        self.assertEqual({(b"file2-id", b"rev3"), (b"file3-id", rev2)}, file_ids)
        bundle.install_revisions(target.branch.repository)


class V08BundleTester(BundleTester, tests.TestCaseWithTransport):
    format = "0.8"

    def test_bundle_empty_property(self):
        """Test serializing revision properties with an empty value."""
        tree = self.make_branch_and_memory_tree("tree")
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.add([""], ids=[b"TREE_ROOT"])
        tree.commit("One", revprops={"one": "two", "empty": ""}, rev_id=b"rev1")
        self.b1 = tree.branch
        bundle_sio, revision_ids = self.create_bundle_text(b"null:", b"rev1")
        self.assertContainsRe(
            bundle_sio.getvalue(),
            b"# properties:\n#   branch-nick: tree\n#   empty: \n#   one: two\n",
        )
        bundle = read_bundle(bundle_sio)
        revision_info = bundle.revisions[0]
        self.assertEqual(b"rev1", revision_info.revision_id)
        rev = revision_info.as_revision()
        self.assertEqual(
            {"branch-nick": "tree", "empty": "", "one": "two"}, rev.properties
        )

    def get_bundle_tree(self, bundle, revision_id):
        repository = self.make_repository("repo")
        return bundle.revision_tree(repository, b"revid1")

    def test_bundle_empty_property_alt(self):
        r"""Test serializing revision properties with an empty value.

        Older readers had a bug when reading an empty property.
        They assumed that all keys ended in ': \n'. However they would write an
        empty value as ':\n'. This tests make sure that all newer bzr versions
        can handle th second form.
        """
        tree = self.make_branch_and_memory_tree("tree")
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.add([""], ids=[b"TREE_ROOT"])
        tree.commit("One", revprops={"one": "two", "empty": ""}, rev_id=b"rev1")
        self.b1 = tree.branch
        bundle_sio, revision_ids = self.create_bundle_text(b"null:", b"rev1")
        txt = bundle_sio.getvalue()
        loc = txt.find(b"#   empty: ") + len(b"#   empty:")
        # Create a new bundle, which strips the trailing space after empty
        bundle_sio = BytesIO(txt[:loc] + txt[loc + 1 :])

        self.assertContainsRe(
            bundle_sio.getvalue(),
            b"# properties:\n#   branch-nick: tree\n#   empty:\n#   one: two\n",
        )
        bundle = read_bundle(bundle_sio)
        revision_info = bundle.revisions[0]
        self.assertEqual(b"rev1", revision_info.revision_id)
        rev = revision_info.as_revision()
        self.assertEqual(
            {"branch-nick": "tree", "empty": "", "one": "two"}, rev.properties
        )

    def test_bundle_sorted_properties(self):
        """For stability the writer should write properties in sorted order."""
        tree = self.make_branch_and_memory_tree("tree")
        tree.lock_write()
        self.addCleanup(tree.unlock)

        tree.add([""], ids=[b"TREE_ROOT"])
        tree.commit(
            "One", rev_id=b"rev1", revprops={"a": "4", "b": "3", "c": "2", "d": "1"}
        )
        self.b1 = tree.branch
        bundle_sio, revision_ids = self.create_bundle_text(b"null:", b"rev1")
        self.assertContainsRe(
            bundle_sio.getvalue(),
            b"# properties:\n"
            b"#   a: 4\n"
            b"#   b: 3\n"
            b"#   branch-nick: tree\n"
            b"#   c: 2\n"
            b"#   d: 1\n",
        )
        bundle = read_bundle(bundle_sio)
        revision_info = bundle.revisions[0]
        self.assertEqual(b"rev1", revision_info.revision_id)
        rev = revision_info.as_revision()
        self.assertEqual(
            {"branch-nick": "tree", "a": "4", "b": "3", "c": "2", "d": "1"},
            rev.properties,
        )

    def test_bundle_unicode_properties(self):
        """We should be able to round trip a non-ascii property."""
        tree = self.make_branch_and_memory_tree("tree")
        tree.lock_write()
        self.addCleanup(tree.unlock)

        tree.add([""], ids=[b"TREE_ROOT"])
        # Revisions themselves do not require anything about revision property
        # keys, other than that they are a basestring, and do not contain
        # whitespace.
        # However, Testaments assert than they are str(), and thus should not
        # be Unicode.
        tree.commit(
            "One", rev_id=b"rev1", revprops={"omega": "\u03a9", "alpha": "\u03b1"}
        )
        self.b1 = tree.branch
        bundle_sio, revision_ids = self.create_bundle_text(b"null:", b"rev1")
        self.assertContainsRe(
            bundle_sio.getvalue(),
            b"# properties:\n"
            b"#   alpha: \xce\xb1\n"
            b"#   branch-nick: tree\n"
            b"#   omega: \xce\xa9\n",
        )
        bundle = read_bundle(bundle_sio)
        revision_info = bundle.revisions[0]
        self.assertEqual(b"rev1", revision_info.revision_id)
        rev = revision_info.as_revision()
        self.assertEqual(
            {"branch-nick": "tree", "omega": "\u03a9", "alpha": "\u03b1"},
            rev.properties,
        )


class V09BundleKnit2Tester(V08BundleTester):
    format = "0.9"

    def bzrdir_format(self):
        format = bzrdir.BzrDirMetaFormat1()
        format.repository_format = knitrepo.RepositoryFormatKnit3()
        return format


class V09BundleKnit1Tester(V08BundleTester):
    format = "0.9"

    def bzrdir_format(self):
        format = bzrdir.BzrDirMetaFormat1()
        format.repository_format = knitrepo.RepositoryFormatKnit1()
        return format


class V4BundleTester(BundleTester, tests.TestCaseWithTransport):
    format = "4"

    def get_valid_bundle(self, base_rev_id, rev_id, checkout_dir=None):
        """Create a bundle from base_rev_id -> rev_id in built-in branch.
        Make sure that the text generated is valid, and that it
        can be applied against the base, and generate the same information.

        :return: The in-memory bundle
        """
        bundle_txt, rev_ids = self.create_bundle_text(base_rev_id, rev_id)

        # This should also validate the generated bundle
        bundle = read_bundle(bundle_txt)
        repository = self.b1.repository
        for bundle_rev in bundle.real_revisions:
            # These really should have already been checked when we read the
            # bundle, since it computes the sha1 hash for the revision, which
            # only will match if everything is okay, but lets be explicit about
            # it
            branch_rev = repository.get_revision(bundle_rev.revision_id)
            for a in (
                "inventory_sha1",
                "revision_id",
                "parent_ids",
                "timestamp",
                "timezone",
                "message",
                "committer",
                "parent_ids",
                "properties",
            ):
                self.assertEqual(getattr(branch_rev, a), getattr(bundle_rev, a))
            self.assertEqual(len(branch_rev.parent_ids), len(bundle_rev.parent_ids))
        self.assertEqual(set(rev_ids), {r.revision_id for r in bundle.real_revisions})
        self.valid_apply_bundle(base_rev_id, bundle, checkout_dir=checkout_dir)

        return bundle

    def get_invalid_bundle(self, base_rev_id, rev_id):
        """Create a bundle from base_rev_id -> rev_id in built-in branch.
        Munge the text so that it's invalid.

        :return: The in-memory bundle
        """
        from ..bundle import serializer

        bundle_txt, rev_ids = self.create_bundle_text(base_rev_id, rev_id)
        new_text = self.get_raw(BytesIO(b"".join(bundle_txt)))
        new_text = new_text.replace(
            b'<file file_id="exe-1"', b'<file executable="y" file_id="exe-1"'
        )
        new_text = new_text.replace(b"B260", b"B275")
        bundle_txt = BytesIO()
        bundle_txt.write(serializer._get_bundle_header("4"))
        bundle_txt.write(b"\n")
        bundle_txt.write(bz2.compress(new_text))
        bundle_txt.seek(0)
        bundle = read_bundle(bundle_txt)
        self.valid_apply_bundle(base_rev_id, bundle)
        return bundle

    def create_bundle_text(self, base_rev_id, rev_id):
        bundle_txt = BytesIO()
        rev_ids = write_bundle(
            self.b1.repository, rev_id, base_rev_id, bundle_txt, format=self.format
        )
        bundle_txt.seek(0)
        self.assertEqual(
            bundle_txt.readline(),
            b"# Bazaar revision bundle v%s\n" % self.format.encode("ascii"),
        )
        self.assertEqual(bundle_txt.readline(), b"#\n")
        self.b1.repository.get_revision(rev_id)
        bundle_txt.seek(0)
        return bundle_txt, rev_ids

    def get_bundle_tree(self, bundle, revision_id):
        repository = self.make_repository("repo")
        bundle.install_revisions(repository)
        return repository.revision_tree(revision_id)

    def test_creation(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree_contents([("tree/file", b"contents1\nstatic\n")])
        tree.add("file", ids=b"fileid-2")
        tree.commit("added file", rev_id=b"rev1")
        self.build_tree_contents([("tree/file", b"contents2\nstatic\n")])
        tree.commit("changed file", rev_id=b"rev2")
        s = BytesIO()
        serializer = BundleSerializerV4("1.0")
        with tree.lock_read():
            serializer.write_bundle(tree.branch.repository, b"rev2", b"null:", s)
        s.seek(0)
        tree2 = self.make_branch_and_tree("target")
        target_repo = tree2.branch.repository
        install_bundle(target_repo, serializer.read(s))
        target_repo.lock_read()
        self.addCleanup(target_repo.unlock)
        # Turn the 'iterators_of_bytes' back into simple strings for comparison
        repo_texts = {
            i: b"".join(content)
            for i, content in target_repo.iter_files_bytes(
                [(b"fileid-2", b"rev1", "1"), (b"fileid-2", b"rev2", "2")]
            )
        }
        self.assertEqual(
            {"1": b"contents1\nstatic\n", "2": b"contents2\nstatic\n"}, repo_texts
        )
        target_repo.revision_tree(b"rev2")
        inventory_vf = target_repo.inventories
        # If the inventory store has a graph, it must match the revision graph.
        self.assertSubset(
            [inventory_vf.get_parent_map([(b"rev2",)])[(b"rev2",)]],
            [None, ((b"rev1",),)],
        )
        self.assertEqual("changed file", target_repo.get_revision(b"rev2").message)

    @staticmethod
    def get_raw(bundle_file):
        bundle_file.seek(0)
        bundle_file.readline()
        bundle_file.readline()
        lines = bundle_file.readlines()
        return bz2.decompress(b"".join(lines))

    def test_copy_signatures(self):
        tree_a = self.make_branch_and_tree("tree_a")
        import breezy.commit as commit
        import breezy.gpg

        oldstrategy = breezy.gpg.GPGStrategy
        branch = tree_a.branch
        repo_a = branch.repository
        tree_a.commit("base", allow_pointless=True, rev_id=b"A")
        self.assertFalse(branch.repository.has_signature_for_revision_id(b"A"))
        try:
            # monkey patch gpg signing mechanism
            breezy.gpg.GPGStrategy = breezy.gpg.LoopbackGPGStrategy
            new_config = test_commit.MustSignConfig()
            commit.Commit(config_stack=new_config).commit(
                message="base", allow_pointless=True, rev_id=b"B", working_tree=tree_a
            )

            def sign(text):
                return breezy.gpg.LoopbackGPGStrategy(None).sign(text)

            self.assertTrue(repo_a.has_signature_for_revision_id(b"B"))
        finally:
            breezy.gpg.GPGStrategy = oldstrategy
        tree_b = self.make_branch_and_tree("tree_b")
        repo_b = tree_b.branch.repository
        s = BytesIO()
        serializer = BundleSerializerV4("4")
        with tree_a.lock_read():
            serializer.write_bundle(tree_a.branch.repository, b"B", b"null:", s)
        s.seek(0)
        install_bundle(repo_b, serializer.read(s))
        self.assertTrue(repo_b.has_signature_for_revision_id(b"B"))
        self.assertEqual(
            repo_b.get_signature_text(b"B"), repo_a.get_signature_text(b"B")
        )
        s.seek(0)
        # ensure repeat installs are harmless
        install_bundle(repo_b, serializer.read(s))


class V4_2aBundleTester(V4BundleTester):
    def bzrdir_format(self):
        return "2a"

    def get_invalid_bundle(self, base_rev_id, rev_id):
        """Create a bundle from base_rev_id -> rev_id in built-in branch.
        Munge the text so that it's invalid.

        :return: The in-memory bundle
        """
        from ..bundle import serializer

        bundle_txt, rev_ids = self.create_bundle_text(base_rev_id, rev_id)
        new_text = self.get_raw(BytesIO(b"".join(bundle_txt)))
        # We are going to be replacing some text to set the executable bit on a
        # file. Make sure the text replacement actually works correctly.
        self.assertContainsRe(new_text, b"(?m)B244\n\ni 1\n<inventory")
        new_text = new_text.replace(
            b'<file file_id="exe-1"', b'<file executable="y" file_id="exe-1"'
        )
        new_text = new_text.replace(b"B244", b"B259")
        bundle_txt = BytesIO()
        bundle_txt.write(serializer._get_bundle_header("4"))
        bundle_txt.write(b"\n")
        bundle_txt.write(bz2.compress(new_text))
        bundle_txt.seek(0)
        bundle = read_bundle(bundle_txt)
        self.valid_apply_bundle(base_rev_id, bundle)
        return bundle

    def make_merged_branch(self):
        builder = self.make_branch_builder("source")
        builder.start_series()
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"root-id", "directory", None)),
                ("add", ("file", b"file-id", "file", b"original content\n")),
            ],
            revision_id=b"a@cset-0-1",
        )
        builder.build_snapshot(
            [b"a@cset-0-1"],
            [
                ("modify", ("file", b"new-content\n")),
            ],
            revision_id=b"a@cset-0-2a",
        )
        builder.build_snapshot(
            [b"a@cset-0-1"],
            [
                ("add", ("other-file", b"file2-id", "file", b"file2-content\n")),
            ],
            revision_id=b"a@cset-0-2b",
        )
        builder.build_snapshot(
            [b"a@cset-0-2a", b"a@cset-0-2b"],
            [
                ("add", ("other-file", b"file2-id", "file", b"file2-content\n")),
            ],
            revision_id=b"a@cset-0-3",
        )
        builder.finish_series()
        self.b1 = builder.get_branch()
        self.b1.lock_read()
        self.addCleanup(self.b1.unlock)

    def make_bundle_just_inventories(
        self, base_revision_id, target_revision_id, revision_ids
    ):
        sio = BytesIO()
        writer = v4.BundleWriteOperation(
            base_revision_id, target_revision_id, self.b1.repository, sio
        )
        writer.bundle.begin()
        writer._add_inventory_mpdiffs_from_serializer(revision_ids)
        writer.bundle.end()
        sio.seek(0)
        return sio

    def test_single_inventory_multiple_parents_as_xml(self):
        self.make_merged_branch()
        sio = self.make_bundle_just_inventories(
            b"a@cset-0-1", b"a@cset-0-3", [b"a@cset-0-3"]
        )
        reader = v4.BundleReader(sio, stream_input=False)
        records = list(reader.iter_records())
        self.assertEqual(1, len(records))
        (bytes, metadata, repo_kind, revision_id, file_id) = records[0]
        self.assertIs(None, file_id)
        self.assertEqual(b"a@cset-0-3", revision_id)
        self.assertEqual("inventory", repo_kind)
        self.assertEqual(
            {
                b"parents": [b"a@cset-0-2a", b"a@cset-0-2b"],
                b"sha1": b"09c53b0c4de0895e11a2aacc34fef60a6e70865c",
                b"storage_kind": b"mpdiff",
            },
            metadata,
        )
        # We should have an mpdiff that takes some lines from both parents.
        self.assertEqualDiff(
            b"i 1\n"
            b'<inventory format="10" revision_id="a@cset-0-3">\n'
            b"\n"
            b"c 0 1 1 2\n"
            b"c 1 3 3 2\n",
            bytes,
        )

    def test_single_inv_no_parents_as_xml(self):
        self.make_merged_branch()
        sio = self.make_bundle_just_inventories(
            b"null:", b"a@cset-0-1", [b"a@cset-0-1"]
        )
        reader = v4.BundleReader(sio, stream_input=False)
        records = list(reader.iter_records())
        self.assertEqual(1, len(records))
        (bytes, metadata, repo_kind, revision_id, file_id) = records[0]
        self.assertIs(None, file_id)
        self.assertEqual(b"a@cset-0-1", revision_id)
        self.assertEqual("inventory", repo_kind)
        self.assertEqual(
            {
                b"parents": [],
                b"sha1": b"a13f42b142d544aac9b085c42595d304150e31a2",
                b"storage_kind": b"mpdiff",
            },
            metadata,
        )
        # We should have an mpdiff that takes some lines from both parents.
        self.assertEqualDiff(
            b"i 4\n"
            b'<inventory format="10" revision_id="a@cset-0-1">\n'
            b'<directory file_id="root-id" name=""'
            b' revision="a@cset-0-1" />\n'
            b'<file file_id="file-id" name="file" parent_id="root-id"'
            b' revision="a@cset-0-1"'
            b' text_sha1="09c2f8647e14e49e922b955c194102070597c2d1"'
            b' text_size="17" />\n'
            b"</inventory>\n"
            b"\n",
            bytes,
        )

    def test_multiple_inventories_as_xml(self):
        self.make_merged_branch()
        sio = self.make_bundle_just_inventories(
            b"a@cset-0-1",
            b"a@cset-0-3",
            [b"a@cset-0-2a", b"a@cset-0-2b", b"a@cset-0-3"],
        )
        reader = v4.BundleReader(sio, stream_input=False)
        records = list(reader.iter_records())
        self.assertEqual(3, len(records))
        revision_ids = [rev_id for b, m, k, rev_id, f in records]
        self.assertEqual([b"a@cset-0-2a", b"a@cset-0-2b", b"a@cset-0-3"], revision_ids)
        metadata_2a = records[0][1]
        self.assertEqual(
            {
                b"parents": [b"a@cset-0-1"],
                b"sha1": b"1e105886d62d510763e22885eec733b66f5f09bf",
                b"storage_kind": b"mpdiff",
            },
            metadata_2a,
        )
        metadata_2b = records[1][1]
        self.assertEqual(
            {
                b"parents": [b"a@cset-0-1"],
                b"sha1": b"f03f12574bdb5ed2204c28636c98a8547544ccd8",
                b"storage_kind": b"mpdiff",
            },
            metadata_2b,
        )
        metadata_3 = records[2][1]
        self.assertEqual(
            {
                b"parents": [b"a@cset-0-2a", b"a@cset-0-2b"],
                b"sha1": b"09c53b0c4de0895e11a2aacc34fef60a6e70865c",
                b"storage_kind": b"mpdiff",
            },
            metadata_3,
        )
        bytes_2a = records[0][0]
        self.assertEqualDiff(
            b"i 1\n"
            b'<inventory format="10" revision_id="a@cset-0-2a">\n'
            b"\n"
            b"c 0 1 1 1\n"
            b"i 1\n"
            b'<file file_id="file-id" name="file" parent_id="root-id"'
            b' revision="a@cset-0-2a"'
            b' text_sha1="50f545ff40e57b6924b1f3174b267ffc4576e9a9"'
            b' text_size="12" />\n'
            b"\n"
            b"c 0 3 3 1\n",
            bytes_2a,
        )
        bytes_2b = records[1][0]
        self.assertEqualDiff(
            b"i 1\n"
            b'<inventory format="10" revision_id="a@cset-0-2b">\n'
            b"\n"
            b"c 0 1 1 2\n"
            b"i 1\n"
            b'<file file_id="file2-id" name="other-file" parent_id="root-id"'
            b' revision="a@cset-0-2b"'
            b' text_sha1="b46c0c8ea1e5ef8e46fc8894bfd4752a88ec939e"'
            b' text_size="14" />\n'
            b"\n"
            b"c 0 3 4 1\n",
            bytes_2b,
        )
        bytes_3 = records[2][0]
        self.assertEqualDiff(
            b"i 1\n"
            b'<inventory format="10" revision_id="a@cset-0-3">\n'
            b"\n"
            b"c 0 1 1 2\n"
            b"c 1 3 3 2\n",
            bytes_3,
        )

    def test_creating_bundle_preserves_chk_pages(self):
        self.make_merged_branch()
        target = self.b1.controldir.sprout(
            "target", revision_id=b"a@cset-0-2a"
        ).open_branch()
        bundle_txt, rev_ids = self.create_bundle_text(b"a@cset-0-2a", b"a@cset-0-3")
        self.assertEqual({b"a@cset-0-2b", b"a@cset-0-3"}, set(rev_ids))
        bundle = read_bundle(bundle_txt)
        target.lock_write()
        self.addCleanup(target.unlock)
        install_bundle(target.repository, bundle)
        inv1 = next(
            self.b1.repository.inventories.get_record_stream(
                [(b"a@cset-0-3",)], "unordered", True
            )
        ).get_bytes_as("fulltext")
        inv2 = next(
            target.repository.inventories.get_record_stream(
                [(b"a@cset-0-3",)], "unordered", True
            )
        ).get_bytes_as("fulltext")
        self.assertEqualDiff(inv1, inv2)


class MungedBundleTester:
    def build_test_bundle(self):
        wt = self.make_branch_and_tree("b1")

        self.build_tree(["b1/one"])
        wt.add("one")
        wt.commit("add one", rev_id=b"a@cset-0-1")
        self.build_tree(["b1/two"])
        wt.add("two")
        wt.commit("add two", rev_id=b"a@cset-0-2", revprops={"branch-nick": "test"})

        bundle_txt = BytesIO()
        rev_ids = write_bundle(
            wt.branch.repository, b"a@cset-0-2", b"a@cset-0-1", bundle_txt, self.format
        )
        self.assertEqual({b"a@cset-0-2"}, set(rev_ids))
        bundle_txt.seek(0, 0)
        return bundle_txt

    def check_valid(self, bundle):
        """Check that after whatever munging, the final object is valid."""
        self.assertEqual(
            [b"a@cset-0-2"], [r.revision_id for r in bundle.real_revisions]
        )

    def test_extra_whitespace(self):
        bundle_txt = self.build_test_bundle()

        # Seek to the end of the file
        # Adding one extra newline used to give us
        # TypeError: float() argument must be a string or a number
        bundle_txt.seek(0, 2)
        bundle_txt.write(b"\n")
        bundle_txt.seek(0)

        bundle = read_bundle(bundle_txt)
        self.check_valid(bundle)

    def test_extra_whitespace_2(self):
        bundle_txt = self.build_test_bundle()

        # Seek to the end of the file
        # Adding two extra newlines used to give us
        # MalformedPatches: The first line of all patches should be ...
        bundle_txt.seek(0, 2)
        bundle_txt.write(b"\n\n")
        bundle_txt.seek(0)

        bundle = read_bundle(bundle_txt)
        self.check_valid(bundle)


class MungedBundleTesterV09(tests.TestCaseWithTransport, MungedBundleTester):
    format = "0.9"

    def test_missing_trailing_whitespace(self):
        bundle_txt = self.build_test_bundle()

        # Remove a trailing newline, it shouldn't kill the parser
        raw = bundle_txt.getvalue()
        # The contents of the bundle don't have to be this, but this
        # test is concerned with the exact case where the serializer
        # creates a blank line at the end, and fails if that
        # line is stripped
        self.assertEqual(b"\n\n", raw[-2:])
        bundle_txt = BytesIO(raw[:-1])

        bundle = read_bundle(bundle_txt)
        self.check_valid(bundle)

    def test_opening_text(self):
        bundle_txt = self.build_test_bundle()

        bundle_txt = BytesIO(b"Some random\nemail comments\n" + bundle_txt.getvalue())

        bundle = read_bundle(bundle_txt)
        self.check_valid(bundle)

    def test_trailing_text(self):
        bundle_txt = self.build_test_bundle()

        bundle_txt = BytesIO(bundle_txt.getvalue() + b"Some trailing\nrandom\ntext\n")

        bundle = read_bundle(bundle_txt)
        self.check_valid(bundle)


class MungedBundleTesterV4(tests.TestCaseWithTransport, MungedBundleTester):
    format = "4"


class TestBundleWriterReader(tests.TestCase):
    def test_roundtrip_record(self):
        fileobj = BytesIO()
        writer = v4.BundleWriter(fileobj)
        writer.begin()
        writer.add_info_record({b"foo": b"bar"})
        writer._add_record(
            b"Record body",
            {b"parents": [b"1", b"3"], b"storage_kind": b"fulltext"},
            "file",
            b"revid",
            b"fileid",
        )
        writer.end()
        fileobj.seek(0)
        reader = v4.BundleReader(fileobj, stream_input=True)
        record_iter = reader.iter_records()
        record = next(record_iter)
        self.assertEqual(
            (None, {b"foo": b"bar", b"storage_kind": b"header"}, "info", None, None),
            record,
        )
        record = next(record_iter)
        self.assertEqual(
            (
                b"Record body",
                {b"storage_kind": b"fulltext", b"parents": [b"1", b"3"]},
                "file",
                b"revid",
                b"fileid",
            ),
            record,
        )

    def test_roundtrip_record_memory_hungry(self):
        fileobj = BytesIO()
        writer = v4.BundleWriter(fileobj)
        writer.begin()
        writer.add_info_record({b"foo": b"bar"})
        writer._add_record(
            b"Record body",
            {b"parents": [b"1", b"3"], b"storage_kind": b"fulltext"},
            "file",
            b"revid",
            b"fileid",
        )
        writer.end()
        fileobj.seek(0)
        reader = v4.BundleReader(fileobj, stream_input=False)
        record_iter = reader.iter_records()
        record = next(record_iter)
        self.assertEqual(
            (None, {b"foo": b"bar", b"storage_kind": b"header"}, "info", None, None),
            record,
        )
        record = next(record_iter)
        self.assertEqual(
            (
                b"Record body",
                {b"storage_kind": b"fulltext", b"parents": [b"1", b"3"]},
                "file",
                b"revid",
                b"fileid",
            ),
            record,
        )

    def test_encode_name(self):
        self.assertEqual(
            b"revision/rev1", v4.BundleWriter.encode_name("revision", b"rev1")
        )
        self.assertEqual(
            b"file/rev//1/file-id-1",
            v4.BundleWriter.encode_name("file", b"rev/1", b"file-id-1"),
        )
        self.assertEqual(b"info", v4.BundleWriter.encode_name("info", None, None))

    def test_decode_name(self):
        self.assertEqual(
            ("revision", b"rev1", None), v4.BundleReader.decode_name(b"revision/rev1")
        )
        self.assertEqual(
            ("file", b"rev/1", b"file-id-1"),
            v4.BundleReader.decode_name(b"file/rev//1/file-id-1"),
        )
        self.assertEqual(("info", None, None), v4.BundleReader.decode_name(b"info"))

    def test_too_many_names(self):
        fileobj = BytesIO()
        writer = v4.BundleWriter(fileobj)
        writer.begin()
        writer.add_info_record({b"foo": b"bar"})
        writer._container.add_bytes_record(
            [b"blah"], len(b"blah"), [(b"two",), (b"names",)]
        )
        writer.end()
        fileobj.seek(0)
        record_iter = v4.BundleReader(fileobj).iter_records()
        record = next(record_iter)
        self.assertEqual(
            (None, {b"foo": b"bar", b"storage_kind": b"header"}, "info", None, None),
            record,
        )
        self.assertRaises(errors.BadBundle, next, record_iter)
