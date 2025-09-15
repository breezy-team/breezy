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

import os
import sys
import tempfile

from .. import controldir, errors, merge_directive, osutils
from ..bzr import generate_ids
from ..bzr.conflicts import ContentsConflict, PathConflict, TextConflict
from ..merge import Diff3Merger, Merge3Merger, Merger, WeaveMerger
from ..osutils import getcwd, pathjoin
from ..workingtree import WorkingTree
from . import TestCaseWithTransport, TestSkipped


class MergeBuilder:
    def __init__(self, dir=None):
        self.dir = tempfile.mkdtemp(prefix="merge-test", dir=dir)
        self.tree_root = generate_ids.gen_root_id()

        def wt(name):
            path = pathjoin(self.dir, name)
            os.mkdir(path)
            wt = controldir.ControlDir.create_standalone_workingtree(path)
            # the tests perform pulls, so need a branch that is writeable.
            wt.lock_write()
            if wt.supports_file_ids:
                wt.set_root_id(self.tree_root)
            wt.flush()
            tt = wt.transform()
            return wt, tt

        self.base, self.base_tt = wt("base")
        self.this, self.this_tt = wt("this")
        self.other, self.other_tt = wt("other")

    def root(self):
        ret = []
        for tt in [self.this_tt, self.base_tt, self.other_tt]:
            ret.append(tt.trans_id_tree_path(""))
        return tuple(ret)

    def get_cset_path(self, parent, name):
        if name is None:
            if parent is not None:
                raise AssertionError()
            return None
        return pathjoin(self.cset.entries[parent].path, name)

    def add_file(
        self,
        parent,
        name,
        contents,
        executable,
        this=True,
        base=True,
        other=True,
        file_id=None,
    ):
        ret = []
        for i, (option, tt) in enumerate(self.selected_transforms(this, base, other)):
            if option is True:
                trans_id = tt.new_file(
                    name, parent[i], [contents], executable=executable, file_id=file_id
                )
            else:
                trans_id = None
            ret.append(trans_id)
        return tuple(ret)

    def merge(self, merge_type=Merge3Merger, interesting_files=None, **kwargs):
        merger = self.make_merger(merge_type, interesting_files, **kwargs)
        merger.do_merge()
        return merger.cooked_conflicts

    def make_preview_transform(self):
        merger = self.make_merger(Merge3Merger, None, this_revision_tree=True)
        return merger.make_preview_transform()

    def make_merger(
        self, merge_type, interesting_files, this_revision_tree=False, **kwargs
    ):
        self.base_tt.apply()
        self.base.commit("base commit")
        for tt, wt in ((self.this_tt, self.this), (self.other_tt, self.other)):
            # why does this not do wt.pull() ?
            wt.branch.pull(self.base.branch)
            wt.set_parent_ids([wt.branch.last_revision()])
            wt.flush()
            # We maintain a write lock, so make sure changes are flushed to
            # disk first
            tt.apply()
            wt.commit("branch commit")
            wt.flush()
            if wt.branch.last_revision_info()[0] != 2:
                raise AssertionError()
        self.this.branch.fetch(self.other.branch)
        other_basis = self.other.branch.basis_tree()
        if this_revision_tree:
            self.this.commit("message")
            this_tree = self.this.basis_tree()
        else:
            this_tree = self.this
        merger = merge_type(
            this_tree,
            self.this,
            self.base,
            other_basis,
            interesting_files=interesting_files,
            do_merge=False,
            this_branch=self.this.branch,
            **kwargs,
        )
        return merger

    def list_transforms(self):
        return [self.this_tt, self.base_tt, self.other_tt]

    def selected_transforms(self, this, base, other):
        pairs = [(this, self.this_tt), (base, self.base_tt), (other, self.other_tt)]
        return [(v, tt) for (v, tt) in pairs if v is not None]

    def add_symlink(self, parent, name, contents, file_id=None):
        ret = []
        for i, tt in enumerate(self.list_transforms()):
            trans_id = tt.new_symlink(name, parent[i], contents, file_id=file_id)
            ret.append(trans_id)
        return ret

    def remove_file(self, trans_ids, base=False, this=False, other=False):
        for trans_id, (option, tt) in zip(
            trans_ids, self.selected_transforms(this, base, other)
        ):
            if option is True:
                tt.cancel_creation(trans_id)
                tt.cancel_versioning(trans_id)
                tt.set_executability(None, trans_id)

    def add_dir(self, parent, name, this=True, base=True, other=True, file_id=None):
        ret = []
        for i, (option, tt) in enumerate(self.selected_transforms(this, base, other)):
            if option is True:
                trans_id = tt.new_directory(name, parent[i], file_id)
            else:
                trans_id = None
            ret.append(trans_id)
        return tuple(ret)

    def change_name(self, trans_ids, base=None, this=None, other=None):
        for val, tt, trans_id in (
            (base, self.base_tt, trans_ids[0]),
            (this, self.this_tt, trans_ids[1]),
            (other, self.other_tt, trans_ids[2]),
        ):
            if val is None:
                continue
            parent_id = tt.final_parent(trans_id)
            tt.adjust_path(val, parent_id, trans_id)

    def change_parent(self, trans_ids, base=None, this=None, other=None):
        for trans_id, (parent, tt) in zip(
            trans_ids, self.selected_transforms(this, base, other)
        ):
            parent_id = tt.trans_id_file_id(parent)
            tt.adjust_path(tt.final_name(trans_id), parent_id, trans_id)

    def change_contents(self, trans_id, base=None, this=None, other=None):
        for trans_id, (contents, tt) in zip(  # noqa: B020
            trans_id, self.selected_transforms(this, base, other)
        ):
            tt.cancel_creation(trans_id)
            tt.create_file([contents], trans_id)

    def change_target(self, trans_ids, base=None, this=None, other=None):
        for trans_id, (target, tt) in zip(
            trans_ids, self.selected_transforms(this, base, other)
        ):
            tt.cancel_creation(trans_id)
            tt.create_symlink(target, trans_id)

    def change_perms(self, trans_ids, base=None, this=None, other=None):
        for trans_id, (executability, tt) in zip(
            trans_ids, self.selected_transforms(this, base, other)
        ):
            tt.set_executability(None, trans_id)
            tt.set_executability(executability, trans_id)

    def apply_inv_change(self, inventory_change, orig_inventory):
        orig_inventory_by_path = {}
        for file_id, path in orig_inventory.items():
            orig_inventory_by_path[path] = file_id

        def parent_id(file_id):
            try:
                parent_dir = os.path.dirname(orig_inventory[file_id])
            except:
                print(file_id)
                raise
            if parent_dir == "":
                return None
            return orig_inventory_by_path[parent_dir]

        def new_path(file_id):
            if fild_id in inventory_change:
                return inventory_change[file_id]
            else:
                parent = parent_id(file_id)
                if parent is None:
                    return orig_inventory[file_id]
                dirname = new_path(parent)
                return pathjoin(dirname, os.path.basename(orig_inventory[file_id]))

        new_inventory = {}
        for file_id in orig_inventory:
            path = new_path(file_id)
            if path is None:
                continue
            new_inventory[file_id] = path

        for file_id, path in inventory_change.items():
            if file_id in orig_inventory:
                continue
            new_inventory[file_id] = path
        return new_inventory

    def unlock(self):
        self.base.unlock()
        self.this.unlock()
        self.other.unlock()

    def cleanup(self):
        self.unlock()
        osutils.rmtree(self.dir)


class MergeTest(TestCaseWithTransport):
    def test_change_name(self):
        """Test renames."""
        builder = MergeBuilder(getcwd())
        name1 = builder.add_file(builder.root(), "name1", b"hello1", True, file_id=b"1")
        builder.change_name(name1, other="name2")
        name3 = builder.add_file(builder.root(), "name3", b"hello2", True, file_id=b"2")
        builder.change_name(name3, base="name4")
        name5 = builder.add_file(builder.root(), "name5", b"hello3", True, file_id=b"3")
        builder.change_name(name5, this="name6")
        builder.merge()
        builder.cleanup()
        builder = MergeBuilder(getcwd())
        name1 = builder.add_file(
            builder.root(), "name1", b"hello1", False, file_id=b"1"
        )
        builder.change_name(name1, other="name2", this="name3")
        conflicts = builder.merge()
        self.assertEqual(conflicts, [PathConflict("name3", "name2", b"1")])
        builder.cleanup()

    def test_merge_one(self):
        builder = MergeBuilder(getcwd())
        name1 = builder.add_file(builder.root(), "name1", b"hello1", True, file_id=b"1")
        builder.change_contents(name1, other=b"text4")
        name2 = builder.add_file(builder.root(), "name2", b"hello1", True, file_id=b"2")
        builder.change_contents(name2, other=b"text4")
        builder.merge(interesting_files=["name1"])
        self.assertEqual(builder.this.get_file("name1").read(), b"text4")
        self.assertEqual(builder.this.get_file("name2").read(), b"hello1")
        builder.cleanup()

    def test_file_moves(self):
        """Test moves."""
        builder = MergeBuilder(getcwd())
        dir1 = builder.add_dir(builder.root(), "dir1", file_id=b"1")
        builder.add_dir(builder.root(), "dir2", file_id=b"2")
        file1 = builder.add_file(dir1, "file1", b"hello1", True, file_id=b"3")
        file2 = builder.add_file(dir1, "file2", b"hello2", True, file_id=b"4")
        file3 = builder.add_file(dir1, "file3", b"hello3", True, file_id=b"5")
        builder.change_parent(file1, other=b"2")
        builder.change_parent(file2, this=b"2")
        builder.change_parent(file3, base=b"2")
        builder.merge()
        builder.cleanup()

        builder = MergeBuilder(getcwd())
        dir1 = builder.add_dir(builder.root(), "dir1", file_id=b"1")
        builder.add_dir(builder.root(), "dir2", file_id=b"2")
        builder.add_dir(builder.root(), "dir3", file_id=b"3")
        file1 = builder.add_file(dir1, "file1", b"hello1", False, file_id=b"4")
        builder.change_parent(file1, other=b"2", this=b"3")
        conflicts = builder.merge()
        path2 = pathjoin("dir2", "file1")
        path3 = pathjoin("dir3", "file1")
        self.assertEqual(conflicts, [PathConflict(path3, path2, b"4")])
        builder.cleanup()

    def test_contents_merge(self):
        """Test merge3 merging."""
        self.do_contents_test(Merge3Merger)

    def test_contents_merge2(self):
        """Test diff3 merging."""
        if sys.platform == "win32":
            raise TestSkipped(
                "diff3 does not have --binary flag and therefore always fails on win32"
            )
        try:
            self.do_contents_test(Diff3Merger)
        except errors.NoDiff3 as err:
            raise TestSkipped("diff3 not available") from err

    def test_contents_merge3(self):
        """Test diff3 merging."""
        self.do_contents_test(WeaveMerger)

    def test_reprocess_weave(self):
        # Reprocess works on weaves, and behaves as expected
        builder = MergeBuilder(getcwd())
        blah = builder.add_file(builder.root(), "blah", b"a", False, file_id=b"a")
        builder.change_contents(blah, this=b"b\nc\nd\ne\n", other=b"z\nc\nd\ny\n")
        builder.merge(WeaveMerger, reprocess=True)
        expected = b"""<<<<<<< TREE
b
=======
z
>>>>>>> MERGE-SOURCE
c
d
<<<<<<< TREE
e
=======
y
>>>>>>> MERGE-SOURCE
"""
        self.assertEqualDiff(builder.this.get_file_text("blah"), expected)
        builder.cleanup()

    def do_contents_test(self, merge_factory):
        """Test merging with specified ContentsChange factory."""
        builder = self.contents_test_success(merge_factory)
        builder.cleanup()
        self.contents_test_conflicts(merge_factory)

    def contents_test_success(self, merge_factory):
        builder = MergeBuilder(getcwd())
        name1 = builder.add_file(builder.root(), "name1", b"text1", True, file_id=b"1")
        builder.change_contents(name1, other=b"text4")
        name3 = builder.add_file(builder.root(), "name3", b"text2", False, file_id=b"2")
        builder.change_contents(name3, base=b"text5")
        builder.add_file(builder.root(), "name5", b"text3", True, file_id=b"3")
        name6 = builder.add_file(builder.root(), "name6", b"text4", True, file_id=b"4")
        builder.remove_file(name6, base=True)
        name7 = builder.add_file(
            builder.root(), "name7", b"a\nb\nc\nd\ne\nf\n", True, file_id=b"5"
        )
        builder.change_contents(
            name7, other=b"a\nz\nc\nd\ne\nf\n", this=b"a\nb\nc\nd\ne\nz\n"
        )
        conflicts = builder.merge(merge_factory)
        try:
            self.assertEqual([], conflicts)
            self.assertEqual(b"text4", builder.this.get_file("name1").read())
            self.assertEqual(b"text2", builder.this.get_file("name3").read())
            self.assertEqual(
                b"a\nz\nc\nd\ne\nz\n", builder.this.get_file("name7").read()
            )
            self.assertTrue(builder.this.is_executable("name1"))
            self.assertFalse(builder.this.is_executable("name3"))
            self.assertTrue(builder.this.is_executable("name5"))
        except:
            builder.unlock()
            raise
        return builder

    def contents_test_conflicts(self, merge_factory):
        builder = MergeBuilder(getcwd())
        name1 = builder.add_file(builder.root(), "name1", b"text1", True, file_id=b"1")
        builder.change_contents(name1, other=b"text4", this=b"text3")
        name2 = builder.add_file(builder.root(), "name2", b"text1", True, file_id=b"2")
        builder.change_contents(name2, other=b"\x00", this=b"text3")
        name3 = builder.add_file(builder.root(), "name3", b"text5", False, file_id=b"3")
        builder.change_perms(name3, this=True)
        builder.change_contents(name3, this=b"moretext")
        builder.remove_file(name3, other=True)
        conflicts = builder.merge(merge_factory)
        self.assertEqual(
            conflicts,
            [
                TextConflict("name1", file_id=b"1"),
                ContentsConflict("name2", file_id=b"2"),
                ContentsConflict("name3", file_id=b"3"),
            ],
        )
        with builder.this.get_file(builder.this.id2path(b"2")) as f:
            self.assertEqual(f.read(), b"\x00")
        builder.cleanup()

    def test_symlink_conflicts(self):
        if sys.platform != "win32":
            builder = MergeBuilder(getcwd())
            name2 = builder.add_symlink(
                builder.root(), "name2", "target1", file_id=b"2"
            )
            builder.change_target(name2, other="target4", base="text3")
            conflicts = builder.merge()
            self.assertEqual(conflicts, [ContentsConflict("name2", file_id=b"2")])
            builder.cleanup()

    def test_symlink_merge(self):
        if sys.platform != "win32":
            builder = MergeBuilder(getcwd())
            name1 = builder.add_symlink(
                builder.root(), "name1", "target1", file_id=b"1"
            )
            name2 = builder.add_symlink(
                builder.root(), "name2", "target1", file_id=b"2"
            )
            name3 = builder.add_symlink(
                builder.root(), "name3", "target1", file_id=b"3"
            )
            builder.change_target(name1, this=b"target2")
            builder.change_target(name2, base=b"target2")
            builder.change_target(name3, other=b"target2")
            builder.merge()
            self.assertEqual(builder.this.get_symlink_target("name1"), "target2")
            self.assertEqual(builder.this.get_symlink_target("name2"), "target1")
            self.assertEqual(builder.this.get_symlink_target("name3"), "target2")
            builder.cleanup()

    def test_no_passive_add(self):
        builder = MergeBuilder(getcwd())
        name1 = builder.add_file(builder.root(), "name1", b"text1", True, file_id=b"1")
        builder.remove_file(name1, this=True)
        builder.merge()
        builder.cleanup()

    def test_perms_merge(self):
        builder = MergeBuilder(getcwd())
        name1 = builder.add_file(builder.root(), "name1", b"text1", True, file_id=b"1")
        builder.change_perms(name1, other=False)
        name2 = builder.add_file(builder.root(), "name2", b"text2", True, file_id=b"2")
        builder.change_perms(name2, base=False)
        name3 = builder.add_file(builder.root(), "name3", b"text3", True, file_id=b"3")
        builder.change_perms(name3, this=False)
        name4 = builder.add_file(builder.root(), "name4", b"text4", False, file_id=b"4")
        builder.change_perms(name4, this=True)
        builder.remove_file(name4, base=True)
        builder.merge()
        self.assertFalse(builder.this.is_executable("name1"))
        self.assertTrue(builder.this.is_executable("name2"))
        self.assertFalse(builder.this.is_executable("name3"))
        builder.cleanup()

    def test_new_suffix(self):
        builder = MergeBuilder(getcwd())
        name1 = builder.add_file(builder.root(), "name1", b"text1", True, file_id=b"1")
        builder.change_contents(name1, other=b"text3")
        builder.add_file(builder.root(), "name1.new", b"text2", True, file_id=b"2")
        builder.merge()
        os.lstat(builder.this.abspath("name1.new"))
        builder.cleanup()

    def test_spurious_conflict(self):
        builder = MergeBuilder(getcwd())
        name1 = builder.add_file(builder.root(), "name1", b"text1", False, file_id=b"1")
        builder.remove_file(name1, other=True)
        builder.add_file(
            builder.root(),
            "name1",
            b"text1",
            False,
            this=False,
            base=False,
            file_id=b"2",
        )
        conflicts = builder.merge()
        self.assertEqual(conflicts, [])
        builder.cleanup()

    def test_merge_one_renamed(self):
        builder = MergeBuilder(getcwd())
        name1 = builder.add_file(
            builder.root(), "name1", b"text1a", False, file_id=b"1"
        )
        builder.change_name(name1, this="name2")
        builder.change_contents(name1, other=b"text2")
        builder.merge(interesting_files=["name2"])
        self.assertEqual(b"text2", builder.this.get_file("name2").read())
        builder.cleanup()


class FunctionalMergeTest(TestCaseWithTransport):
    def test_trivial_star_merge(self):
        """Test that merges in a star shape Just Work."""
        # John starts a branch
        self.build_tree(("original/", "original/file1", "original/file2"))
        tree = self.make_branch_and_tree("original")
        branch = tree.branch
        tree.smart_add(["original"])
        tree.commit("start branch.", verbose=False)
        # Mary branches it.
        self.build_tree(("mary/",))
        branch.controldir.clone("mary")
        # Now John commits a change
        with open("original/file1", "w") as f:
            f.write("John\n")
        tree.commit("change file1")
        # Mary does too
        mary_tree = WorkingTree.open("mary")
        with open("mary/file2", "w") as f:
            f.write("Mary\n")
        mary_tree.commit("change file2")
        # john should be able to merge with no conflicts.
        tree.merge_from_branch(mary_tree.branch)
        with open("original/file1") as f:
            self.assertEqual("John\n", f.read())
        with open("original/file2") as f:
            self.assertEqual("Mary\n", f.read())

    def test_conflicts(self):
        wta = self.make_branch_and_tree("a")
        self.build_tree_contents([("a/file", b"contents\n")])
        wta.add("file")
        wta.commit("base revision", allow_pointless=False)
        d_b = wta.branch.controldir.clone("b")
        self.build_tree_contents([("a/file", b"other contents\n")])
        wta.commit("other revision", allow_pointless=False)
        self.build_tree_contents([("b/file", b"this contents contents\n")])
        wtb = d_b.open_workingtree()
        wtb.commit("this revision", allow_pointless=False)
        self.assertEqual(1, len(wtb.merge_from_branch(wta.branch)))
        self.assertPathExists("b/file.THIS")
        self.assertPathExists("b/file.BASE")
        self.assertPathExists("b/file.OTHER")
        wtb.revert()
        self.assertEqual(
            1, len(wtb.merge_from_branch(wta.branch, merge_type=WeaveMerger))
        )
        self.assertPathExists("b/file")
        self.assertPathExists("b/file.THIS")
        self.assertPathExists("b/file.BASE")
        self.assertPathExists("b/file.OTHER")

    def test_weave_conflicts_not_in_base(self):
        builder = self.make_branch_builder("source")
        builder.start_series()
        # See bug #494197
        #  A        base revision (before criss-cross)
        #  |\
        #  B C      B does nothing, C adds 'foo'
        #  |X|
        #  D E      D and E modify foo in incompatible ways
        #
        # Merging will conflict, with C as a clean base text. However, the
        # current code uses A as the global base and 'foo' doesn't exist there.
        # It isn't trivial to create foo.BASE because it tries to look up
        # attributes like 'executable' in A.
        a_id = builder.build_snapshot(
            None, [("add", ("", b"TREE_ROOT", "directory", None))]
        )
        b_id = builder.build_snapshot([a_id], [])
        c_id = builder.build_snapshot(
            [a_id], [("add", ("foo", b"foo-id", "file", b"orig\ncontents\n"))]
        )
        d_id = builder.build_snapshot(
            [b_id, c_id],
            [("add", ("foo", b"foo-id", "file", b"orig\ncontents\nand D\n"))],
        )
        builder.build_snapshot(
            [c_id, b_id], [("modify", ("foo", b"orig\ncontents\nand E\n"))]
        )
        builder.finish_series()
        tree = builder.get_branch().create_checkout("tree", lightweight=True)
        self.assertEqual(
            1,
            len(
                tree.merge_from_branch(
                    tree.branch, to_revision=d_id, merge_type=WeaveMerger
                )
            ),
        )
        self.assertPathExists("tree/foo.THIS")
        self.assertPathExists("tree/foo.OTHER")
        self.expectFailure(
            "fail to create .BASE in some criss-cross merges",
            self.assertPathExists,
            "tree/foo.BASE",
        )
        self.assertPathExists("tree/foo.BASE")

    def test_merge_unrelated(self):
        """Sucessfully merges unrelated branches with no common names."""
        wta = self.make_branch_and_tree("a")
        with open("a/a_file", "wb") as f:
            f.write(b"contents\n")
        wta.add("a_file")
        wta.commit("a_revision", allow_pointless=False)
        wtb = self.make_branch_and_tree("b")
        with open("b/b_file", "wb") as f:
            f.write(b"contents\n")
        wtb.add("b_file")
        b_rev = wtb.commit("b_revision", allow_pointless=False)
        wta.merge_from_branch(wtb.branch, b_rev, b"null:")
        self.assertTrue(os.path.lexists("a/b_file"))
        self.assertEqual([b_rev], wta.get_parent_ids()[1:])

    def test_merge_unrelated_conflicting(self):
        """Sucessfully merges unrelated branches with common names."""
        wta = self.make_branch_and_tree("a")
        with open("a/file", "wb") as f:
            f.write(b"contents\n")
        wta.add("file")
        wta.commit("a_revision", allow_pointless=False)
        wtb = self.make_branch_and_tree("b")
        with open("b/file", "wb") as f:
            f.write(b"contents\n")
        wtb.add("file")
        b_rev = wtb.commit("b_revision", allow_pointless=False)
        wta.merge_from_branch(wtb.branch, b_rev, b"null:")
        self.assertTrue(os.path.lexists("a/file"))
        self.assertTrue(os.path.lexists("a/file.moved"))
        self.assertEqual([b_rev], wta.get_parent_ids()[1:])

    def test_merge_deleted_conflicts(self):
        wta = self.make_branch_and_tree("a")
        with open("a/file", "wb") as f:
            f.write(b"contents\n")
        wta.add("file")
        wta.commit("a_revision", allow_pointless=False)
        self.run_bzr("branch a b")
        os.remove("a/file")
        wta.commit("removed file", allow_pointless=False)
        with open("b/file", "wb") as f:
            f.write(b"changed contents\n")
        wtb = WorkingTree.open("b")
        wtb.commit("changed file", allow_pointless=False)
        wtb.merge_from_branch(
            wta.branch, wta.branch.last_revision(), wta.branch.get_rev_id(1)
        )
        self.assertFalse(os.path.lexists("b/file"))

    def test_merge_metadata_vs_deletion(self):
        """Conflict deletion vs metadata change."""
        a_wt = self.make_branch_and_tree("a")
        with open("a/file", "wb") as f:
            f.write(b"contents\n")
        a_wt.add("file")
        a_wt.commit("r0")
        self.run_bzr("branch a b")
        b_wt = WorkingTree.open("b")
        os.chmod("b/file", 0o755)  # noqa: S103
        os.remove("a/file")
        a_wt.commit("removed a")
        self.assertEqual(a_wt.branch.revno(), 2)
        self.assertFalse(os.path.exists("a/file"))
        b_wt.commit("exec a")
        a_wt.merge_from_branch(b_wt.branch, b_wt.last_revision(), b"null:")
        self.assertTrue(os.path.exists("a/file"))

    def test_merge_swapping_renames(self):
        a_wt = self.make_branch_and_tree("a")
        with open("a/un", "wb") as f:
            f.write(b"UN")
        with open("a/deux", "wb") as f:
            f.write(b"DEUX")
        a_wt.add("un")
        a_wt.add("deux")
        a_wt.commit("r0", rev_id=b"r0")
        self.run_bzr("branch a b")
        b_wt = WorkingTree.open("b")
        b_wt.rename_one("un", "tmp")
        b_wt.rename_one("deux", "un")
        b_wt.rename_one("tmp", "deux")
        b_wt.commit("r1", rev_id=b"r1")
        self.assertEqual(
            0,
            len(
                a_wt.merge_from_branch(
                    b_wt.branch, b_wt.branch.last_revision(), b_wt.branch.get_rev_id(1)
                )
            ),
        )
        self.assertPathExists("a/un")
        self.assertTrue("a/deux")
        self.assertFalse(os.path.exists("a/tmp"))
        with open("a/un") as f:
            self.assertEqual(f.read(), "DEUX")
        with open("a/deux") as f:
            self.assertEqual(f.read(), "UN")

    def test_merge_delete_and_add_same(self):
        a_wt = self.make_branch_and_tree("a")
        with open("a/file", "wb") as f:
            f.write(b"THIS")
        a_wt.add("file")
        a_wt.commit("r0")
        self.run_bzr("branch a b")
        b_wt = WorkingTree.open("b")
        os.remove("b/file")
        b_wt.commit("r1")
        with open("b/file", "wb") as f:
            f.write(b"THAT")
        b_wt.add("file")
        b_wt.commit("r2")
        a_wt.merge_from_branch(
            b_wt.branch, b_wt.branch.last_revision(), b_wt.branch.get_rev_id(1)
        )
        self.assertTrue(os.path.exists("a/file"))
        with open("a/file") as f:
            self.assertEqual(f.read(), "THAT")

    def test_merge_rename_before_create(self):
        """Rename before create.

        This case requires that you must not do creates
        before move-into-place:

        $ touch foo
        $ bzr add foo
        $ bzr commit
        $ bzr mv foo bar
        $ touch foo
        $ bzr add foo
        $ bzr commit
        """
        a_wt = self.make_branch_and_tree("a")
        with open("a/foo", "wb") as f:
            f.write(b"A/FOO")
        a_wt.add("foo")
        a_wt.commit("added foo")
        self.run_bzr("branch a b")
        b_wt = WorkingTree.open("b")
        b_wt.rename_one("foo", "bar")
        with open("b/foo", "wb") as f:
            f.write(b"B/FOO")
        b_wt.add("foo")
        b_wt.commit("moved foo to bar, added new foo")
        a_wt.merge_from_branch(
            b_wt.branch, b_wt.branch.last_revision(), b_wt.branch.get_rev_id(1)
        )

    def test_merge_create_before_rename(self):
        """Create before rename, target parents before children.

        This case requires that you must not do move-into-place
        before creates, and that you must not do children after
        parents:

        $ touch foo
        $ bzr add foo
        $ bzr commit
        $ bzr mkdir bar
        $ bzr add bar
        $ bzr mv foo bar/foo
        $ bzr commit
        """
        os.mkdir("a")
        a_wt = self.make_branch_and_tree("a")
        with open("a/foo", "wb") as f:
            f.write(b"A/FOO")
        a_wt.add("foo")
        a_wt.commit("added foo")
        self.run_bzr("branch a b")
        b_wt = WorkingTree.open("b")
        os.mkdir("b/bar")
        b_wt.add("bar")
        b_wt.rename_one("foo", "bar/foo")
        b_wt.commit("created bar dir, moved foo into bar")
        a_wt.merge_from_branch(
            b_wt.branch, b_wt.branch.last_revision(), b_wt.branch.get_rev_id(1)
        )

    def test_merge_rename_to_temp_before_delete(self):
        """Rename to temp before delete, source children before parents.

        This case requires that you must not do deletes before
        move-out-of-the-way, and that you must not do children
        after parents:

        $ mkdir foo
        $ touch foo/bar
        $ bzr add foo/bar
        $ bzr commit
        $ bzr mv foo/bar bar
        $ rmdir foo
        $ bzr commit
        """
        a_wt = self.make_branch_and_tree("a")
        os.mkdir("a/foo")
        with open("a/foo/bar", "wb") as f:
            f.write(b"A/FOO/BAR")
        a_wt.add("foo")
        a_wt.add("foo/bar")
        a_wt.commit("added foo/bar")
        self.run_bzr("branch a b")
        b_wt = WorkingTree.open("b")
        b_wt.rename_one("foo/bar", "bar")
        os.rmdir("b/foo")
        b_wt.remove("foo")
        b_wt.commit("moved foo/bar to bar, deleted foo")
        a_wt.merge_from_branch(
            b_wt.branch, b_wt.branch.last_revision(), b_wt.branch.get_rev_id(1)
        )

    def test_merge_delete_before_rename_to_temp(self):
        """Delete before rename to temp.

        This case requires that you must not do
        move-out-of-the-way before deletes:

        $ touch foo
        $ touch bar
        $ bzr add foo bar
        $ bzr commit
        $ rm foo
        $ bzr rm foo
        $ bzr mv bar foo
        $ bzr commit
        """
        a_wt = self.make_branch_and_tree("a")
        with open("a/foo", "wb") as f:
            f.write(b"A/FOO")
        with open("a/bar", "wb") as f:
            f.write(b"A/BAR")
        a_wt.add("foo")
        a_wt.add("bar")
        a_wt.commit("added foo and bar")
        self.run_bzr("branch a b")
        b_wt = WorkingTree.open("b")
        os.unlink("b/foo")
        b_wt.remove("foo")
        b_wt.rename_one("bar", "foo")
        b_wt.commit("deleted foo, renamed bar to foo")
        a_wt.merge_from_branch(
            b_wt.branch, b_wt.branch.last_revision(), b_wt.branch.get_rev_id(1)
        )


class TestMerger(TestCaseWithTransport):
    def set_up_trees(self):
        this = self.make_branch_and_tree("this")
        this.commit("rev1", rev_id=b"rev1")
        other = this.controldir.sprout("other").open_workingtree()
        this.commit("rev2a", rev_id=b"rev2a")
        other.commit("rev2b", rev_id=b"rev2b")
        return this, other

    def test_from_revision_ids(self):
        this, other = self.set_up_trees()
        self.assertRaises(
            errors.NoSuchRevision, Merger.from_revision_ids, this, b"rev2b"
        )
        this.lock_write()
        self.addCleanup(this.unlock)
        merger = Merger.from_revision_ids(this, b"rev2b", other_branch=other.branch)
        self.assertEqual(b"rev2b", merger.other_rev_id)
        self.assertEqual(b"rev1", merger.base_rev_id)
        merger = Merger.from_revision_ids(
            this, b"rev2b", b"rev2a", other_branch=other.branch
        )
        self.assertEqual(b"rev2a", merger.base_rev_id)

    def test_from_uncommitted(self):
        this, other = self.set_up_trees()
        merger = Merger.from_uncommitted(this, other, None)
        self.assertIs(other, merger.other_tree)
        self.assertIs(None, merger.other_rev_id)
        self.assertEqual(b"rev2b", merger.base_rev_id)

    def prepare_for_merging(self):
        this, other = self.set_up_trees()
        other.commit("rev3", rev_id=b"rev3")
        this.lock_write()
        self.addCleanup(this.unlock)
        return this, other

    def test_from_mergeable(self):
        this, other = self.prepare_for_merging()
        md = merge_directive.MergeDirective2.from_objects(
            repository=other.branch.repository,
            revision_id=b"rev3",
            time=0,
            timezone=0,
            target_branch="this",
        )
        other.lock_read()
        self.addCleanup(other.unlock)
        merger, verified = Merger.from_mergeable(this, md)
        md.patch = None
        merger, verified = Merger.from_mergeable(this, md)
        self.assertEqual("inapplicable", verified)
        self.assertEqual(b"rev3", merger.other_rev_id)
        self.assertEqual(b"rev1", merger.base_rev_id)
        md.base_revision_id = b"rev2b"
        merger, verified = Merger.from_mergeable(this, md)
        self.assertEqual(b"rev2b", merger.base_rev_id)

    def test_from_mergeable_old_merge_directive(self):
        this, other = self.prepare_for_merging()
        other.lock_write()
        self.addCleanup(other.unlock)
        md = merge_directive.MergeDirective.from_objects(
            repository=other.branch.repository,
            revision_id=b"rev3",
            time=0,
            timezone=0,
            target_branch="this",
        )
        merger, _verified = Merger.from_mergeable(this, md)
        self.assertEqual(b"rev3", merger.other_rev_id)
        self.assertEqual(b"rev1", merger.base_rev_id)
