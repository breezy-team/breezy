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

import contextlib
import os

from .. import branch as _mod_branch
from .. import errors, memorytree, option, tests
from .. import merge as _mod_merge
from .. import revision as _mod_revision
from ..bzr import inventory, knit, versionedfile
from ..bzr.conflicts import (
    ContentsConflict,
    DeletingParent,
    MissingParent,
    TextConflict,
    UnversionedParent,
)
from ..errors import NoCommits, UnrelatedBranches
from ..merge import _PlanMerge, merge_inner, transform_tree
from ..osutils import basename, pathjoin
from ..transport.local import file_kind
from ..workingtree import PointlessMerge, WorkingTree
from . import (
    TestCaseWithMemoryTransport,
    TestCaseWithTransport,
    features,
    test_merge_core,
)


class TestMerge(TestCaseWithTransport):
    """Test appending more than one revision."""

    def test_pending(self):
        wt = self.make_branch_and_tree(".")
        rev_a = wt.commit("lala!")
        self.assertEqual([rev_a], wt.get_parent_ids())
        self.assertRaises(PointlessMerge, wt.merge_from_branch, wt.branch)
        self.assertEqual([rev_a], wt.get_parent_ids())
        return wt

    def test_undo(self):
        wt = self.make_branch_and_tree(".")
        wt.commit("lala!")
        wt.commit("haha!")
        wt.commit("blabla!")
        wt.merge_from_branch(
            wt.branch, wt.branch.get_rev_id(2), wt.branch.get_rev_id(1)
        )

    def test_nocommits(self):
        wt = self.test_pending()
        wt2 = self.make_branch_and_tree("branch2")
        self.assertRaises(NoCommits, wt.merge_from_branch, wt2.branch)
        return wt, wt2

    def test_unrelated(self):
        wt, wt2 = self.test_nocommits()
        wt2.commit("blah")
        self.assertRaises(UnrelatedBranches, wt.merge_from_branch, wt2.branch)
        return wt2

    def test_merge_one_file(self):
        """Do a partial merge of a tree which should not affect tree parents."""
        wt1 = self.make_branch_and_tree("branch1")
        tip = wt1.commit("empty commit")
        wt2 = self.make_branch_and_tree("branch2")
        wt2.pull(wt1.branch)
        with open("branch1/foo", "wb") as f:
            f.write(b"foo")
        with open("branch1/bar", "wb") as f:
            f.write(b"bar")
        wt1.add("foo")
        wt1.add("bar")
        wt1.commit("add foobar")
        self.run_bzr("merge ../branch1/baz", retcode=3, working_dir="branch2")
        self.run_bzr("merge ../branch1/foo", working_dir="branch2")
        self.assertPathExists("branch2/foo")
        self.assertPathDoesNotExist("branch2/bar")
        wt2 = WorkingTree.open("branch2")
        self.assertEqual([tip], wt2.get_parent_ids())

    def test_pending_with_null(self):
        """When base is forced to revno 0, parent_ids are set."""
        wt2 = self.test_unrelated()
        wt1 = WorkingTree.open(".")
        br1 = wt1.branch
        br1.fetch(wt2.branch)
        # merge all of branch 2 into branch 1 even though they
        # are not related.
        wt1.merge_from_branch(wt2.branch, wt2.last_revision(), b"null:")
        self.assertEqual(
            [br1.last_revision(), wt2.branch.last_revision()], wt1.get_parent_ids()
        )
        return (wt1, wt2.branch)

    def test_two_roots(self):
        """Merge base is sane when two unrelated branches are merged."""
        wt1, br2 = self.test_pending_with_null()
        wt1.commit("blah")
        wt1.lock_read()
        try:
            last = wt1.branch.last_revision()
            last2 = br2.last_revision()
            graph = wt1.branch.repository.get_graph()
            self.assertEqual(last2, graph.find_unique_lca(last, last2))
        finally:
            wt1.unlock()

    def test_merge_into_null_tree(self):
        wt = self.make_branch_and_tree("tree")
        null_tree = wt.basis_tree()
        self.build_tree(["tree/file"])
        wt.add("file")
        wt.commit("tree with root")
        merger = _mod_merge.Merge3Merger(
            null_tree, null_tree, null_tree, wt, this_branch=wt.branch, do_merge=False
        )
        with merger.make_preview_transform() as tt:
            self.assertEqual([], tt.find_raw_conflicts())
            preview = tt.get_preview_tree()
            self.assertEqual(wt.path2id(""), preview.path2id(""))

    def test_merge_unrelated_retains_root(self):
        wt = self.make_branch_and_tree("tree")
        other_tree = self.make_branch_and_tree("other")
        self.addCleanup(other_tree.lock_read().unlock)
        merger = _mod_merge.Merge3Merger(
            wt, wt, wt.basis_tree(), other_tree, this_branch=wt.branch, do_merge=False
        )
        with wt.preview_transform() as merger.tt:
            merger._compute_transform()
            new_root_id = merger.tt.final_file_id(merger.tt.root)
            self.assertEqual(wt.path2id(""), new_root_id)

    def test_create_rename(self):
        """Rename an inventory entry while creating the file."""
        tree = self.make_branch_and_tree(".")
        with open("name1", "wb") as f:
            f.write(b"Hello")
        tree.add("name1")
        tree.commit(message="hello")
        tree.rename_one("name1", "name2")
        os.unlink("name2")
        transform_tree(tree, tree.branch.basis_tree())

    def test_layered_rename(self):
        """Rename both child and parent at same time."""
        tree = self.make_branch_and_tree(".")
        os.mkdir("dirname1")
        tree.add("dirname1")
        filename = pathjoin("dirname1", "name1")
        with open(filename, "wb") as f:
            f.write(b"Hello")
        tree.add(filename)
        tree.commit(message="hello")
        filename2 = pathjoin("dirname1", "name2")
        tree.rename_one(filename, filename2)
        tree.rename_one("dirname1", "dirname2")
        transform_tree(tree, tree.branch.basis_tree())

    def test_ignore_zero_merge_inner(self):
        # Test that merge_inner's ignore zero parameter is effective
        tree_a = self.make_branch_and_tree("a")
        tree_a.commit(message="hello")
        dir_b = tree_a.controldir.sprout("b")
        tree_b = dir_b.open_workingtree()
        tree_b.lock_write()
        self.addCleanup(tree_b.unlock)
        tree_a.commit(message="hello again")
        merge_inner(
            tree_b.branch,
            tree_a,
            tree_b.basis_tree(),
            this_tree=tree_b,
            ignore_zero=True,
        )
        self.assertNotIn("All changes applied successfully.\n", self.get_log())
        tree_b.revert()
        merge_inner(
            tree_b.branch,
            tree_a,
            tree_b.basis_tree(),
            this_tree=tree_b,
            ignore_zero=False,
        )
        self.assertIn("All changes applied successfully.\n", self.get_log())

    def test_merge_inner_conflicts(self):
        tree_a = self.make_branch_and_tree("a")
        tree_a.set_conflicts([TextConflict("patha")])
        merge_inner(tree_a.branch, tree_a, tree_a, this_tree=tree_a)
        self.assertEqual(1, len(tree_a.conflicts()))

    def test_rmdir_conflict(self):
        tree_a = self.make_branch_and_tree("a")
        self.build_tree(["a/b/"])
        tree_a.add("b", ids=b"b-id")
        tree_a.commit("added b")
        # basis_tree() is only guaranteed to be valid as long as it is actually
        # the basis tree. This mutates the tree after grabbing basis, so go to
        # the repository.
        base_tree = tree_a.branch.repository.revision_tree(tree_a.last_revision())
        tree_z = tree_a.controldir.sprout("z").open_workingtree()
        self.build_tree(["a/b/c"])
        tree_a.add("b/c")
        tree_a.commit("added c")
        os.rmdir("z/b")
        tree_z.commit("removed b")
        merge_inner(tree_z.branch, tree_a, base_tree, this_tree=tree_z)
        self.assertEqual(
            [
                MissingParent("Created directory", "b", b"b-id"),
                UnversionedParent("Versioned directory", "b", b"b-id"),
            ],
            tree_z.conflicts(),
        )
        merge_inner(tree_a.branch, tree_z.basis_tree(), base_tree, this_tree=tree_a)
        self.assertEqual(
            [
                DeletingParent("Not deleting", "b", b"b-id"),
                UnversionedParent("Versioned directory", "b", b"b-id"),
            ],
            tree_a.conflicts(),
        )

    def test_nested_merge(self):
        self.knownFailure("iter_changes doesn't work with changes in nested trees")
        tree = self.make_branch_and_tree("tree", format="development-subtree")
        sub_tree = self.make_branch_and_tree(
            "tree/sub-tree", format="development-subtree"
        )
        sub_tree.set_root_id(b"sub-tree-root")
        self.build_tree_contents([("tree/sub-tree/file", b"text1")])
        sub_tree.add("file")
        sub_tree.commit("foo")
        tree.add_reference(sub_tree)
        tree.commit("set text to 1")
        tree2 = tree.controldir.sprout("tree2").open_workingtree()
        # modify the file in the subtree
        self.build_tree_contents([("tree2/sub-tree/file", b"text2")])
        # and merge the changes from the diverged subtree into the containing
        # tree
        tree2.commit("changed file text")
        tree.merge_from_branch(tree2.branch)
        self.assertFileEqual(b"text2", "tree/sub-tree/file")

    def test_merge_with_missing(self):
        tree_a = self.make_branch_and_tree("tree_a")
        self.build_tree_contents([("tree_a/file", b"content_1")])
        tree_a.add("file")
        tree_a.commit("commit base")
        # basis_tree() is only guaranteed to be valid as long as it is actually
        # the basis tree. This test commits to the tree after grabbing basis,
        # so we go to the repository.
        base_tree = tree_a.branch.repository.revision_tree(tree_a.last_revision())
        tree_b = tree_a.controldir.sprout("tree_b").open_workingtree()
        self.build_tree_contents([("tree_a/file", b"content_2")])
        tree_a.commit("commit other")
        other_tree = tree_a.basis_tree()
        # 'file' is now missing but isn't altered in any commit in b so no
        # change should be applied.
        os.unlink("tree_b/file")
        merge_inner(tree_b.branch, other_tree, base_tree, this_tree=tree_b)

    def test_merge_kind_change(self):
        tree_a = self.make_branch_and_tree("tree_a")
        self.build_tree_contents([("tree_a/file", b"content_1")])
        tree_a.add("file", ids=b"file-id")
        tree_a.commit("added file")
        tree_b = tree_a.controldir.sprout("tree_b").open_workingtree()
        os.unlink("tree_a/file")
        self.build_tree(["tree_a/file/"])
        tree_a.commit("changed file to directory")
        tree_b.merge_from_branch(tree_a.branch)
        self.assertEqual("directory", file_kind("tree_b/file"))
        tree_b.revert()
        self.assertEqual("file", file_kind("tree_b/file"))
        self.build_tree_contents([("tree_b/file", b"content_2")])
        tree_b.commit("content change")
        tree_b.merge_from_branch(tree_a.branch)
        self.assertEqual(
            tree_b.conflicts(), [ContentsConflict("file", file_id=b"file-id")]
        )

    def test_merge_type_registry(self):
        merge_type_option = option.Option.OPTIONS["merge-type"]
        self.assertNotIn("merge4", [x[0] for x in merge_type_option.iter_switches()])
        registry = _mod_merge.get_merge_type_registry()
        registry.register_lazy(
            "merge4", "breezy.merge", "Merge4Merger", "time-travelling merge"
        )
        self.assertIn("merge4", [x[0] for x in merge_type_option.iter_switches()])
        registry.remove("merge4")
        self.assertNotIn("merge4", [x[0] for x in merge_type_option.iter_switches()])

    def test_merge_other_moves_we_deleted(self):
        tree_a = self.make_branch_and_tree("A")
        tree_a.lock_write()
        self.addCleanup(tree_a.unlock)
        self.build_tree(["A/a"])
        tree_a.add("a")
        tree_a.commit("1", rev_id=b"rev-1")
        tree_a.flush()
        tree_a.rename_one("a", "b")
        tree_a.commit("2")
        bzrdir_b = tree_a.controldir.sprout("B", revision_id=b"rev-1")
        tree_b = bzrdir_b.open_workingtree()
        tree_b.lock_write()
        self.addCleanup(tree_b.unlock)
        os.unlink("B/a")
        tree_b.commit("3")
        try:
            tree_b.merge_from_branch(tree_a.branch)
        except AttributeError:
            self.fail("tried to join a path when name was None")

    def test_merge_uncommitted_otherbasis_ancestor_of_thisbasis(self):
        tree_a = self.make_branch_and_tree("a")
        self.build_tree(["a/file_1", "a/file_2"])
        tree_a.add(["file_1"])
        tree_a.commit("commit 1")
        tree_a.add(["file_2"])
        tree_a.commit("commit 2")
        tree_b = tree_a.controldir.sprout("b").open_workingtree()
        tree_b.rename_one("file_1", "renamed")
        merger = _mod_merge.Merger.from_uncommitted(tree_a, tree_b)
        merger.merge_type = _mod_merge.Merge3Merger
        merger.do_merge()
        self.assertEqual(tree_a.get_parent_ids(), [tree_b.last_revision()])

    def test_merge_uncommitted_otherbasis_ancestor_of_thisbasis_weave(self):
        tree_a = self.make_branch_and_tree("a")
        self.build_tree(["a/file_1", "a/file_2"])
        tree_a.add(["file_1"])
        tree_a.commit("commit 1")
        tree_a.add(["file_2"])
        tree_a.commit("commit 2")
        tree_b = tree_a.controldir.sprout("b").open_workingtree()
        tree_b.rename_one("file_1", "renamed")
        merger = _mod_merge.Merger.from_uncommitted(tree_a, tree_b)
        merger.merge_type = _mod_merge.WeaveMerger
        merger.do_merge()
        self.assertEqual(tree_a.get_parent_ids(), [tree_b.last_revision()])

    def prepare_cherrypick(self):
        """Prepare a pair of trees for cherrypicking tests.

        Both trees have a file, 'file'.
        rev1 sets content to 'a'.
        rev2b adds 'b'.
        rev3b adds 'c'.
        A full merge of rev2b and rev3b into this_tree would add both 'b' and
        'c'.  A successful cherrypick of rev2b-rev3b into this_tree will add
        'c', but not 'b'.
        """
        this_tree = self.make_branch_and_tree("this")
        self.build_tree_contents([("this/file", b"a\n")])
        this_tree.add("file")
        this_tree.commit("rev1")
        other_tree = this_tree.controldir.sprout("other").open_workingtree()
        self.build_tree_contents([("other/file", b"a\nb\n")])
        other_tree.commit("rev2b", rev_id=b"rev2b")
        self.build_tree_contents([("other/file", b"c\na\nb\n")])
        other_tree.commit("rev3b", rev_id=b"rev3b")
        this_tree.lock_write()
        self.addCleanup(this_tree.unlock)
        return this_tree, other_tree

    def test_weave_cherrypick(self):
        this_tree, other_tree = self.prepare_cherrypick()
        merger = _mod_merge.Merger.from_revision_ids(
            this_tree, b"rev3b", b"rev2b", other_tree.branch
        )
        merger.merge_type = _mod_merge.WeaveMerger
        merger.do_merge()
        self.assertFileEqual(b"c\na\n", "this/file")

    def test_weave_cannot_reverse_cherrypick(self):
        this_tree, other_tree = self.prepare_cherrypick()
        merger = _mod_merge.Merger.from_revision_ids(
            this_tree, b"rev2b", b"rev3b", other_tree.branch
        )
        merger.merge_type = _mod_merge.WeaveMerger
        self.assertRaises(errors.CannotReverseCherrypick, merger.do_merge)

    def test_merge3_can_reverse_cherrypick(self):
        this_tree, other_tree = self.prepare_cherrypick()
        merger = _mod_merge.Merger.from_revision_ids(
            this_tree, b"rev2b", b"rev3b", other_tree.branch
        )
        merger.merge_type = _mod_merge.Merge3Merger
        merger.do_merge()

    def test_merge3_will_detect_cherrypick(self):
        this_tree = self.make_branch_and_tree("this")
        self.build_tree_contents([("this/file", b"a\n")])
        this_tree.add("file")
        this_tree.commit("rev1")
        other_tree = this_tree.controldir.sprout("other").open_workingtree()
        self.build_tree_contents([("other/file", b"a\nb\n")])
        other_tree.commit("rev2b", rev_id=b"rev2b")
        self.build_tree_contents([("other/file", b"a\nb\nc\n")])
        other_tree.commit("rev3b", rev_id=b"rev3b")
        this_tree.lock_write()
        self.addCleanup(this_tree.unlock)

        merger = _mod_merge.Merger.from_revision_ids(
            this_tree, b"rev3b", b"rev2b", other_tree.branch
        )
        merger.merge_type = _mod_merge.Merge3Merger
        merger.do_merge()
        self.assertFileEqual(
            b"a\n<<<<<<< TREE\n=======\nc\n>>>>>>> MERGE-SOURCE\n",
            "this/file",
        )

    def test_merge_reverse_revision_range(self):
        tree = self.make_branch_and_tree(".")
        tree.lock_write()
        self.addCleanup(tree.unlock)
        self.build_tree(["a"])
        tree.add("a")
        first_rev = tree.commit("added a")
        merger = _mod_merge.Merger.from_revision_ids(
            tree, _mod_revision.NULL_REVISION, first_rev
        )
        merger.merge_type = _mod_merge.Merge3Merger
        merger.interesting_files = "a"
        conflicts = merger.do_merge()
        self.assertEqual([], conflicts)

        self.assertPathDoesNotExist("a")
        tree.revert()
        self.assertPathExists("a")

    def test_make_merger(self):
        this_tree = self.make_branch_and_tree("this")
        this_tree.commit("rev1", rev_id=b"rev1")
        other_tree = this_tree.controldir.sprout("other").open_workingtree()
        this_tree.commit("rev2", rev_id=b"rev2a")
        other_tree.commit("rev2", rev_id=b"rev2b")
        this_tree.lock_write()
        self.addCleanup(this_tree.unlock)
        merger = _mod_merge.Merger.from_revision_ids(
            this_tree, b"rev2b", other_branch=other_tree.branch
        )
        merger.merge_type = _mod_merge.Merge3Merger
        tree_merger = merger.make_merger()
        self.assertIs(_mod_merge.Merge3Merger, tree_merger.__class__)
        self.assertEqual(b"rev2b", tree_merger.other_tree.get_revision_id())
        self.assertEqual(b"rev1", tree_merger.base_tree.get_revision_id())
        self.assertEqual(other_tree.branch, tree_merger.other_branch)

    def test_make_preview_transform(self):
        this_tree = self.make_branch_and_tree("this")
        self.build_tree_contents([("this/file", b"1\n")])
        this_tree.add("file", ids=b"file-id")
        this_tree.commit("rev1", rev_id=b"rev1")
        other_tree = this_tree.controldir.sprout("other").open_workingtree()
        self.build_tree_contents([("this/file", b"1\n2a\n")])
        this_tree.commit("rev2", rev_id=b"rev2a")
        self.build_tree_contents([("other/file", b"2b\n1\n")])
        other_tree.commit("rev2", rev_id=b"rev2b")
        this_tree.lock_write()
        self.addCleanup(this_tree.unlock)
        merger = _mod_merge.Merger.from_revision_ids(
            this_tree, b"rev2b", other_branch=other_tree.branch
        )
        merger.merge_type = _mod_merge.Merge3Merger
        tree_merger = merger.make_merger()
        with tree_merger.make_preview_transform() as tt:
            preview_tree = tt.get_preview_tree()
            with this_tree.get_file("file") as tree_file:
                self.assertEqual(b"1\n2a\n", tree_file.read())
            with preview_tree.get_file("file") as preview_file:
                self.assertEqual(b"2b\n1\n2a\n", preview_file.read())

    def test_do_merge(self):
        this_tree = self.make_branch_and_tree("this")
        self.build_tree_contents([("this/file", b"1\n")])
        this_tree.add("file", ids=b"file-id")
        this_tree.commit("rev1", rev_id=b"rev1")
        other_tree = this_tree.controldir.sprout("other").open_workingtree()
        self.build_tree_contents([("this/file", b"1\n2a\n")])
        this_tree.commit("rev2", rev_id=b"rev2a")
        self.build_tree_contents([("other/file", b"2b\n1\n")])
        other_tree.commit("rev2", rev_id=b"rev2b")
        this_tree.lock_write()
        self.addCleanup(this_tree.unlock)
        merger = _mod_merge.Merger.from_revision_ids(
            this_tree, b"rev2b", other_branch=other_tree.branch
        )
        merger.merge_type = _mod_merge.Merge3Merger
        tree_merger = merger.make_merger()
        tree_merger.do_merge()
        with this_tree.get_file("file") as tree_file:
            self.assertEqual(b"2b\n1\n2a\n", tree_file.read())

    def test_merge_require_tree_root(self):
        tree = self.make_branch_and_tree(".")
        tree.lock_write()
        self.addCleanup(tree.unlock)
        self.build_tree(["a"])
        tree.add("a")
        first_rev = tree.commit("added a")
        tree.path2id("")
        merger = _mod_merge.Merger.from_revision_ids(
            tree, _mod_revision.NULL_REVISION, first_rev
        )
        merger.merge_type = _mod_merge.Merge3Merger
        conflicts = merger.do_merge()
        self.assertEqual([], conflicts)
        self.assertEqual({""}, set(tree.all_versioned_paths()))
        tree.set_parent_ids([])

    def test_merge_add_into_deleted_root(self):
        # Yes, people actually do this.  And report bugs if it breaks.
        source = self.make_branch_and_tree("source", format="rich-root-pack")
        self.build_tree(["source/foo/"])
        source.add("foo", ids=b"foo-id")
        source.commit("Add foo")
        target = source.controldir.sprout("target").open_workingtree()
        subtree = target.extract("foo")
        subtree.commit("Delete root")
        self.build_tree(["source/bar"])
        source.add("bar", ids=b"bar-id")
        source.commit("Add bar")
        subtree.merge_from_branch(source.branch)

    def test_merge_joined_branch(self):
        source = self.make_branch_and_tree("source", format="rich-root-pack")
        self.build_tree(["source/foo"])
        source.add("foo")
        source.commit("Add foo")
        target = self.make_branch_and_tree("target", format="rich-root-pack")
        self.build_tree(["target/bla"])
        target.add("bla")
        target.commit("Add bla")
        nested = source.controldir.sprout("target/subtree").open_workingtree()
        target.subsume(nested)
        target.commit("Join nested")
        self.build_tree(["source/bar"])
        source.add("bar")
        source.commit("Add bar")
        target.merge_from_branch(source.branch)
        target.commit("Merge source")


class TestPlanMerge(TestCaseWithMemoryTransport):
    def setUp(self):
        super().setUp()
        mapper = versionedfile.PrefixMapper()
        factory = knit.make_file_factory(True, mapper)
        self.vf = factory(self.get_transport())
        self.plan_merge_vf = versionedfile._PlanMergeVersionedFile(b"root")
        self.plan_merge_vf.fallback_versionedfiles.append(self.vf)

    def add_version(self, key, parents, text):
        self.vf.add_lines(key, parents, [bytes([c]) + b"\n" for c in bytearray(text)])

    def add_rev(self, prefix, revision_id, parents, text):
        self.add_version((prefix, revision_id), [(prefix, p) for p in parents], text)

    def add_uncommitted_version(self, key, parents, text):
        self.plan_merge_vf.add_lines(
            key, parents, [bytes([c]) + b"\n" for c in bytearray(text)]
        )

    def setup_plan_merge(self):
        self.add_rev(b"root", b"A", [], b"abc")
        self.add_rev(b"root", b"B", [b"A"], b"acehg")
        self.add_rev(b"root", b"C", [b"A"], b"fabg")
        return _PlanMerge(b"B", b"C", self.plan_merge_vf, (b"root",))

    def setup_plan_merge_uncommitted(self):
        self.add_version((b"root", b"A"), [], b"abc")
        self.add_uncommitted_version((b"root", b"B:"), [(b"root", b"A")], b"acehg")
        self.add_uncommitted_version((b"root", b"C:"), [(b"root", b"A")], b"fabg")
        return _PlanMerge(b"B:", b"C:", self.plan_merge_vf, (b"root",))

    def test_base_from_plan(self):
        self.setup_plan_merge()
        plan = self.plan_merge_vf.plan_merge(b"B", b"C")
        pwm = versionedfile.PlanWeaveMerge(plan)
        self.assertEqual([b"a\n", b"b\n", b"c\n"], pwm.base_from_plan())

    def test_unique_lines(self):
        plan = self.setup_plan_merge()
        self.assertEqual(
            plan._unique_lines(plan._get_matching_blocks(b"B", b"C")),
            ([1, 2, 3], [0, 2]),
        )

    def test_plan_merge(self):
        self.setup_plan_merge()
        plan = self.plan_merge_vf.plan_merge(b"B", b"C")
        self.assertEqual(
            [
                ("new-b", b"f\n"),
                ("unchanged", b"a\n"),
                ("killed-a", b"b\n"),
                ("killed-b", b"c\n"),
                ("new-a", b"e\n"),
                ("new-a", b"h\n"),
                ("new-a", b"g\n"),
                ("new-b", b"g\n"),
            ],
            list(plan),
        )

    def test_plan_merge_cherrypick(self):
        self.add_rev(b"root", b"A", [], b"abc")
        self.add_rev(b"root", b"B", [b"A"], b"abcde")
        self.add_rev(b"root", b"C", [b"A"], b"abcefg")
        self.add_rev(b"root", b"D", [b"A", b"B", b"C"], b"abcdegh")
        my_plan = _PlanMerge(b"B", b"D", self.plan_merge_vf, (b"root",))
        # We shortcut when one text supersedes the other in the per-file graph.
        # We don't actually need to compare the texts at this point.
        self.assertEqual(
            [
                ("new-b", b"a\n"),
                ("new-b", b"b\n"),
                ("new-b", b"c\n"),
                ("new-b", b"d\n"),
                ("new-b", b"e\n"),
                ("new-b", b"g\n"),
                ("new-b", b"h\n"),
            ],
            list(my_plan.plan_merge()),
        )

    def test_plan_merge_no_common_ancestor(self):
        self.add_rev(b"root", b"A", [], b"abc")
        self.add_rev(b"root", b"B", [], b"xyz")
        my_plan = _PlanMerge(b"A", b"B", self.plan_merge_vf, (b"root",))
        self.assertEqual(
            [
                ("new-a", b"a\n"),
                ("new-a", b"b\n"),
                ("new-a", b"c\n"),
                ("new-b", b"x\n"),
                ("new-b", b"y\n"),
                ("new-b", b"z\n"),
            ],
            list(my_plan.plan_merge()),
        )

    def test_plan_merge_tail_ancestors(self):
        # The graph looks like this:
        #       A       # Common to all ancestors
        #      / \
        #     B   C     # Ancestors of E, only common to one side
        #     |\ /|
        #     D E F     # D, F are unique to G, H respectively
        #     |/ \|     # E is the LCA for G & H, and the unique LCA for
        #     G   H     # I, J
        #     |\ /|
        #     | X |
        #     |/ \|
        #     I   J     # criss-cross merge of G, H
        #
        # In this situation, a simple pruning of ancestors of E will leave D &
        # F "dangling", which looks like they introduce lines different from
        # the ones in E, but in actuality C&B introduced the lines, and they
        # are already present in E

        # Introduce the base text
        self.add_rev(b"root", b"A", [], b"abc")
        # Introduces a new line B
        self.add_rev(b"root", b"B", [b"A"], b"aBbc")
        # Introduces a new line C
        self.add_rev(b"root", b"C", [b"A"], b"abCc")
        # Introduce new line D
        self.add_rev(b"root", b"D", [b"B"], b"DaBbc")
        # Merges B and C by just incorporating both
        self.add_rev(b"root", b"E", [b"B", b"C"], b"aBbCc")
        # Introduce new line F
        self.add_rev(b"root", b"F", [b"C"], b"abCcF")
        # Merge D & E by just combining the texts
        self.add_rev(b"root", b"G", [b"D", b"E"], b"DaBbCc")
        # Merge F & E by just combining the texts
        self.add_rev(b"root", b"H", [b"F", b"E"], b"aBbCcF")
        # Merge G & H by just combining texts
        self.add_rev(b"root", b"I", [b"G", b"H"], b"DaBbCcF")
        # Merge G & H but supersede an old line in B
        self.add_rev(b"root", b"J", [b"H", b"G"], b"DaJbCcF")
        plan = self.plan_merge_vf.plan_merge(b"I", b"J")
        self.assertEqual(
            [
                ("unchanged", b"D\n"),
                ("unchanged", b"a\n"),
                ("killed-b", b"B\n"),
                ("new-b", b"J\n"),
                ("unchanged", b"b\n"),
                ("unchanged", b"C\n"),
                ("unchanged", b"c\n"),
                ("unchanged", b"F\n"),
            ],
            list(plan),
        )

    def test_plan_merge_tail_triple_ancestors(self):
        # The graph looks like this:
        #       A       # Common to all ancestors
        #      / \
        #     B   C     # Ancestors of E, only common to one side
        #     |\ /|
        #     D E F     # D, F are unique to G, H respectively
        #     |/|\|     # E is the LCA for G & H, and the unique LCA for
        #     G Q H     # I, J
        #     |\ /|     # Q is just an extra node which is merged into both
        #     | X |     # I and J
        #     |/ \|
        #     I   J     # criss-cross merge of G, H
        #
        # This is the same as the test_plan_merge_tail_ancestors, except we add
        # a third LCA that doesn't add new lines, but will trigger our more
        # involved ancestry logic

        self.add_rev(b"root", b"A", [], b"abc")
        self.add_rev(b"root", b"B", [b"A"], b"aBbc")
        self.add_rev(b"root", b"C", [b"A"], b"abCc")
        self.add_rev(b"root", b"D", [b"B"], b"DaBbc")
        self.add_rev(b"root", b"E", [b"B", b"C"], b"aBbCc")
        self.add_rev(b"root", b"F", [b"C"], b"abCcF")
        self.add_rev(b"root", b"G", [b"D", b"E"], b"DaBbCc")
        self.add_rev(b"root", b"H", [b"F", b"E"], b"aBbCcF")
        self.add_rev(b"root", b"Q", [b"E"], b"aBbCc")
        self.add_rev(b"root", b"I", [b"G", b"Q", b"H"], b"DaBbCcF")
        # Merge G & H but supersede an old line in B
        self.add_rev(b"root", b"J", [b"H", b"Q", b"G"], b"DaJbCcF")
        plan = self.plan_merge_vf.plan_merge(b"I", b"J")
        self.assertEqual(
            [
                ("unchanged", b"D\n"),
                ("unchanged", b"a\n"),
                ("killed-b", b"B\n"),
                ("new-b", b"J\n"),
                ("unchanged", b"b\n"),
                ("unchanged", b"C\n"),
                ("unchanged", b"c\n"),
                ("unchanged", b"F\n"),
            ],
            list(plan),
        )

    def test_plan_merge_2_tail_triple_ancestors(self):
        # The graph looks like this:
        #     A   B     # 2 tails going back to NULL
        #     |\ /|
        #     D E F     # D, is unique to G, F to H
        #     |/|\|     # E is the LCA for G & H, and the unique LCA for
        #     G Q H     # I, J
        #     |\ /|     # Q is just an extra node which is merged into both
        #     | X |     # I and J
        #     |/ \|
        #     I   J     # criss-cross merge of G, H (and Q)
        #

        # This is meant to test after hitting a 3-way LCA, and multiple tail
        # ancestors (only have NULL_REVISION in common)

        self.add_rev(b"root", b"A", [], b"abc")
        self.add_rev(b"root", b"B", [], b"def")
        self.add_rev(b"root", b"D", [b"A"], b"Dabc")
        self.add_rev(b"root", b"E", [b"A", b"B"], b"abcdef")
        self.add_rev(b"root", b"F", [b"B"], b"defF")
        self.add_rev(b"root", b"G", [b"D", b"E"], b"Dabcdef")
        self.add_rev(b"root", b"H", [b"F", b"E"], b"abcdefF")
        self.add_rev(b"root", b"Q", [b"E"], b"abcdef")
        self.add_rev(b"root", b"I", [b"G", b"Q", b"H"], b"DabcdefF")
        # Merge G & H but supersede an old line in B
        self.add_rev(b"root", b"J", [b"H", b"Q", b"G"], b"DabcdJfF")
        plan = self.plan_merge_vf.plan_merge(b"I", b"J")
        self.assertEqual(
            [
                ("unchanged", b"D\n"),
                ("unchanged", b"a\n"),
                ("unchanged", b"b\n"),
                ("unchanged", b"c\n"),
                ("unchanged", b"d\n"),
                ("killed-b", b"e\n"),
                ("new-b", b"J\n"),
                ("unchanged", b"f\n"),
                ("unchanged", b"F\n"),
            ],
            list(plan),
        )

    def test_plan_merge_uncommitted_files(self):
        self.setup_plan_merge_uncommitted()
        plan = self.plan_merge_vf.plan_merge(b"B:", b"C:")
        self.assertEqual(
            [
                ("new-b", b"f\n"),
                ("unchanged", b"a\n"),
                ("killed-a", b"b\n"),
                ("killed-b", b"c\n"),
                ("new-a", b"e\n"),
                ("new-a", b"h\n"),
                ("new-a", b"g\n"),
                ("new-b", b"g\n"),
            ],
            list(plan),
        )

    def test_plan_merge_insert_order(self):
        """Weave merges are sensitive to the order of insertion.

        Specifically for overlapping regions, it effects which region gets put
        'first'. And when a user resolves an overlapping merge, if they use the
        same ordering, then the lines match the parents, if they don't only
        *some* of the lines match.
        """
        self.add_rev(b"root", b"A", [], b"abcdef")
        self.add_rev(b"root", b"B", [b"A"], b"abwxcdef")
        self.add_rev(b"root", b"C", [b"A"], b"abyzcdef")
        # Merge, and resolve the conflict by adding *both* sets of lines
        # If we get the ordering wrong, these will look like new lines in D,
        # rather than carried over from B, C
        self.add_rev(b"root", b"D", [b"B", b"C"], b"abwxyzcdef")
        # Supersede the lines in B and delete the lines in C, which will
        # conflict if they are treated as being in D
        self.add_rev(b"root", b"E", [b"C", b"B"], b"abnocdef")
        # Same thing for the lines in C
        self.add_rev(b"root", b"F", [b"C"], b"abpqcdef")
        plan = self.plan_merge_vf.plan_merge(b"D", b"E")
        self.assertEqual(
            [
                ("unchanged", b"a\n"),
                ("unchanged", b"b\n"),
                ("killed-b", b"w\n"),
                ("killed-b", b"x\n"),
                ("killed-b", b"y\n"),
                ("killed-b", b"z\n"),
                ("new-b", b"n\n"),
                ("new-b", b"o\n"),
                ("unchanged", b"c\n"),
                ("unchanged", b"d\n"),
                ("unchanged", b"e\n"),
                ("unchanged", b"f\n"),
            ],
            list(plan),
        )
        plan = self.plan_merge_vf.plan_merge(b"E", b"D")
        # Going in the opposite direction shows the effect of the opposite plan
        self.assertEqual(
            [
                ("unchanged", b"a\n"),
                ("unchanged", b"b\n"),
                ("new-b", b"w\n"),
                ("new-b", b"x\n"),
                ("killed-a", b"y\n"),
                ("killed-a", b"z\n"),
                ("killed-both", b"w\n"),
                ("killed-both", b"x\n"),
                ("new-a", b"n\n"),
                ("new-a", b"o\n"),
                ("unchanged", b"c\n"),
                ("unchanged", b"d\n"),
                ("unchanged", b"e\n"),
                ("unchanged", b"f\n"),
            ],
            list(plan),
        )

    def test_plan_merge_criss_cross(self):
        # This is specificly trying to trigger problems when using limited
        # ancestry and weaves. The ancestry graph looks like:
        #       XX      unused ancestor, should not show up in the weave
        #       |
        #       A       Unique LCA
        #       |\
        #       B \     Introduces a line 'foo'
        #      / \ \
        #     C   D E   C & D both have 'foo', E has different changes
        #     |\ /| |
        #     | X | |
        #     |/ \|/
        #     F   G      All of C, D, E are merged into F and G, so they are
        #                all common ancestors.
        #
        # The specific issue with weaves:
        #   B introduced a text ('foo') that is present in both C and D.
        #   If we do not include B (because it isn't an ancestor of E), then
        #   the A=>C and A=>D look like both sides independently introduce the
        #   text ('foo'). If F does not modify the text, it would still appear
        #   to have deleted on of the versions from C or D. If G then modifies
        #   'foo', it should appear as superseding the value in F (since it
        #   came from B), rather than conflict because of the resolution during
        #   C & D.
        self.add_rev(b"root", b"XX", [], b"qrs")
        self.add_rev(b"root", b"A", [b"XX"], b"abcdef")
        self.add_rev(b"root", b"B", [b"A"], b"axcdef")
        self.add_rev(b"root", b"C", [b"B"], b"axcdefg")
        self.add_rev(b"root", b"D", [b"B"], b"haxcdef")
        self.add_rev(b"root", b"E", [b"A"], b"abcdyf")
        # Simple combining of all texts
        self.add_rev(b"root", b"F", [b"C", b"D", b"E"], b"haxcdyfg")
        # combine and supersede 'x'
        self.add_rev(b"root", b"G", [b"C", b"D", b"E"], b"hazcdyfg")
        plan = self.plan_merge_vf.plan_merge(b"F", b"G")
        self.assertEqual(
            [
                ("unchanged", b"h\n"),
                ("unchanged", b"a\n"),
                ("killed-base", b"b\n"),
                ("killed-b", b"x\n"),
                ("new-b", b"z\n"),
                ("unchanged", b"c\n"),
                ("unchanged", b"d\n"),
                ("killed-base", b"e\n"),
                ("unchanged", b"y\n"),
                ("unchanged", b"f\n"),
                ("unchanged", b"g\n"),
            ],
            list(plan),
        )
        plan = self.plan_merge_vf.plan_lca_merge(b"F", b"G")
        # This is one of the main differences between plan_merge and
        # plan_lca_merge. plan_lca_merge generates a conflict for 'x => z',
        # because 'x' was not present in one of the bases. However, in this
        # case it is spurious because 'x' does not exist in the global base A.
        self.assertEqual(
            [
                ("unchanged", b"h\n"),
                ("unchanged", b"a\n"),
                ("conflicted-a", b"x\n"),
                ("new-b", b"z\n"),
                ("unchanged", b"c\n"),
                ("unchanged", b"d\n"),
                ("unchanged", b"y\n"),
                ("unchanged", b"f\n"),
                ("unchanged", b"g\n"),
            ],
            list(plan),
        )

    def test_criss_cross_flip_flop(self):
        # This is specificly trying to trigger problems when using limited
        # ancestry and weaves. The ancestry graph looks like:
        #       XX      unused ancestor, should not show up in the weave
        #       |
        #       A       Unique LCA
        #      / \
        #     B   C     B & C both introduce a new line
        #     |\ /|
        #     | X |
        #     |/ \|
        #     D   E     B & C are both merged, so both are common ancestors
        #               In the process of merging, both sides order the new
        #               lines differently
        #
        self.add_rev(b"root", b"XX", [], b"qrs")
        self.add_rev(b"root", b"A", [b"XX"], b"abcdef")
        self.add_rev(b"root", b"B", [b"A"], b"abcdgef")
        self.add_rev(b"root", b"C", [b"A"], b"abcdhef")
        self.add_rev(b"root", b"D", [b"B", b"C"], b"abcdghef")
        self.add_rev(b"root", b"E", [b"C", b"B"], b"abcdhgef")
        plan = list(self.plan_merge_vf.plan_merge(b"D", b"E"))
        self.assertEqual(
            [
                ("unchanged", b"a\n"),
                ("unchanged", b"b\n"),
                ("unchanged", b"c\n"),
                ("unchanged", b"d\n"),
                ("new-b", b"h\n"),
                ("unchanged", b"g\n"),
                ("killed-b", b"h\n"),
                ("unchanged", b"e\n"),
                ("unchanged", b"f\n"),
            ],
            plan,
        )
        pwm = versionedfile.PlanWeaveMerge(plan)
        self.assertEqualDiff(
            b"a\nb\nc\nd\ng\nh\ne\nf\n", b"".join(pwm.base_from_plan())
        )
        # Reversing the order reverses the merge plan, and final order of 'hg'
        # => 'gh'
        plan = list(self.plan_merge_vf.plan_merge(b"E", b"D"))
        self.assertEqual(
            [
                ("unchanged", b"a\n"),
                ("unchanged", b"b\n"),
                ("unchanged", b"c\n"),
                ("unchanged", b"d\n"),
                ("new-b", b"g\n"),
                ("unchanged", b"h\n"),
                ("killed-b", b"g\n"),
                ("unchanged", b"e\n"),
                ("unchanged", b"f\n"),
            ],
            plan,
        )
        pwm = versionedfile.PlanWeaveMerge(plan)
        self.assertEqualDiff(
            b"a\nb\nc\nd\nh\ng\ne\nf\n", b"".join(pwm.base_from_plan())
        )
        # This is where lca differs, in that it (fairly correctly) determines
        # that there is a conflict because both sides resolved the merge
        # differently
        plan = list(self.plan_merge_vf.plan_lca_merge(b"D", b"E"))
        self.assertEqual(
            [
                ("unchanged", b"a\n"),
                ("unchanged", b"b\n"),
                ("unchanged", b"c\n"),
                ("unchanged", b"d\n"),
                ("conflicted-b", b"h\n"),
                ("unchanged", b"g\n"),
                ("conflicted-a", b"h\n"),
                ("unchanged", b"e\n"),
                ("unchanged", b"f\n"),
            ],
            plan,
        )
        pwm = versionedfile.PlanWeaveMerge(plan)
        self.assertEqualDiff(b"a\nb\nc\nd\ng\ne\nf\n", b"".join(pwm.base_from_plan()))
        # Reversing it changes what line is doubled, but still gives a
        # double-conflict
        plan = list(self.plan_merge_vf.plan_lca_merge(b"E", b"D"))
        self.assertEqual(
            [
                ("unchanged", b"a\n"),
                ("unchanged", b"b\n"),
                ("unchanged", b"c\n"),
                ("unchanged", b"d\n"),
                ("conflicted-b", b"g\n"),
                ("unchanged", b"h\n"),
                ("conflicted-a", b"g\n"),
                ("unchanged", b"e\n"),
                ("unchanged", b"f\n"),
            ],
            plan,
        )
        pwm = versionedfile.PlanWeaveMerge(plan)
        self.assertEqualDiff(b"a\nb\nc\nd\nh\ne\nf\n", b"".join(pwm.base_from_plan()))

    def assertRemoveExternalReferences(
        self, filtered_parent_map, child_map, tails, parent_map
    ):
        """Assert results for _PlanMerge._remove_external_references."""
        (
            act_filtered_parent_map,
            act_child_map,
            act_tails,
        ) = _PlanMerge._remove_external_references(parent_map)

        # The parent map *should* preserve ordering, but the ordering of
        # children is not strictly defined
        # child_map = dict((k, sorted(children))
        #                  for k, children in child_map.iteritems())
        # act_child_map = dict(k, sorted(children)
        #                      for k, children in act_child_map.iteritems())
        self.assertEqual(filtered_parent_map, act_filtered_parent_map)
        self.assertEqual(child_map, act_child_map)
        self.assertEqual(sorted(tails), sorted(act_tails))

    def test__remove_external_references(self):
        # First, nothing to remove
        self.assertRemoveExternalReferences(
            {3: [2], 2: [1], 1: []},
            {1: [2], 2: [3], 3: []},
            [1],
            {3: [2], 2: [1], 1: []},
        )
        # The reverse direction
        self.assertRemoveExternalReferences(
            {1: [2], 2: [3], 3: []},
            {3: [2], 2: [1], 1: []},
            [3],
            {1: [2], 2: [3], 3: []},
        )
        # Extra references
        self.assertRemoveExternalReferences(
            {3: [2], 2: [1], 1: []},
            {1: [2], 2: [3], 3: []},
            [1],
            {3: [2, 4], 2: [1, 5], 1: [6]},
        )
        # Multiple tails
        self.assertRemoveExternalReferences(
            {4: [2, 3], 3: [], 2: [1], 1: []},
            {1: [2], 2: [4], 3: [4], 4: []},
            [1, 3],
            {4: [2, 3], 3: [5], 2: [1], 1: [6]},
        )
        # Multiple children
        self.assertRemoveExternalReferences(
            {1: [3], 2: [3, 4], 3: [], 4: []},
            {1: [], 2: [], 3: [1, 2], 4: [2]},
            [3, 4],
            {1: [3], 2: [3, 4], 3: [5], 4: []},
        )

    def assertPruneTails(self, pruned_map, tails, parent_map):
        child_map = {}
        for key, parent_keys in parent_map.items():
            child_map.setdefault(key, [])
            for pkey in parent_keys:
                child_map.setdefault(pkey, []).append(key)
        _PlanMerge._prune_tails(parent_map, child_map, tails)
        self.assertEqual(pruned_map, parent_map)

    def test__prune_tails(self):
        # Nothing requested to prune
        self.assertPruneTails({1: [], 2: [], 3: []}, [], {1: [], 2: [], 3: []})
        # Prune a single entry
        self.assertPruneTails({1: [], 3: []}, [2], {1: [], 2: [], 3: []})
        # Prune a chain
        self.assertPruneTails({1: []}, [3], {1: [], 2: [3], 3: []})
        # Prune a chain with a diamond
        self.assertPruneTails({1: []}, [5], {1: [], 2: [3, 4], 3: [5], 4: [5], 5: []})
        # Prune a partial chain
        self.assertPruneTails(
            {1: [6], 6: []}, [5], {1: [2, 6], 2: [3, 4], 3: [5], 4: [5], 5: [], 6: []}
        )
        # Prune a chain with multiple tips, that pulls out intermediates
        self.assertPruneTails(
            {1: [3], 3: []}, [4, 5], {1: [2, 3], 2: [4, 5], 3: [], 4: [], 5: []}
        )
        self.assertPruneTails(
            {1: [3], 3: []}, [5, 4], {1: [2, 3], 2: [4, 5], 3: [], 4: [], 5: []}
        )

    def test_subtract_plans(self):
        old_plan = [
            ("unchanged", b"a\n"),
            ("new-a", b"b\n"),
            ("killed-a", b"c\n"),
            ("new-b", b"d\n"),
            ("new-b", b"e\n"),
            ("killed-b", b"f\n"),
            ("killed-b", b"g\n"),
        ]
        new_plan = [
            ("unchanged", b"a\n"),
            ("new-a", b"b\n"),
            ("killed-a", b"c\n"),
            ("new-b", b"d\n"),
            ("new-b", b"h\n"),
            ("killed-b", b"f\n"),
            ("killed-b", b"i\n"),
        ]
        subtracted_plan = [
            ("unchanged", b"a\n"),
            ("new-a", b"b\n"),
            ("killed-a", b"c\n"),
            ("new-b", b"h\n"),
            ("unchanged", b"f\n"),
            ("killed-b", b"i\n"),
        ]
        self.assertEqual(
            subtracted_plan, list(_PlanMerge._subtract_plans(old_plan, new_plan))
        )

    def setup_merge_with_base(self):
        self.add_rev(b"root", b"COMMON", [], b"abc")
        self.add_rev(b"root", b"THIS", [b"COMMON"], b"abcd")
        self.add_rev(b"root", b"BASE", [b"COMMON"], b"eabc")
        self.add_rev(b"root", b"OTHER", [b"BASE"], b"eafb")

    def test_plan_merge_with_base(self):
        self.setup_merge_with_base()
        plan = self.plan_merge_vf.plan_merge(b"THIS", b"OTHER", b"BASE")
        self.assertEqual(
            [
                ("unchanged", b"a\n"),
                ("new-b", b"f\n"),
                ("unchanged", b"b\n"),
                ("killed-b", b"c\n"),
                ("new-a", b"d\n"),
            ],
            list(plan),
        )

    def test_plan_lca_merge(self):
        self.setup_plan_merge()
        plan = self.plan_merge_vf.plan_lca_merge(b"B", b"C")
        self.assertEqual(
            [
                ("new-b", b"f\n"),
                ("unchanged", b"a\n"),
                ("killed-b", b"c\n"),
                ("new-a", b"e\n"),
                ("new-a", b"h\n"),
                ("killed-a", b"b\n"),
                ("unchanged", b"g\n"),
            ],
            list(plan),
        )

    def test_plan_lca_merge_uncommitted_files(self):
        self.setup_plan_merge_uncommitted()
        plan = self.plan_merge_vf.plan_lca_merge(b"B:", b"C:")
        self.assertEqual(
            [
                ("new-b", b"f\n"),
                ("unchanged", b"a\n"),
                ("killed-b", b"c\n"),
                ("new-a", b"e\n"),
                ("new-a", b"h\n"),
                ("killed-a", b"b\n"),
                ("unchanged", b"g\n"),
            ],
            list(plan),
        )

    def test_plan_lca_merge_with_base(self):
        self.setup_merge_with_base()
        plan = self.plan_merge_vf.plan_lca_merge(b"THIS", b"OTHER", b"BASE")
        self.assertEqual(
            [
                ("unchanged", b"a\n"),
                ("new-b", b"f\n"),
                ("unchanged", b"b\n"),
                ("killed-b", b"c\n"),
                ("new-a", b"d\n"),
            ],
            list(plan),
        )

    def test_plan_lca_merge_with_criss_cross(self):
        self.add_version((b"root", b"ROOT"), [], b"abc")
        # each side makes a change
        self.add_version((b"root", b"REV1"), [(b"root", b"ROOT")], b"abcd")
        self.add_version((b"root", b"REV2"), [(b"root", b"ROOT")], b"abce")
        # both sides merge, discarding others' changes
        self.add_version(
            (b"root", b"LCA1"), [(b"root", b"REV1"), (b"root", b"REV2")], b"abcd"
        )
        self.add_version(
            (b"root", b"LCA2"), [(b"root", b"REV1"), (b"root", b"REV2")], b"fabce"
        )
        plan = self.plan_merge_vf.plan_lca_merge(b"LCA1", b"LCA2")
        self.assertEqual(
            [
                ("new-b", b"f\n"),
                ("unchanged", b"a\n"),
                ("unchanged", b"b\n"),
                ("unchanged", b"c\n"),
                ("conflicted-a", b"d\n"),
                ("conflicted-b", b"e\n"),
            ],
            list(plan),
        )

    def test_plan_lca_merge_with_null(self):
        self.add_version((b"root", b"A"), [], b"ab")
        self.add_version((b"root", b"B"), [], b"bc")
        plan = self.plan_merge_vf.plan_lca_merge(b"A", b"B")
        self.assertEqual(
            [
                ("new-a", b"a\n"),
                ("unchanged", b"b\n"),
                ("new-b", b"c\n"),
            ],
            list(plan),
        )

    def test_plan_merge_with_delete_and_change(self):
        self.add_rev(b"root", b"C", [], b"a")
        self.add_rev(b"root", b"A", [b"C"], b"b")
        self.add_rev(b"root", b"B", [b"C"], b"")
        plan = self.plan_merge_vf.plan_merge(b"A", b"B")
        self.assertEqual(
            [
                ("killed-both", b"a\n"),
                ("new-a", b"b\n"),
            ],
            list(plan),
        )

    def test_plan_merge_with_move_and_change(self):
        self.add_rev(b"root", b"C", [], b"abcd")
        self.add_rev(b"root", b"A", [b"C"], b"acbd")
        self.add_rev(b"root", b"B", [b"C"], b"aBcd")
        plan = self.plan_merge_vf.plan_merge(b"A", b"B")
        self.assertEqual(
            [
                ("unchanged", b"a\n"),
                ("new-a", b"c\n"),
                ("killed-b", b"b\n"),
                ("new-b", b"B\n"),
                ("killed-a", b"c\n"),
                ("unchanged", b"d\n"),
            ],
            list(plan),
        )


class LoggingMerger:
    # These seem to be the required attributes
    requires_base = False
    supports_reprocess = False
    supports_show_base = False
    supports_cherrypick = False
    # We intentionally do not define supports_lca_trees

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


class TestMergerBase(TestCaseWithMemoryTransport):
    """Common functionality for Merger tests that don't write to disk."""

    def get_builder(self):
        builder = self.make_branch_builder("path")
        builder.start_series()
        self.addCleanup(builder.finish_series)
        return builder

    def setup_simple_graph(self):
        """Create a simple 3-node graph.

        :return: A BranchBuilder
        """
        #
        #  A
        #  |\
        #  B C
        #
        builder = self.get_builder()
        builder.build_snapshot(
            None, [("add", ("", None, "directory", None))], revision_id=b"A-id"
        )
        builder.build_snapshot([b"A-id"], [], revision_id=b"C-id")
        builder.build_snapshot([b"A-id"], [], revision_id=b"B-id")
        return builder

    def setup_criss_cross_graph(self):
        """Create a 5-node graph with a criss-cross.

        :return: A BranchBuilder
        """
        # A
        # |\
        # B C
        # |X|
        # D E
        builder = self.setup_simple_graph()
        builder.build_snapshot([b"C-id", b"B-id"], [], revision_id=b"E-id")
        builder.build_snapshot([b"B-id", b"C-id"], [], revision_id=b"D-id")
        return builder

    def make_Merger(self, builder, other_revision_id, interesting_files=None):
        """Make a Merger object from a branch builder."""
        mem_tree = memorytree.MemoryTree.create_on_branch(builder.get_branch())
        mem_tree.lock_write()
        self.addCleanup(mem_tree.unlock)
        merger = _mod_merge.Merger.from_revision_ids(mem_tree, other_revision_id)
        merger.set_interesting_files(interesting_files)
        merger.merge_type = _mod_merge.Merge3Merger
        return merger


class TestMergerInMemory(TestMergerBase):
    def test_cache_trees_with_revision_ids_None(self):
        merger = self.make_Merger(self.setup_simple_graph(), b"C-id")
        original_cache = dict(merger._cached_trees)
        merger.cache_trees_with_revision_ids([None])
        self.assertEqual(original_cache, merger._cached_trees)

    def test_cache_trees_with_revision_ids_no_revision_id(self):
        merger = self.make_Merger(self.setup_simple_graph(), b"C-id")
        original_cache = dict(merger._cached_trees)
        tree = self.make_branch_and_memory_tree("tree")
        merger.cache_trees_with_revision_ids([tree])
        self.assertEqual(original_cache, merger._cached_trees)

    def test_cache_trees_with_revision_ids_having_revision_id(self):
        merger = self.make_Merger(self.setup_simple_graph(), b"C-id")
        original_cache = dict(merger._cached_trees)
        tree = merger.this_branch.repository.revision_tree(b"B-id")
        original_cache[b"B-id"] = tree
        merger.cache_trees_with_revision_ids([tree])
        self.assertEqual(original_cache, merger._cached_trees)

    def test_find_base(self):
        merger = self.make_Merger(self.setup_simple_graph(), b"C-id")
        self.assertEqual(b"A-id", merger.base_rev_id)
        self.assertFalse(merger._is_criss_cross)
        self.assertIs(None, merger._lca_trees)

    def test_find_base_criss_cross(self):
        builder = self.setup_criss_cross_graph()
        merger = self.make_Merger(builder, b"E-id")
        self.assertEqual(b"A-id", merger.base_rev_id)
        self.assertTrue(merger._is_criss_cross)
        self.assertEqual(
            [b"B-id", b"C-id"], [t.get_revision_id() for t in merger._lca_trees]
        )
        # If we swap the order, we should get a different lca order
        builder.build_snapshot([b"E-id"], [], revision_id=b"F-id")
        merger = self.make_Merger(builder, b"D-id")
        self.assertEqual(
            [b"C-id", b"B-id"], [t.get_revision_id() for t in merger._lca_trees]
        )

    def test_find_base_triple_criss_cross(self):
        #       A-.
        #      / \ \
        #     B   C F # F is merged into both branches
        #     |\ /| |
        #     | X | |\
        #     |/ \| | :
        #   : D   E |
        #    \|   |/
        #     G   H
        builder = self.setup_criss_cross_graph()
        builder.build_snapshot([b"A-id"], [], revision_id=b"F-id")
        builder.build_snapshot([b"E-id", b"F-id"], [], revision_id=b"H-id")
        builder.build_snapshot([b"D-id", b"F-id"], [], revision_id=b"G-id")
        merger = self.make_Merger(builder, b"H-id")
        self.assertEqual(
            [b"B-id", b"C-id", b"F-id"],
            [t.get_revision_id() for t in merger._lca_trees],
        )

    def test_find_base_new_root_criss_cross(self):
        # A   B
        # |\ /|
        # | X |
        # |/ \|
        # C   D
        builder = self.get_builder()
        builder.build_snapshot(
            None, [("add", ("", None, "directory", None))], revision_id=b"A-id"
        )
        builder.build_snapshot(
            [], [("add", ("", None, "directory", None))], revision_id=b"B-id"
        )
        builder.build_snapshot([b"A-id", b"B-id"], [], revision_id=b"D-id")
        builder.build_snapshot([b"A-id", b"B-id"], [], revision_id=b"C-id")
        merger = self.make_Merger(builder, b"D-id")
        self.assertEqual(b"A-id", merger.base_rev_id)
        self.assertTrue(merger._is_criss_cross)
        self.assertEqual(
            [b"A-id", b"B-id"], [t.get_revision_id() for t in merger._lca_trees]
        )

    def test_no_criss_cross_passed_to_merge_type(self):
        class LCATreesMerger(LoggingMerger):
            supports_lca_trees = True

        merger = self.make_Merger(self.setup_simple_graph(), b"C-id")
        merger.merge_type = LCATreesMerger
        merge_obj = merger.make_merger()
        self.assertIsInstance(merge_obj, LCATreesMerger)
        self.assertNotIn("lca_trees", merge_obj.kwargs)

    def test_criss_cross_passed_to_merge_type(self):
        merger = self.make_Merger(self.setup_criss_cross_graph(), b"E-id")
        merger.merge_type = _mod_merge.Merge3Merger
        merger.make_merger()
        self.assertEqual(
            [b"B-id", b"C-id"], [t.get_revision_id() for t in merger._lca_trees]
        )

    def test_criss_cross_not_supported_merge_type(self):
        merger = self.make_Merger(self.setup_criss_cross_graph(), b"E-id")
        # We explicitly do not define supports_lca_trees
        merger.merge_type = LoggingMerger
        merge_obj = merger.make_merger()
        self.assertIsInstance(merge_obj, LoggingMerger)
        self.assertNotIn("lca_trees", merge_obj.kwargs)

    def test_criss_cross_unsupported_merge_type(self):
        class UnsupportedLCATreesMerger(LoggingMerger):
            supports_lca_trees = False

        merger = self.make_Merger(self.setup_criss_cross_graph(), b"E-id")
        merger.merge_type = UnsupportedLCATreesMerger
        merge_obj = merger.make_merger()
        self.assertIsInstance(merge_obj, UnsupportedLCATreesMerger)
        self.assertNotIn("lca_trees", merge_obj.kwargs)


class TestMergerEntriesLCA(TestMergerBase):
    def make_merge_obj(self, builder, other_revision_id, interesting_files=None):
        merger = self.make_Merger(
            builder, other_revision_id, interesting_files=interesting_files
        )
        return merger.make_merger()

    def test_simple(self):
        builder = self.get_builder()
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"a-root-id", "directory", None)),
                ("add", ("a", b"a-id", "file", b"a\nb\nc\n")),
            ],
            revision_id=b"A-id",
        )
        builder.build_snapshot(
            [b"A-id"], [("modify", ("a", b"a\nb\nC\nc\n"))], revision_id=b"C-id"
        )
        builder.build_snapshot(
            [b"A-id"], [("modify", ("a", b"a\nB\nb\nc\n"))], revision_id=b"B-id"
        )
        builder.build_snapshot(
            [b"C-id", b"B-id"],
            [("modify", ("a", b"a\nB\nb\nC\nc\nE\n"))],
            revision_id=b"E-id",
        )
        builder.build_snapshot(
            [b"B-id", b"C-id"],
            [("modify", ("a", b"a\nB\nb\nC\nc\n"))],
            revision_id=b"D-id",
        )
        merge_obj = self.make_merge_obj(builder, b"E-id")

        self.assertEqual(
            [b"B-id", b"C-id"], [t.get_revision_id() for t in merge_obj._lca_trees]
        )
        self.assertEqual(b"A-id", merge_obj.base_tree.get_revision_id())
        entries = list(merge_obj._entries_lca())

        # (file_id, changed, parents, names, executable)
        # BASE, lca1, lca2, OTHER, THIS
        root_id = b"a-root-id"
        self.assertEqual(
            [
                (
                    b"a-id",
                    True,
                    (("a", ["a", "a"]), "a", "a"),
                    ((root_id, [root_id, root_id]), root_id, root_id),
                    (("a", ["a", "a"]), "a", "a"),
                    ((False, [False, False]), False, False),
                    False,
                ),
            ],
            entries,
        )

    def test_not_in_base(self):
        # LCAs all have the same last-modified revision for the file, as do
        # the tips, but the base has something different
        #       A    base, doesn't have the file
        #       |\
        #       B C  B introduces 'foo', C introduces 'bar'
        #       |X|
        #       D E  D and E now both have 'foo' and 'bar'
        #       |X|
        #       F G  the files are now in F, G, D and E, but not in A
        #            G modifies 'bar'

        builder = self.get_builder()
        builder.build_snapshot(
            None, [("add", ("", b"a-root-id", "directory", None))], revision_id=b"A-id"
        )
        builder.build_snapshot(
            [b"A-id"],
            [("add", ("foo", b"foo-id", "file", b"a\nb\nc\n"))],
            revision_id=b"B-id",
        )
        builder.build_snapshot(
            [b"A-id"],
            [("add", ("bar", b"bar-id", "file", b"d\ne\nf\n"))],
            revision_id=b"C-id",
        )
        builder.build_snapshot(
            [b"B-id", b"C-id"],
            [("add", ("bar", b"bar-id", "file", b"d\ne\nf\n"))],
            revision_id=b"D-id",
        )
        builder.build_snapshot(
            [b"C-id", b"B-id"],
            [("add", ("foo", b"foo-id", "file", b"a\nb\nc\n"))],
            revision_id=b"E-id",
        )
        builder.build_snapshot(
            [b"E-id", b"D-id"],
            [("modify", ("bar", b"d\ne\nf\nG\n"))],
            revision_id=b"G-id",
        )
        builder.build_snapshot([b"D-id", b"E-id"], [], revision_id=b"F-id")
        merge_obj = self.make_merge_obj(builder, b"G-id")

        self.assertEqual(
            [b"D-id", b"E-id"], [t.get_revision_id() for t in merge_obj._lca_trees]
        )
        self.assertEqual(b"A-id", merge_obj.base_tree.get_revision_id())
        entries = list(merge_obj._entries_lca())
        root_id = b"a-root-id"
        self.assertEqual(
            [
                (
                    b"bar-id",
                    True,
                    ((None, ["bar", "bar"]), "bar", "bar"),
                    ((None, [root_id, root_id]), root_id, root_id),
                    ((None, ["bar", "bar"]), "bar", "bar"),
                    ((None, [False, False]), False, False),
                    False,
                ),
            ],
            entries,
        )

    def test_not_in_this(self):
        builder = self.get_builder()
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"a-root-id", "directory", None)),
                ("add", ("a", b"a-id", "file", b"a\nb\nc\n")),
            ],
            revision_id=b"A-id",
        )
        builder.build_snapshot(
            [b"A-id"], [("modify", ("a", b"a\nB\nb\nc\n"))], revision_id=b"B-id"
        )
        builder.build_snapshot(
            [b"A-id"], [("modify", ("a", b"a\nb\nC\nc\n"))], revision_id=b"C-id"
        )
        builder.build_snapshot(
            [b"C-id", b"B-id"],
            [("modify", ("a", b"a\nB\nb\nC\nc\nE\n"))],
            revision_id=b"E-id",
        )
        builder.build_snapshot(
            [b"B-id", b"C-id"], [("unversion", "a")], revision_id=b"D-id"
        )
        merge_obj = self.make_merge_obj(builder, b"E-id")

        self.assertEqual(
            [b"B-id", b"C-id"], [t.get_revision_id() for t in merge_obj._lca_trees]
        )
        self.assertEqual(b"A-id", merge_obj.base_tree.get_revision_id())

        entries = list(merge_obj._entries_lca())
        root_id = b"a-root-id"
        self.assertEqual(
            [
                (
                    b"a-id",
                    True,
                    (("a", ["a", "a"]), "a", None),
                    ((root_id, [root_id, root_id]), root_id, None),
                    (("a", ["a", "a"]), "a", None),
                    ((False, [False, False]), False, None),
                    False,
                ),
            ],
            entries,
        )

    def test_file_not_in_one_lca(self):
        #   A   # just root
        #   |\
        #   B C # B no file, C introduces a file
        #   |X|
        #   D E # D and E both have the file, unchanged from C
        builder = self.get_builder()
        builder.build_snapshot(
            None, [("add", ("", b"a-root-id", "directory", None))], revision_id=b"A-id"
        )
        builder.build_snapshot([b"A-id"], [], revision_id=b"B-id")
        builder.build_snapshot(
            [b"A-id"],
            [("add", ("a", b"a-id", "file", b"a\nb\nc\n"))],
            revision_id=b"C-id",
        )
        builder.build_snapshot(
            [b"C-id", b"B-id"], [], revision_id=b"E-id"
        )  # Inherited from C
        builder.build_snapshot(
            [b"B-id", b"C-id"],  # Merged from C
            [("add", ("a", b"a-id", "file", b"a\nb\nc\n"))],
            revision_id=b"D-id",
        )
        merge_obj = self.make_merge_obj(builder, b"E-id")

        self.assertEqual(
            [b"B-id", b"C-id"], [t.get_revision_id() for t in merge_obj._lca_trees]
        )
        self.assertEqual(b"A-id", merge_obj.base_tree.get_revision_id())

        entries = list(merge_obj._entries_lca())
        self.assertEqual([], entries)

    def test_not_in_other(self):
        builder = self.get_builder()
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"a-root-id", "directory", None)),
                ("add", ("a", b"a-id", "file", b"a\nb\nc\n")),
            ],
            revision_id=b"A-id",
        )
        builder.build_snapshot([b"A-id"], [], revision_id=b"B-id")
        builder.build_snapshot([b"A-id"], [], revision_id=b"C-id")
        builder.build_snapshot(
            [b"C-id", b"B-id"], [("unversion", "a")], revision_id=b"E-id"
        )
        builder.build_snapshot([b"B-id", b"C-id"], [], revision_id=b"D-id")
        merge_obj = self.make_merge_obj(builder, b"E-id")

        entries = list(merge_obj._entries_lca())
        root_id = b"a-root-id"
        self.assertEqual(
            [
                (
                    b"a-id",
                    True,
                    (("a", ["a", "a"]), None, "a"),
                    ((root_id, [root_id, root_id]), None, root_id),
                    (("a", ["a", "a"]), None, "a"),
                    ((False, [False, False]), None, False),
                    False,
                ),
            ],
            entries,
        )

    def test_not_in_other_or_lca(self):
        #       A    base, introduces 'foo'
        #       |\
        #       B C  B nothing, C deletes foo
        #       |X|
        #       D E  D restores foo (same as B), E leaves it deleted
        # Analysis:
        #   A => B, no changes
        #   A => C, delete foo (C should supersede B)
        #   C => D, restore foo
        #   C => E, no changes
        # D would then win 'cleanly' and no record would be given
        builder = self.get_builder()
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"a-root-id", "directory", None)),
                ("add", ("foo", b"foo-id", "file", b"content\n")),
            ],
            revision_id=b"A-id",
        )
        builder.build_snapshot([b"A-id"], [], revision_id=b"B-id")
        builder.build_snapshot([b"A-id"], [("unversion", "foo")], revision_id=b"C-id")
        builder.build_snapshot([b"C-id", b"B-id"], [], revision_id=b"E-id")
        builder.build_snapshot([b"B-id", b"C-id"], [], revision_id=b"D-id")
        merge_obj = self.make_merge_obj(builder, b"E-id")

        entries = list(merge_obj._entries_lca())
        self.assertEqual([], entries)

    def test_not_in_other_mod_in_lca1_not_in_lca2(self):
        #       A    base, introduces 'foo'
        #       |\
        #       B C  B changes 'foo', C deletes foo
        #       |X|
        #       D E  D restores foo (same as B), E leaves it deleted (as C)
        # Analysis:
        #   A => B, modified foo
        #   A => C, delete foo, C does not supersede B
        #   B => D, no changes
        #   C => D, resolve in favor of B
        #   B => E, resolve in favor of E
        #   C => E, no changes
        # In this case, we have a conflict of how the changes were resolved. E
        # picked C and D picked B, so we should issue a conflict
        builder = self.get_builder()
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"a-root-id", "directory", None)),
                ("add", ("foo", b"foo-id", "file", b"content\n")),
            ],
            revision_id=b"A-id",
        )
        builder.build_snapshot(
            [b"A-id"], [("modify", ("foo", b"new-content\n"))], revision_id=b"B-id"
        )
        builder.build_snapshot([b"A-id"], [("unversion", "foo")], revision_id=b"C-id")
        builder.build_snapshot([b"C-id", b"B-id"], [], revision_id=b"E-id")
        builder.build_snapshot([b"B-id", b"C-id"], [], revision_id=b"D-id")
        merge_obj = self.make_merge_obj(builder, b"E-id")

        entries = list(merge_obj._entries_lca())
        root_id = b"a-root-id"
        self.assertEqual(
            [
                (
                    b"foo-id",
                    True,
                    (("foo", ["foo", None]), None, "foo"),
                    ((root_id, [root_id, None]), None, root_id),
                    (("foo", ["foo", None]), None, "foo"),
                    ((False, [False, None]), None, False),
                    False,
                ),
            ],
            entries,
        )

    def test_only_in_one_lca(self):
        #   A   add only root
        #   |\
        #   B C B nothing, C add file
        #   |X|
        #   D E D still has nothing, E removes file
        # Analysis:
        #   B => D, no change
        #   C => D, removed the file
        #   B => E, no change
        #   C => E, removed the file
        # Thus D & E have identical changes, and this is a no-op
        # Alternatively:
        #   A => B, no change
        #   A => C, add file, thus C supersedes B
        #   w/ C=BASE, D=THIS, E=OTHER we have 'happy convergence'
        builder = self.get_builder()
        builder.build_snapshot(
            None, [("add", ("", b"a-root-id", "directory", None))], revision_id=b"A-id"
        )
        builder.build_snapshot([b"A-id"], [], revision_id=b"B-id")
        builder.build_snapshot(
            [b"A-id"],
            [("add", ("a", b"a-id", "file", b"a\nb\nc\n"))],
            revision_id=b"C-id",
        )
        builder.build_snapshot(
            [b"C-id", b"B-id"], [("unversion", "a")], revision_id=b"E-id"
        )
        builder.build_snapshot([b"B-id", b"C-id"], [], revision_id=b"D-id")
        merge_obj = self.make_merge_obj(builder, b"E-id")

        entries = list(merge_obj._entries_lca())
        self.assertEqual([], entries)

    def test_only_in_other(self):
        builder = self.get_builder()
        builder.build_snapshot(
            None, [("add", ("", b"a-root-id", "directory", None))], revision_id=b"A-id"
        )
        builder.build_snapshot([b"A-id"], [], revision_id=b"B-id")
        builder.build_snapshot([b"A-id"], [], revision_id=b"C-id")
        builder.build_snapshot(
            [b"C-id", b"B-id"],
            [("add", ("a", b"a-id", "file", b"a\nb\nc\n"))],
            revision_id=b"E-id",
        )
        builder.build_snapshot([b"B-id", b"C-id"], [], revision_id=b"D-id")
        merge_obj = self.make_merge_obj(builder, b"E-id")

        entries = list(merge_obj._entries_lca())
        root_id = b"a-root-id"
        self.assertEqual(
            [
                (
                    b"a-id",
                    True,
                    ((None, [None, None]), "a", None),
                    ((None, [None, None]), root_id, None),
                    ((None, [None, None]), "a", None),
                    ((None, [None, None]), False, None),
                    False,
                ),
            ],
            entries,
        )

    def test_one_lca_supersedes(self):
        # One LCA supersedes the other LCAs last modified value, but the
        # value is not the same as BASE.
        #       A    base, introduces 'foo', last mod A
        #       |\
        #       B C  B modifies 'foo' (mod B), C does nothing (mod A)
        #       |X|
        #       D E  D does nothing (mod B), E updates 'foo' (mod E)
        #       |X|
        #       F G  F updates 'foo' (mod F). G does nothing (mod E)
        #
        #   At this point, G should not be considered to modify 'foo', even
        #   though its LCAs disagree. This is because the modification in E
        #   completely supersedes the value in D.
        builder = self.get_builder()
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"a-root-id", "directory", None)),
                ("add", ("foo", b"foo-id", "file", b"A content\n")),
            ],
            revision_id=b"A-id",
        )
        builder.build_snapshot([b"A-id"], [], revision_id=b"C-id")
        builder.build_snapshot(
            [b"A-id"], [("modify", ("foo", b"B content\n"))], revision_id=b"B-id"
        )
        builder.build_snapshot([b"B-id", b"C-id"], [], revision_id=b"D-id")
        builder.build_snapshot(
            [b"C-id", b"B-id"],
            [("modify", ("foo", b"E content\n"))],
            revision_id=b"E-id",
        )
        builder.build_snapshot([b"E-id", b"D-id"], [], revision_id=b"G-id")
        builder.build_snapshot(
            [b"D-id", b"E-id"],
            [("modify", ("foo", b"F content\n"))],
            revision_id=b"F-id",
        )
        merge_obj = self.make_merge_obj(builder, b"G-id")

        self.assertEqual([], list(merge_obj._entries_lca()))

    def test_one_lca_supersedes_path(self):
        # Double-criss-cross merge, the ultimate base value is different from
        # the intermediate.
        #   A    value 'foo'
        #   |\
        #   B C  B value 'bar', C = 'foo'
        #   |X|
        #   D E  D = 'bar', E supersedes to 'bing'
        #   |X|
        #   F G  F = 'bing', G supersedes to 'barry'
        #
        # In this case, we technically should not care about the value 'bar' for
        # D, because it was clearly superseded by E's 'bing'. The
        # per-file/attribute graph would actually look like:
        #   A
        #   |
        #   B
        #   |
        #   E
        #   |
        #   G
        #
        # Because the other side of the merge never modifies the value, it just
        # takes the value from the merge.
        #
        # ATM this fails because we will prune 'foo' from the LCAs, but we
        # won't prune 'bar'. This is getting far off into edge-case land, so we
        # aren't supporting it yet.
        #
        builder = self.get_builder()
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"a-root-id", "directory", None)),
                ("add", ("foo", b"foo-id", "file", b"A content\n")),
            ],
            revision_id=b"A-id",
        )
        builder.build_snapshot([b"A-id"], [], revision_id=b"C-id")
        builder.build_snapshot(
            [b"A-id"], [("rename", ("foo", "bar"))], revision_id=b"B-id"
        )
        builder.build_snapshot([b"B-id", b"C-id"], [], revision_id=b"D-id")
        builder.build_snapshot(
            [b"C-id", b"B-id"], [("rename", ("foo", "bing"))], revision_id=b"E-id"
        )  # override to bing
        builder.build_snapshot(
            [b"E-id", b"D-id"], [("rename", ("bing", "barry"))], revision_id=b"G-id"
        )  # override to barry
        builder.build_snapshot(
            [b"D-id", b"E-id"], [("rename", ("bar", "bing"))], revision_id=b"F-id"
        )  # Merge in E's change
        merge_obj = self.make_merge_obj(builder, b"G-id")

        self.expectFailure(
            "We don't do an actual heads() check on lca values,"
            " or use the per-attribute graph",
            self.assertEqual,
            [],
            list(merge_obj._entries_lca()),
        )

    def test_one_lca_accidentally_pruned(self):
        # Another incorrect resolution from the same basic flaw:
        #   A    value 'foo'
        #   |\
        #   B C  B value 'bar', C = 'foo'
        #   |X|
        #   D E  D = 'bar', E reverts to 'foo'
        #   |X|
        #   F G  F = 'bing', G switches to 'bar'
        #
        # 'bar' will not be seen as an interesting change, because 'foo' will
        # be pruned from the LCAs, even though it was newly introduced by E
        # (superseding B).
        builder = self.get_builder()
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"a-root-id", "directory", None)),
                ("add", ("foo", b"foo-id", "file", b"A content\n")),
            ],
            revision_id=b"A-id",
        )
        builder.build_snapshot([b"A-id"], [], revision_id=b"C-id")
        builder.build_snapshot(
            [b"A-id"], [("rename", ("foo", "bar"))], revision_id=b"B-id"
        )
        builder.build_snapshot([b"B-id", b"C-id"], [], revision_id=b"D-id")
        builder.build_snapshot([b"C-id", b"B-id"], [], revision_id=b"E-id")
        builder.build_snapshot(
            [b"E-id", b"D-id"], [("rename", ("foo", "bar"))], revision_id=b"G-id"
        )
        builder.build_snapshot(
            [b"D-id", b"E-id"], [("rename", ("bar", "bing"))], revision_id=b"F-id"
        )  # should end up conflicting
        merge_obj = self.make_merge_obj(builder, b"G-id")

        entries = list(merge_obj._entries_lca())
        root_id = b"a-root-id"
        self.expectFailure(
            "We prune values from BASE even when relevant.",
            self.assertEqual,
            [
                (
                    b"foo-id",
                    False,
                    ((root_id, [root_id, root_id]), root_id, root_id),
                    (("foo", ["bar", "foo"]), "bar", "bing"),
                    ((False, [False, False]), False, False),
                    False,
                ),
            ],
            entries,
        )

    def test_both_sides_revert(self):
        # Both sides of a criss-cross revert the text to the lca
        #       A    base, introduces 'foo'
        #       |\
        #       B C  B modifies 'foo', C modifies 'foo'
        #       |X|
        #       D E  D reverts to B, E reverts to C
        # This should conflict
        builder = self.get_builder()
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"a-root-id", "directory", None)),
                ("add", ("foo", b"foo-id", "file", b"A content\n")),
            ],
            revision_id=b"A-id",
        )
        builder.build_snapshot(
            [b"A-id"], [("modify", ("foo", b"B content\n"))], revision_id=b"B-id"
        )
        builder.build_snapshot(
            [b"A-id"], [("modify", ("foo", b"C content\n"))], revision_id=b"C-id"
        )
        builder.build_snapshot([b"C-id", b"B-id"], [], revision_id=b"E-id")
        builder.build_snapshot([b"B-id", b"C-id"], [], revision_id=b"D-id")
        merge_obj = self.make_merge_obj(builder, b"E-id")

        entries = list(merge_obj._entries_lca())
        root_id = b"a-root-id"
        self.assertEqual(
            [
                (
                    b"foo-id",
                    True,
                    (("foo", ["foo", "foo"]), "foo", "foo"),
                    ((root_id, [root_id, root_id]), root_id, root_id),
                    (("foo", ["foo", "foo"]), "foo", "foo"),
                    ((False, [False, False]), False, False),
                    False,
                ),
            ],
            entries,
        )

    def test_different_lca_resolve_one_side_updates_content(self):
        # Both sides converge, but then one side updates the text.
        #       A    base, introduces 'foo'
        #       |\
        #       B C  B modifies 'foo', C modifies 'foo'
        #       |X|
        #       D E  D reverts to B, E reverts to C
        #       |
        #       F    F updates to a new value
        # We need to emit an entry for 'foo', because D & E differed on the
        # merge resolution
        builder = self.get_builder()
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"a-root-id", "directory", None)),
                ("add", ("foo", b"foo-id", "file", b"A content\n")),
            ],
            revision_id=b"A-id",
        )
        builder.build_snapshot(
            [b"A-id"], [("modify", ("foo", b"B content\n"))], revision_id=b"B-id"
        )
        builder.build_snapshot(
            [b"A-id"],
            [("modify", ("foo", b"C content\n"))],
            revision_id=b"C-id",
        )
        builder.build_snapshot([b"C-id", b"B-id"], [], revision_id=b"E-id")
        builder.build_snapshot([b"B-id", b"C-id"], [], revision_id=b"D-id")
        builder.build_snapshot(
            [b"D-id"], [("modify", ("foo", b"F content\n"))], revision_id=b"F-id"
        )
        merge_obj = self.make_merge_obj(builder, b"E-id")

        entries = list(merge_obj._entries_lca())
        root_id = b"a-root-id"
        self.assertEqual(
            [
                (
                    b"foo-id",
                    True,
                    (("foo", ["foo", "foo"]), "foo", "foo"),
                    ((root_id, [root_id, root_id]), root_id, root_id),
                    (("foo", ["foo", "foo"]), "foo", "foo"),
                    ((False, [False, False]), False, False),
                    False,
                ),
            ],
            entries,
        )

    def test_same_lca_resolution_one_side_updates_content(self):
        # Both sides converge, but then one side updates the text.
        #       A    base, introduces 'foo'
        #       |\
        #       B C  B modifies 'foo', C modifies 'foo'
        #       |X|
        #       D E  D and E use C's value
        #       |
        #       F    F updates to a new value
        # I think it is a bug that this conflicts, but we don't have a way to
        # detect otherwise. And because of:
        #   test_different_lca_resolve_one_side_updates_content
        # We need to conflict.

        builder = self.get_builder()
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"a-root-id", "directory", None)),
                ("add", ("foo", b"foo-id", "file", b"A content\n")),
            ],
            revision_id=b"A-id",
        )
        builder.build_snapshot(
            [b"A-id"], [("modify", ("foo", b"B content\n"))], revision_id=b"B-id"
        )
        builder.build_snapshot(
            [b"A-id"], [("modify", ("foo", b"C content\n"))], revision_id=b"C-id"
        )
        builder.build_snapshot([b"C-id", b"B-id"], [], revision_id=b"E-id")
        builder.build_snapshot(
            [b"B-id", b"C-id"],
            [("modify", ("foo", b"C content\n"))],
            revision_id=b"D-id",
        )  # Same as E
        builder.build_snapshot(
            [b"D-id"], [("modify", ("foo", b"F content\n"))], revision_id=b"F-id"
        )
        merge_obj = self.make_merge_obj(builder, b"E-id")

        entries = list(merge_obj._entries_lca())
        self.expectFailure(
            "We don't detect that LCA resolution was the same on both sides",
            self.assertEqual,
            [],
            entries,
        )

    def test_only_path_changed(self):
        builder = self.get_builder()
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"a-root-id", "directory", None)),
                ("add", ("a", b"a-id", "file", b"content\n")),
            ],
            revision_id=b"A-id",
        )
        builder.build_snapshot([b"A-id"], [], revision_id=b"B-id")
        builder.build_snapshot([b"A-id"], [], revision_id=b"C-id")
        builder.build_snapshot(
            [b"C-id", b"B-id"], [("rename", ("a", "b"))], revision_id=b"E-id"
        )
        builder.build_snapshot([b"B-id", b"C-id"], [], revision_id=b"D-id")
        merge_obj = self.make_merge_obj(builder, b"E-id")
        entries = list(merge_obj._entries_lca())
        root_id = b"a-root-id"
        # The content was not changed, only the path
        self.assertEqual(
            [
                (
                    b"a-id",
                    False,
                    (("a", ["a", "a"]), "b", "a"),
                    ((root_id, [root_id, root_id]), root_id, root_id),
                    (("a", ["a", "a"]), "b", "a"),
                    ((False, [False, False]), False, False),
                    False,
                ),
            ],
            entries,
        )

    def test_kind_changed(self):
        # Identical content, except 'D' changes a-id into a directory
        builder = self.get_builder()
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"a-root-id", "directory", None)),
                ("add", ("a", b"a-id", "file", b"content\n")),
            ],
            revision_id=b"A-id",
        )
        builder.build_snapshot([b"A-id"], [], revision_id=b"B-id")
        builder.build_snapshot([b"A-id"], [], revision_id=b"C-id")
        builder.build_snapshot(
            [b"C-id", b"B-id"],
            [
                ("unversion", "a"),
                ("flush", None),
                ("add", ("a", b"a-id", "directory", None)),
            ],
            revision_id=b"E-id",
        )
        builder.build_snapshot([b"B-id", b"C-id"], [], revision_id=b"D-id")
        merge_obj = self.make_merge_obj(builder, b"E-id")
        entries = list(merge_obj._entries_lca())
        root_id = b"a-root-id"
        # Only the kind was changed (content)
        self.assertEqual(
            [
                (
                    b"a-id",
                    True,
                    (("a", ["a", "a"]), "a", "a"),
                    ((root_id, [root_id, root_id]), root_id, root_id),
                    (("a", ["a", "a"]), "a", "a"),
                    ((False, [False, False]), False, False),
                    False,
                ),
            ],
            entries,
        )

    def test_this_changed_kind(self):
        # Identical content, but THIS changes a file to a directory
        builder = self.get_builder()
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"a-root-id", "directory", None)),
                ("add", ("a", b"a-id", "file", b"content\n")),
            ],
            revision_id=b"A-id",
        )
        builder.build_snapshot([b"A-id"], [], revision_id=b"B-id")
        builder.build_snapshot([b"A-id"], [], revision_id=b"C-id")
        builder.build_snapshot([b"C-id", b"B-id"], [], revision_id=b"E-id")
        builder.build_snapshot(
            [b"B-id", b"C-id"],
            [
                ("unversion", "a"),
                ("flush", None),
                ("add", ("a", b"a-id", "directory", None)),
            ],
            revision_id=b"D-id",
        )
        merge_obj = self.make_merge_obj(builder, b"E-id")
        entries = list(merge_obj._entries_lca())
        # Only the kind was changed (content)
        self.assertEqual([], entries)

    def test_interesting_file_in_this(self):
        # This renamed the file, but it should still match the entry in other
        builder = self.get_builder()
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"a-root-id", "directory", None)),
                ("add", ("a", b"a-id", "file", b"content\n")),
                ("add", ("b", b"b-id", "file", b"content\n")),
            ],
            revision_id=b"A-id",
        )
        builder.build_snapshot([b"A-id"], [], revision_id=b"B-id")
        builder.build_snapshot([b"A-id"], [], revision_id=b"C-id")
        builder.build_snapshot(
            [b"C-id", b"B-id"],
            [("modify", ("a", b"new-content\n")), ("modify", ("b", b"new-content\n"))],
            revision_id=b"E-id",
        )
        builder.build_snapshot(
            [b"B-id", b"C-id"], [("rename", ("b", "c"))], revision_id=b"D-id"
        )
        merge_obj = self.make_merge_obj(builder, b"E-id", interesting_files=["c"])
        entries = list(merge_obj._entries_lca())
        root_id = b"a-root-id"
        self.assertEqual(
            [
                (
                    b"b-id",
                    True,
                    (("b", ["b", "b"]), "b", "c"),
                    ((root_id, [root_id, root_id]), root_id, root_id),
                    (("b", ["b", "b"]), "b", "c"),
                    ((False, [False, False]), False, False),
                    False,
                ),
            ],
            entries,
        )

    def test_interesting_file_in_base(self):
        # This renamed the file, but it should still match the entry in BASE
        builder = self.get_builder()
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"a-root-id", "directory", None)),
                ("add", ("a", b"a-id", "file", b"content\n")),
                ("add", ("c", b"c-id", "file", b"content\n")),
            ],
            revision_id=b"A-id",
        )
        builder.build_snapshot([b"A-id"], [("rename", ("c", "b"))], revision_id=b"B-id")
        builder.build_snapshot([b"A-id"], [("rename", ("c", "b"))], revision_id=b"C-id")
        builder.build_snapshot(
            [b"C-id", b"B-id"],
            [("modify", ("a", b"new-content\n")), ("modify", ("b", b"new-content\n"))],
            revision_id=b"E-id",
        )
        builder.build_snapshot([b"B-id", b"C-id"], [], revision_id=b"D-id")
        merge_obj = self.make_merge_obj(builder, b"E-id", interesting_files=["c"])
        entries = list(merge_obj._entries_lca())
        root_id = b"a-root-id"
        self.assertEqual(
            [
                (
                    b"c-id",
                    True,
                    (("c", ["b", "b"]), "b", "b"),
                    ((root_id, [root_id, root_id]), root_id, root_id),
                    (("c", ["b", "b"]), "b", "b"),
                    ((False, [False, False]), False, False),
                    False,
                ),
            ],
            entries,
        )

    def test_interesting_file_in_lca(self):
        # This renamed the file, but it should still match the entry in LCA
        builder = self.get_builder()
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"a-root-id", "directory", None)),
                ("add", ("a", b"a-id", "file", b"content\n")),
                ("add", ("b", b"b-id", "file", b"content\n")),
            ],
            revision_id=b"A-id",
        )
        builder.build_snapshot([b"A-id"], [("rename", ("b", "c"))], revision_id=b"B-id")
        builder.build_snapshot([b"A-id"], [], revision_id=b"C-id")
        builder.build_snapshot(
            [b"C-id", b"B-id"],
            [("modify", ("a", b"new-content\n")), ("modify", ("b", b"new-content\n"))],
            revision_id=b"E-id",
        )
        builder.build_snapshot(
            [b"B-id", b"C-id"], [("rename", ("c", "b"))], revision_id=b"D-id"
        )
        merge_obj = self.make_merge_obj(builder, b"E-id", interesting_files=["c"])
        entries = list(merge_obj._entries_lca())
        root_id = b"a-root-id"
        self.assertEqual(
            [
                (
                    b"b-id",
                    True,
                    (("b", ["c", "b"]), "b", "b"),
                    ((root_id, [root_id, root_id]), root_id, root_id),
                    (("b", ["c", "b"]), "b", "b"),
                    ((False, [False, False]), False, False),
                    False,
                ),
            ],
            entries,
        )

    def test_interesting_files(self):
        # Two files modified, but we should filter one of them
        builder = self.get_builder()
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"a-root-id", "directory", None)),
                ("add", ("a", b"a-id", "file", b"content\n")),
                ("add", ("b", b"b-id", "file", b"content\n")),
            ],
            revision_id=b"A-id",
        )
        builder.build_snapshot([b"A-id"], [], revision_id=b"B-id")
        builder.build_snapshot([b"A-id"], [], revision_id=b"C-id")
        builder.build_snapshot(
            [b"C-id", b"B-id"],
            [("modify", ("a", b"new-content\n")), ("modify", ("b", b"new-content\n"))],
            revision_id=b"E-id",
        )
        builder.build_snapshot([b"B-id", b"C-id"], [], revision_id=b"D-id")
        merge_obj = self.make_merge_obj(builder, b"E-id", interesting_files=["b"])
        entries = list(merge_obj._entries_lca())
        root_id = b"a-root-id"
        self.assertEqual(
            [
                (
                    b"b-id",
                    True,
                    (("b", ["b", "b"]), "b", "b"),
                    ((root_id, [root_id, root_id]), root_id, root_id),
                    (("b", ["b", "b"]), "b", "b"),
                    ((False, [False, False]), False, False),
                    False,
                ),
            ],
            entries,
        )


class TestMergerEntriesLCAOnDisk(tests.TestCaseWithTransport):
    def get_builder(self):
        builder = self.make_branch_builder("path")
        builder.start_series()
        self.addCleanup(builder.finish_series)
        return builder

    def get_wt_from_builder(self, builder):
        """Get a real WorkingTree from the builder."""
        the_branch = builder.get_branch()
        wt = the_branch.controldir.create_workingtree()
        # Note: This is a little bit ugly, but we are holding the branch
        #       write-locked as part of the build process, and we would like to
        #       maintain that. So we just force the WT to re-use the same
        #       branch object.
        wt._branch = the_branch
        wt.lock_write()
        self.addCleanup(wt.unlock)
        return wt

    def do_merge(self, builder, other_revision_id):
        wt = self.get_wt_from_builder(builder)
        merger = _mod_merge.Merger.from_revision_ids(wt, other_revision_id)
        merger.merge_type = _mod_merge.Merge3Merger
        return wt, merger.do_merge()

    def test_simple_lca(self):
        builder = self.get_builder()
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"a-root-id", "directory", None)),
                ("add", ("a", b"a-id", "file", b"a\nb\nc\n")),
            ],
            revision_id=b"A-id",
        )
        builder.build_snapshot([b"A-id"], [], revision_id=b"C-id")
        builder.build_snapshot([b"A-id"], [], revision_id=b"B-id")
        builder.build_snapshot([b"C-id", b"B-id"], [], revision_id=b"E-id")
        builder.build_snapshot(
            [b"B-id", b"C-id"],
            [("modify", ("a", b"a\nb\nc\nd\ne\nf\n"))],
            revision_id=b"D-id",
        )
        wt, conflicts = self.do_merge(builder, b"E-id")
        self.assertEqual([], conflicts)
        # The merge should have simply update the contents of 'a'
        self.assertEqual(b"a\nb\nc\nd\ne\nf\n", wt.get_file_text("a"))

    def test_conflict_without_lca(self):
        # This test would cause a merge conflict, unless we use the lca trees
        # to determine the real ancestry
        #   A       Path at 'foo'
        #  / \
        # B   C     Path renamed to 'bar' in B
        # |\ /|
        # | X |
        # |/ \|
        # D   E     Path at 'bar' in D and E
        #     |
        #     F     Path at 'baz' in F, which supersedes 'bar' and 'foo'
        builder = self.get_builder()
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"a-root-id", "directory", None)),
                ("add", ("foo", b"foo-id", "file", b"a\nb\nc\n")),
            ],
            revision_id=b"A-id",
        )
        builder.build_snapshot([b"A-id"], [], revision_id=b"C-id")
        builder.build_snapshot(
            [b"A-id"],
            [("rename", ("foo", "bar"))],
            revision_id=b"B-id",
        )
        builder.build_snapshot(
            [b"C-id", b"B-id"],  # merge the rename
            [("rename", ("foo", "bar"))],
            revision_id=b"E-id",
        )
        builder.build_snapshot(
            [b"E-id"], [("rename", ("bar", "baz"))], revision_id=b"F-id"
        )
        builder.build_snapshot([b"B-id", b"C-id"], [], revision_id=b"D-id")
        wt, conflicts = self.do_merge(builder, b"F-id")
        self.assertEqual([], conflicts)
        # The merge should simply recognize that the final rename takes
        # precedence
        self.assertEqual("baz", wt.id2path(b"foo-id"))

    def test_other_deletes_lca_renames(self):
        # This test would cause a merge conflict, unless we use the lca trees
        # to determine the real ancestry
        #   A       Path at 'foo'
        #  / \
        # B   C     Path renamed to 'bar' in B
        # |\ /|
        # | X |
        # |/ \|
        # D   E     Path at 'bar' in D and E
        #     |
        #     F     F deletes 'bar'
        builder = self.get_builder()
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"a-root-id", "directory", None)),
                ("add", ("foo", b"foo-id", "file", b"a\nb\nc\n")),
            ],
            revision_id=b"A-id",
        )
        builder.build_snapshot([b"A-id"], [], revision_id=b"C-id")
        builder.build_snapshot(
            [b"A-id"], [("rename", ("foo", "bar"))], revision_id=b"B-id"
        )
        builder.build_snapshot(
            [b"C-id", b"B-id"],  # merge the rename
            [("rename", ("foo", "bar"))],
            revision_id=b"E-id",
        )
        builder.build_snapshot([b"E-id"], [("unversion", "bar")], revision_id=b"F-id")
        builder.build_snapshot([b"B-id", b"C-id"], [], revision_id=b"D-id")
        wt, conflicts = self.do_merge(builder, b"F-id")
        self.assertEqual([], conflicts)
        self.assertRaises(errors.NoSuchId, wt.id2path, b"foo-id")

    def test_executable_changes(self):
        #   A       Path at 'foo'
        #  / \
        # B   C
        # |\ /|
        # | X |
        # |/ \|
        # D   E
        #     |
        #     F     Executable bit changed
        builder = self.get_builder()
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"a-root-id", "directory", None)),
                ("add", ("foo", b"foo-id", "file", b"a\nb\nc\n")),
            ],
            revision_id=b"A-id",
        )
        builder.build_snapshot([b"A-id"], [], revision_id=b"C-id")
        builder.build_snapshot([b"A-id"], [], revision_id=b"B-id")
        builder.build_snapshot([b"B-id", b"C-id"], [], revision_id=b"D-id")
        builder.build_snapshot([b"C-id", b"B-id"], [], revision_id=b"E-id")
        # Have to use a real WT, because BranchBuilder doesn't support exec bit
        wt = self.get_wt_from_builder(builder)
        with wt.transform() as tt:
            tt.set_executability(True, tt.trans_id_tree_path("foo"))
            tt.apply()
        self.assertTrue(wt.is_executable("foo"))
        wt.commit("F-id", rev_id=b"F-id")
        # Reset to D, so that we can merge F
        wt.set_parent_ids([b"D-id"])
        wt.branch.set_last_revision_info(3, b"D-id")
        wt.revert()
        self.assertFalse(wt.is_executable("foo"))
        conflicts = wt.merge_from_branch(wt.branch, to_revision=b"F-id")
        self.assertEqual(0, len(conflicts))
        self.assertTrue(wt.is_executable("foo"))

    def test_create_symlink(self):
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        #   A
        #  / \
        # B   C
        # |\ /|
        # | X |
        # |/ \|
        # D   E
        #     |
        #     F     Add a symlink 'foo' => 'bar'
        # Have to use a real WT, because BranchBuilder and MemoryTree don't
        # have symlink support
        builder = self.get_builder()
        builder.build_snapshot(
            None, [("add", ("", b"a-root-id", "directory", None))], revision_id=b"A-id"
        )
        builder.build_snapshot([b"A-id"], [], revision_id=b"C-id")
        builder.build_snapshot([b"A-id"], [], revision_id=b"B-id")
        builder.build_snapshot([b"B-id", b"C-id"], [], revision_id=b"D-id")
        builder.build_snapshot([b"C-id", b"B-id"], [], revision_id=b"E-id")
        # Have to use a real WT, because BranchBuilder doesn't support exec bit
        wt = self.get_wt_from_builder(builder)
        os.symlink("bar", "path/foo")
        wt.add(["foo"], ids=[b"foo-id"])
        self.assertEqual("bar", wt.get_symlink_target("foo"))
        wt.commit("add symlink", rev_id=b"F-id")
        # Reset to D, so that we can merge F
        wt.set_parent_ids([b"D-id"])
        wt.branch.set_last_revision_info(3, b"D-id")
        wt.revert()
        self.assertFalse(wt.is_versioned("foo"))
        conflicts = wt.merge_from_branch(wt.branch, to_revision=b"F-id")
        self.assertEqual(0, len(conflicts))
        self.assertEqual(b"foo-id", wt.path2id("foo"))
        self.assertEqual("bar", wt.get_symlink_target("foo"))

    def test_both_sides_revert(self):
        # Both sides of a criss-cross revert the text to the lca
        #       A    base, introduces 'foo'
        #       |\
        #       B C  B modifies 'foo', C modifies 'foo'
        #       |X|
        #       D E  D reverts to B, E reverts to C
        # This should conflict
        # This must be done with a real WorkingTree, because normally their
        # inventory contains "None" rather than a real sha1
        builder = self.get_builder()
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"a-root-id", "directory", None)),
                ("add", ("foo", b"foo-id", "file", b"A content\n")),
            ],
            revision_id=b"A-id",
        )
        builder.build_snapshot(
            [b"A-id"], [("modify", ("foo", b"B content\n"))], revision_id=b"B-id"
        )
        builder.build_snapshot(
            [b"A-id"], [("modify", ("foo", b"C content\n"))], revision_id=b"C-id"
        )
        builder.build_snapshot([b"C-id", b"B-id"], [], revision_id=b"E-id")
        builder.build_snapshot([b"B-id", b"C-id"], [], revision_id=b"D-id")
        wt, conflicts = self.do_merge(builder, b"E-id")
        self.assertEqual(1, len(conflicts))
        self.assertEqualDiff(
            b"<<<<<<< TREE\nB content\n=======\nC content\n>>>>>>> MERGE-SOURCE\n",
            wt.get_file_text("foo"),
        )

    def test_modified_symlink(self):
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        #   A       Create symlink foo => bar
        #  / \
        # B   C     B relinks foo => baz
        # |\ /|
        # | X |
        # |/ \|
        # D   E     D & E have foo => baz
        #     |
        #     F     F changes it to bing
        #
        # Merging D & F should result in F cleanly overriding D, because D's
        # value actually comes from B

        # Have to use a real WT, because BranchBuilder and MemoryTree don't
        # have symlink support
        wt = self.make_branch_and_tree("path")
        wt.lock_write()
        self.addCleanup(wt.unlock)
        os.symlink("bar", "path/foo")
        wt.add(["foo"], ids=[b"foo-id"])
        wt.commit("add symlink", rev_id=b"A-id")
        os.remove("path/foo")
        os.symlink("baz", "path/foo")
        wt.commit("foo => baz", rev_id=b"B-id")
        wt.set_last_revision(b"A-id")
        wt.branch.set_last_revision_info(1, b"A-id")
        wt.revert()
        wt.commit("C", rev_id=b"C-id")
        wt.merge_from_branch(wt.branch, b"B-id")
        self.assertEqual("baz", wt.get_symlink_target("foo"))
        wt.commit("E merges C & B", rev_id=b"E-id")
        os.remove("path/foo")
        os.symlink("bing", "path/foo")
        wt.commit("F foo => bing", rev_id=b"F-id")
        wt.set_last_revision(b"B-id")
        wt.branch.set_last_revision_info(2, b"B-id")
        wt.revert()
        wt.merge_from_branch(wt.branch, b"C-id")
        wt.commit("D merges B & C", rev_id=b"D-id")
        conflicts = wt.merge_from_branch(wt.branch, to_revision=b"F-id")
        self.assertEqual(0, len(conflicts))
        self.assertEqual("bing", wt.get_symlink_target("foo"))

    def test_renamed_symlink(self):
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        #   A       Create symlink foo => bar
        #  / \
        # B   C     B renames foo => barry
        # |\ /|
        # | X |
        # |/ \|
        # D   E     D & E have barry
        #     |
        #     F     F renames barry to blah
        #
        # Merging D & F should result in F cleanly overriding D, because D's
        # value actually comes from B

        wt = self.make_branch_and_tree("path")
        wt.lock_write()
        self.addCleanup(wt.unlock)
        os.symlink("bar", "path/foo")
        wt.add(["foo"], ids=[b"foo-id"])
        wt.commit("A add symlink", rev_id=b"A-id")
        wt.rename_one("foo", "barry")
        wt.commit("B foo => barry", rev_id=b"B-id")
        wt.set_last_revision(b"A-id")
        wt.branch.set_last_revision_info(1, b"A-id")
        wt.revert()
        wt.commit("C", rev_id=b"C-id")
        wt.merge_from_branch(wt.branch, b"B-id")
        self.assertEqual("barry", wt.id2path(b"foo-id"))
        self.assertEqual("bar", wt.get_symlink_target("barry"))
        wt.commit("E merges C & B", rev_id=b"E-id")
        wt.rename_one("barry", "blah")
        wt.commit("F barry => blah", rev_id=b"F-id")
        wt.set_last_revision(b"B-id")
        wt.branch.set_last_revision_info(2, b"B-id")
        wt.revert()
        wt.merge_from_branch(wt.branch, b"C-id")
        wt.commit("D merges B & C", rev_id=b"D-id")
        self.assertEqual("barry", wt.id2path(b"foo-id"))
        # Check the output of the Merger object directly
        merger = _mod_merge.Merger.from_revision_ids(wt, b"F-id")
        merger.merge_type = _mod_merge.Merge3Merger
        merge_obj = merger.make_merger()
        root_id = wt.path2id("")
        entries = list(merge_obj._entries_lca())
        # No content change, just a path change
        self.assertEqual(
            [
                (
                    b"foo-id",
                    False,
                    (("foo", ["barry", "foo"]), "blah", "barry"),
                    ((root_id, [root_id, root_id]), root_id, root_id),
                    (("foo", ["barry", "foo"]), "blah", "barry"),
                    ((False, [False, False]), False, False),
                    False,
                ),
            ],
            entries,
        )
        conflicts = wt.merge_from_branch(wt.branch, to_revision=b"F-id")
        self.assertEqual(0, len(conflicts))
        self.assertEqual("blah", wt.id2path(b"foo-id"))

    def test_symlink_no_content_change(self):
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        #   A       Create symlink foo => bar
        #  / \
        # B   C     B relinks foo => baz
        # |\ /|
        # | X |
        # |/ \|
        # D   E     D & E have foo => baz
        # |
        # F         F has foo => bing
        #
        # Merging E into F should not cause a conflict, because E doesn't have
        # a content change relative to the LCAs (it does relative to A)
        wt = self.make_branch_and_tree("path")
        wt.lock_write()
        self.addCleanup(wt.unlock)
        os.symlink("bar", "path/foo")
        wt.add(["foo"], ids=[b"foo-id"])
        wt.commit("add symlink", rev_id=b"A-id")
        os.remove("path/foo")
        os.symlink("baz", "path/foo")
        wt.commit("foo => baz", rev_id=b"B-id")
        wt.set_last_revision(b"A-id")
        wt.branch.set_last_revision_info(1, b"A-id")
        wt.revert()
        wt.commit("C", rev_id=b"C-id")
        wt.merge_from_branch(wt.branch, b"B-id")
        self.assertEqual("baz", wt.get_symlink_target("foo"))
        wt.commit("E merges C & B", rev_id=b"E-id")
        wt.set_last_revision(b"B-id")
        wt.branch.set_last_revision_info(2, b"B-id")
        wt.revert()
        wt.merge_from_branch(wt.branch, b"C-id")
        wt.commit("D merges B & C", rev_id=b"D-id")
        os.remove("path/foo")
        os.symlink("bing", "path/foo")
        wt.commit("F foo => bing", rev_id=b"F-id")

        # Check the output of the Merger object directly
        merger = _mod_merge.Merger.from_revision_ids(wt, b"E-id")
        merger.merge_type = _mod_merge.Merge3Merger
        merge_obj = merger.make_merger()
        # Nothing interesting happened in OTHER relative to BASE
        self.assertEqual([], list(merge_obj._entries_lca()))
        # Now do a real merge, just to test the rest of the stack
        conflicts = wt.merge_from_branch(wt.branch, to_revision=b"E-id")
        self.assertEqual(0, len(conflicts))
        self.assertEqual("bing", wt.get_symlink_target("foo"))

    def test_symlink_this_changed_kind(self):
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        #   A       Nothing
        #  / \
        # B   C     B creates symlink foo => bar
        # |\ /|
        # | X |
        # |/ \|
        # D   E     D changes foo into a file, E has foo => bing
        #
        # Mostly, this is trying to test that we don't try to os.readlink() on
        # a file, or when there is nothing there
        wt = self.make_branch_and_tree("path")
        wt.lock_write()
        self.addCleanup(wt.unlock)
        wt.commit("base", rev_id=b"A-id")
        os.symlink("bar", "path/foo")
        wt.add(["foo"], ids=[b"foo-id"])
        wt.commit("add symlink foo => bar", rev_id=b"B-id")
        wt.set_last_revision(b"A-id")
        wt.branch.set_last_revision_info(1, b"A-id")
        wt.revert()
        wt.commit("C", rev_id=b"C-id")
        wt.merge_from_branch(wt.branch, b"B-id")
        self.assertEqual("bar", wt.get_symlink_target("foo"))
        os.remove("path/foo")
        # We have to change the link in E, or it won't try to do a comparison
        os.symlink("bing", "path/foo")
        wt.commit("E merges C & B, overrides to bing", rev_id=b"E-id")
        wt.set_last_revision(b"B-id")
        wt.branch.set_last_revision_info(2, b"B-id")
        wt.revert()
        wt.merge_from_branch(wt.branch, b"C-id")
        os.remove("path/foo")
        self.build_tree_contents([("path/foo", b"file content\n")])
        # XXX: workaround, WT doesn't detect kind changes unless you do
        # iter_changes()
        list(wt.iter_changes(wt.basis_tree()))
        wt.commit("D merges B & C, makes it a file", rev_id=b"D-id")

        merger = _mod_merge.Merger.from_revision_ids(wt, b"E-id")
        merger.merge_type = _mod_merge.Merge3Merger
        merge_obj = merger.make_merger()
        entries = list(merge_obj._entries_lca())
        root_id = wt.path2id("")
        self.assertEqual(
            [
                (
                    b"foo-id",
                    True,
                    ((None, ["foo", None]), "foo", "foo"),
                    ((None, [root_id, None]), root_id, root_id),
                    ((None, ["foo", None]), "foo", "foo"),
                    ((None, [False, None]), False, False),
                    False,
                ),
            ],
            entries,
        )

    def test_symlink_all_wt(self):
        """Check behavior if all trees are Working Trees."""
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        # The big issue is that entry.symlink_target is None for WorkingTrees.
        # So we need to make sure we handle that case correctly.
        #   A   foo => bar
        #   |\
        #   B C B relinks foo => baz
        #   |X|
        #   D E D & E have foo => baz
        #     |
        #     F F changes it to bing
        # Merging D & F should result in F cleanly overriding D, because D's
        # value actually comes from B

        wt = self.make_branch_and_tree("path")
        wt.lock_write()
        self.addCleanup(wt.unlock)
        os.symlink("bar", "path/foo")
        wt.add(["foo"], ids=[b"foo-id"])
        wt.commit("add symlink", rev_id=b"A-id")
        os.remove("path/foo")
        os.symlink("baz", "path/foo")
        wt.commit("foo => baz", rev_id=b"B-id")
        wt.set_last_revision(b"A-id")
        wt.branch.set_last_revision_info(1, b"A-id")
        wt.revert()
        wt.commit("C", rev_id=b"C-id")
        wt.merge_from_branch(wt.branch, b"B-id")
        self.assertEqual("baz", wt.get_symlink_target("foo"))
        wt.commit("E merges C & B", rev_id=b"E-id")
        os.remove("path/foo")
        os.symlink("bing", "path/foo")
        wt.commit("F foo => bing", rev_id=b"F-id")
        wt.set_last_revision(b"B-id")
        wt.branch.set_last_revision_info(2, b"B-id")
        wt.revert()
        wt.merge_from_branch(wt.branch, b"C-id")
        wt.commit("D merges B & C", rev_id=b"D-id")
        wt_base = wt.controldir.sprout("base", b"A-id").open_workingtree()
        wt_base.lock_read()
        self.addCleanup(wt_base.unlock)
        wt_lca1 = wt.controldir.sprout("b-tree", b"B-id").open_workingtree()
        wt_lca1.lock_read()
        self.addCleanup(wt_lca1.unlock)
        wt_lca2 = wt.controldir.sprout("c-tree", b"C-id").open_workingtree()
        wt_lca2.lock_read()
        self.addCleanup(wt_lca2.unlock)
        wt_other = wt.controldir.sprout("other", b"F-id").open_workingtree()
        wt_other.lock_read()
        self.addCleanup(wt_other.unlock)
        merge_obj = _mod_merge.Merge3Merger(
            wt, wt, wt_base, wt_other, lca_trees=[wt_lca1, wt_lca2], do_merge=False
        )
        entries = list(merge_obj._entries_lca())
        root_id = wt.path2id("")
        self.assertEqual(
            [
                (
                    b"foo-id",
                    True,
                    (("foo", ["foo", "foo"]), "foo", "foo"),
                    ((root_id, [root_id, root_id]), root_id, root_id),
                    (("foo", ["foo", "foo"]), "foo", "foo"),
                    ((False, [False, False]), False, False),
                    False,
                ),
            ],
            entries,
        )

    def test_other_reverted_path_to_base(self):
        #   A       Path at 'foo'
        #  / \
        # B   C     Path at 'bar' in B
        # |\ /|
        # | X |
        # |/ \|
        # D   E     Path at 'bar'
        #     |
        #     F     Path at 'foo'
        builder = self.get_builder()
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"a-root-id", "directory", None)),
                ("add", ("foo", b"foo-id", "file", b"a\nb\nc\n")),
            ],
            revision_id=b"A-id",
        )
        builder.build_snapshot([b"A-id"], [], revision_id=b"C-id")
        builder.build_snapshot(
            [b"A-id"], [("rename", ("foo", "bar"))], revision_id=b"B-id"
        )
        builder.build_snapshot(
            [b"C-id", b"B-id"], [("rename", ("foo", "bar"))], revision_id=b"E-id"
        )  # merge the rename
        builder.build_snapshot(
            [b"E-id"], [("rename", ("bar", "foo"))], revision_id=b"F-id"
        )  # Rename back to BASE
        builder.build_snapshot([b"B-id", b"C-id"], [], revision_id=b"D-id")
        wt, conflicts = self.do_merge(builder, b"F-id")
        self.assertEqual([], conflicts)
        self.assertEqual("foo", wt.id2path(b"foo-id"))

    def test_other_reverted_content_to_base(self):
        builder = self.get_builder()
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"a-root-id", "directory", None)),
                ("add", ("foo", b"foo-id", "file", b"base content\n")),
            ],
            revision_id=b"A-id",
        )
        builder.build_snapshot([b"A-id"], [], revision_id=b"C-id")
        builder.build_snapshot(
            [b"A-id"], [("modify", ("foo", b"B content\n"))], revision_id=b"B-id"
        )
        builder.build_snapshot(
            [b"C-id", b"B-id"],
            [("modify", ("foo", b"B content\n"))],
            revision_id=b"E-id",
        )  # merge the content
        builder.build_snapshot(
            [b"E-id"], [("modify", ("foo", b"base content\n"))], revision_id=b"F-id"
        )  # Revert back to BASE
        builder.build_snapshot([b"B-id", b"C-id"], [], revision_id=b"D-id")
        wt, conflicts = self.do_merge(builder, b"F-id")
        self.assertEqual([], conflicts)
        # TODO: We need to use the per-file graph to properly select a BASE
        #       before this will work. Or at least use the LCA trees to find
        #       the appropriate content base. (which is B, not A).
        self.assertEqual(b"base content\n", wt.get_file_text("foo"))

    def test_other_modified_content(self):
        builder = self.get_builder()
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"a-root-id", "directory", None)),
                ("add", ("foo", b"foo-id", "file", b"base content\n")),
            ],
            revision_id=b"A-id",
        )
        builder.build_snapshot([b"A-id"], [], revision_id=b"C-id")
        builder.build_snapshot(
            [b"A-id"], [("modify", ("foo", b"B content\n"))], revision_id=b"B-id"
        )
        builder.build_snapshot(
            [b"C-id", b"B-id"],
            [("modify", ("foo", b"B content\n"))],
            revision_id=b"E-id",
        )  # merge the content
        builder.build_snapshot(
            [b"E-id"], [("modify", ("foo", b"F content\n"))], revision_id=b"F-id"
        )  # Override B content
        builder.build_snapshot([b"B-id", b"C-id"], [], revision_id=b"D-id")
        wt, conflicts = self.do_merge(builder, b"F-id")
        self.assertEqual([], conflicts)
        self.assertEqual(b"F content\n", wt.get_file_text("foo"))

    def test_all_wt(self):
        """Check behavior if all trees are Working Trees."""
        # The big issue is that entry.revision is None for WorkingTrees. (as is
        # entry.text_sha1, etc. So we need to make sure we handle that case
        # correctly.
        #   A   Content of 'foo', path of 'a'
        #   |\
        #   B C B modifies content, C renames 'a' => 'b'
        #   |X|
        #   D E E updates content, renames 'b' => 'c'
        builder = self.get_builder()
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"a-root-id", "directory", None)),
                ("add", ("a", b"a-id", "file", b"base content\n")),
                ("add", ("foo", b"foo-id", "file", b"base content\n")),
            ],
            revision_id=b"A-id",
        )
        builder.build_snapshot(
            [b"A-id"], [("modify", ("foo", b"B content\n"))], revision_id=b"B-id"
        )
        builder.build_snapshot([b"A-id"], [("rename", ("a", "b"))], revision_id=b"C-id")
        builder.build_snapshot(
            [b"C-id", b"B-id"],
            [("rename", ("b", "c")), ("modify", ("foo", b"E content\n"))],
            revision_id=b"E-id",
        )
        builder.build_snapshot(
            [b"B-id", b"C-id"], [("rename", ("a", "b"))], revision_id=b"D-id"
        )  # merged change
        wt_this = self.get_wt_from_builder(builder)
        wt_base = wt_this.controldir.sprout("base", b"A-id").open_workingtree()
        wt_base.lock_read()
        self.addCleanup(wt_base.unlock)
        wt_lca1 = wt_this.controldir.sprout("b-tree", b"B-id").open_workingtree()
        wt_lca1.lock_read()
        self.addCleanup(wt_lca1.unlock)
        wt_lca2 = wt_this.controldir.sprout("c-tree", b"C-id").open_workingtree()
        wt_lca2.lock_read()
        self.addCleanup(wt_lca2.unlock)
        wt_other = wt_this.controldir.sprout("other", b"E-id").open_workingtree()
        wt_other.lock_read()
        self.addCleanup(wt_other.unlock)
        merge_obj = _mod_merge.Merge3Merger(
            wt_this,
            wt_this,
            wt_base,
            wt_other,
            lca_trees=[wt_lca1, wt_lca2],
            do_merge=False,
        )
        entries = list(merge_obj._entries_lca())
        root_id = b"a-root-id"
        self.assertEqual(
            [
                (
                    b"a-id",
                    False,
                    (("a", ["a", "b"]), "c", "b"),
                    ((root_id, [root_id, root_id]), root_id, root_id),
                    (("a", ["a", "b"]), "c", "b"),
                    ((False, [False, False]), False, False),
                    False,
                ),
                (
                    b"foo-id",
                    True,
                    (("foo", ["foo", "foo"]), "foo", "foo"),
                    ((root_id, [root_id, root_id]), root_id, root_id),
                    (("foo", ["foo", "foo"]), "foo", "foo"),
                    ((False, [False, False]), False, False),
                    False,
                ),
            ],
            entries,
        )

    def test_nested_tree_unmodified(self):
        # Tested with a real WT, because BranchBuilder/MemoryTree don't handle
        # 'tree-reference'
        wt = self.make_branch_and_tree("tree", format="development-subtree")
        wt.lock_write()
        self.addCleanup(wt.unlock)
        sub_tree = self.make_branch_and_tree(
            "tree/sub-tree", format="development-subtree"
        )
        wt.set_root_id(b"a-root-id")
        sub_tree.set_root_id(b"sub-tree-root")
        self.build_tree_contents([("tree/sub-tree/file", b"text1")])
        sub_tree.add("file")
        sub_tree.commit("foo", rev_id=b"sub-A-id")
        wt.add_reference(sub_tree)
        wt.commit("set text to 1", rev_id=b"A-id", recursive=None)
        # Now create a criss-cross merge in the parent, without modifying the
        # subtree
        wt.commit("B", rev_id=b"B-id", recursive=None)
        wt.set_last_revision(b"A-id")
        wt.branch.set_last_revision_info(1, b"A-id")
        wt.commit("C", rev_id=b"C-id", recursive=None)
        wt.merge_from_branch(wt.branch, to_revision=b"B-id")
        wt.commit("E", rev_id=b"E-id", recursive=None)
        wt.set_parent_ids([b"B-id", b"C-id"])
        wt.branch.set_last_revision_info(2, b"B-id")
        wt.commit("D", rev_id=b"D-id", recursive=None)

        merger = _mod_merge.Merger.from_revision_ids(wt, b"E-id")
        merger.merge_type = _mod_merge.Merge3Merger
        merge_obj = merger.make_merger()
        entries = list(merge_obj._entries_lca())
        self.assertEqual([], entries)

    def test_nested_tree_subtree_modified(self):
        # Tested with a real WT, because BranchBuilder/MemoryTree don't handle
        # 'tree-reference'
        wt = self.make_branch_and_tree("tree", format="development-subtree")
        wt.lock_write()
        self.addCleanup(wt.unlock)
        sub_tree = self.make_branch_and_tree("tree/sub", format="development-subtree")
        wt.set_root_id(b"a-root-id")
        sub_tree.set_root_id(b"sub-tree-root")
        self.build_tree_contents([("tree/sub/file", b"text1")])
        sub_tree.add("file")
        sub_tree.commit("foo", rev_id=b"sub-A-id")
        wt.add_reference(sub_tree)
        wt.commit("set text to 1", rev_id=b"A-id", recursive=None)
        # Now create a criss-cross merge in the parent, without modifying the
        # subtree
        wt.commit("B", rev_id=b"B-id", recursive=None)
        wt.set_last_revision(b"A-id")
        wt.branch.set_last_revision_info(1, b"A-id")
        wt.commit("C", rev_id=b"C-id", recursive=None)
        wt.merge_from_branch(wt.branch, to_revision=b"B-id")
        self.build_tree_contents([("tree/sub/file", b"text2")])
        sub_tree.commit("modify contents", rev_id=b"sub-B-id")
        wt.commit("E", rev_id=b"E-id", recursive=None)
        wt.set_parent_ids([b"B-id", b"C-id"])
        wt.branch.set_last_revision_info(2, b"B-id")
        wt.commit("D", rev_id=b"D-id", recursive=None)

        merger = _mod_merge.Merger.from_revision_ids(wt, b"E-id")
        merger.merge_type = _mod_merge.Merge3Merger
        merge_obj = merger.make_merger()
        entries = list(merge_obj._entries_lca())
        # Nothing interesting about this sub-tree, because content changes are
        # computed at a higher level
        self.assertEqual([], entries)

    def test_nested_tree_subtree_renamed(self):
        # Tested with a real WT, because BranchBuilder/MemoryTree don't handle
        # 'tree-reference'
        wt = self.make_branch_and_tree("tree", format="development-subtree")
        wt.lock_write()
        self.addCleanup(wt.unlock)
        sub_tree = self.make_branch_and_tree("tree/sub", format="development-subtree")
        wt.set_root_id(b"a-root-id")
        sub_tree.set_root_id(b"sub-tree-root")
        self.build_tree_contents([("tree/sub/file", b"text1")])
        sub_tree.add("file")
        sub_tree.commit("foo", rev_id=b"sub-A-id")
        wt.add_reference(sub_tree)
        wt.commit("set text to 1", rev_id=b"A-id", recursive=None)
        # Now create a criss-cross merge in the parent, without modifying the
        # subtree
        wt.commit("B", rev_id=b"B-id", recursive=None)
        wt.set_last_revision(b"A-id")
        wt.branch.set_last_revision_info(1, b"A-id")
        wt.commit("C", rev_id=b"C-id", recursive=None)
        wt.merge_from_branch(wt.branch, to_revision=b"B-id")
        wt.rename_one("sub", "alt_sub")
        wt.commit("E", rev_id=b"E-id", recursive=None)
        wt.set_last_revision(b"B-id")
        wt.revert()
        wt.set_parent_ids([b"B-id", b"C-id"])
        wt.branch.set_last_revision_info(2, b"B-id")
        wt.commit("D", rev_id=b"D-id", recursive=None)

        merger = _mod_merge.Merger.from_revision_ids(wt, b"E-id")
        merger.merge_type = _mod_merge.Merge3Merger
        merge_obj = merger.make_merger()
        entries = list(merge_obj._entries_lca())
        root_id = b"a-root-id"
        self.assertEqual(
            [
                (
                    b"sub-tree-root",
                    False,
                    (("sub", ["sub", "sub"]), "alt_sub", "sub"),
                    ((root_id, [root_id, root_id]), root_id, root_id),
                    (("sub", ["sub", "sub"]), "alt_sub", "sub"),
                    ((False, [False, False]), False, False),
                    False,
                ),
            ],
            entries,
        )

    def test_nested_tree_subtree_renamed_and_modified(self):
        # Tested with a real WT, because BranchBuilder/MemoryTree don't handle
        # 'tree-reference'
        wt = self.make_branch_and_tree("tree", format="development-subtree")
        wt.lock_write()
        self.addCleanup(wt.unlock)
        sub_tree = self.make_branch_and_tree("tree/sub", format="development-subtree")
        wt.set_root_id(b"a-root-id")
        sub_tree.set_root_id(b"sub-tree-root")
        self.build_tree_contents([("tree/sub/file", b"text1")])
        sub_tree.add("file")
        sub_tree.commit("foo", rev_id=b"sub-A-id")
        wt.add_reference(sub_tree)
        wt.commit("set text to 1", rev_id=b"A-id", recursive=None)
        # Now create a criss-cross merge in the parent, without modifying the
        # subtree
        wt.commit("B", rev_id=b"B-id", recursive=None)
        wt.set_last_revision(b"A-id")
        wt.branch.set_last_revision_info(1, b"A-id")
        wt.commit("C", rev_id=b"C-id", recursive=None)
        wt.merge_from_branch(wt.branch, to_revision=b"B-id")
        self.build_tree_contents([("tree/sub/file", b"text2")])
        sub_tree.commit("modify contents", rev_id=b"sub-B-id")
        wt.rename_one("sub", "alt_sub")
        wt.commit("E", rev_id=b"E-id", recursive=None)
        wt.set_last_revision(b"B-id")
        wt.revert()
        wt.set_parent_ids([b"B-id", b"C-id"])
        wt.branch.set_last_revision_info(2, b"B-id")
        wt.commit("D", rev_id=b"D-id", recursive=None)

        merger = _mod_merge.Merger.from_revision_ids(wt, b"E-id")
        merger.merge_type = _mod_merge.Merge3Merger
        merge_obj = merger.make_merger()
        entries = list(merge_obj._entries_lca())
        root_id = b"a-root-id"
        self.assertEqual(
            [
                (
                    b"sub-tree-root",
                    False,
                    (("sub", ["sub", "sub"]), "alt_sub", "sub"),
                    ((root_id, [root_id, root_id]), root_id, root_id),
                    (("sub", ["sub", "sub"]), "alt_sub", "sub"),
                    ((False, [False, False]), False, False),
                    False,
                ),
            ],
            entries,
        )


class TestLCAMultiWay(tests.TestCase):
    def assertLCAMultiWay(
        self, expected, base, lcas, other, this, allow_overriding_lca=True
    ):
        self.assertEqual(
            expected,
            _mod_merge.Merge3Merger._lca_multi_way(
                (base, lcas), other, this, allow_overriding_lca=allow_overriding_lca
            ),
        )

    def test_other_equal_equal_lcas(self):
        """Test when OTHER=LCA and all LCAs are identical."""
        self.assertLCAMultiWay("this", "bval", ["bval", "bval"], "bval", "bval")
        self.assertLCAMultiWay("this", "bval", ["lcaval", "lcaval"], "lcaval", "bval")
        self.assertLCAMultiWay(
            "this", "bval", ["lcaval", "lcaval", "lcaval"], "lcaval", "bval"
        )
        self.assertLCAMultiWay(
            "this", "bval", ["lcaval", "lcaval", "lcaval"], "lcaval", "tval"
        )
        self.assertLCAMultiWay(
            "this", "bval", ["lcaval", "lcaval", "lcaval"], "lcaval", None
        )

    def test_other_equal_this(self):
        """Test when other and this are identical."""
        self.assertLCAMultiWay("this", "bval", ["bval", "bval"], "oval", "oval")
        self.assertLCAMultiWay("this", "bval", ["lcaval", "lcaval"], "oval", "oval")
        self.assertLCAMultiWay("this", "bval", ["cval", "dval"], "oval", "oval")
        self.assertLCAMultiWay("this", "bval", [None, "lcaval"], "oval", "oval")
        self.assertLCAMultiWay("this", None, [None, "lcaval"], "oval", "oval")
        self.assertLCAMultiWay("this", None, ["lcaval", "lcaval"], "oval", "oval")
        self.assertLCAMultiWay("this", None, ["cval", "dval"], "oval", "oval")
        self.assertLCAMultiWay("this", None, ["cval", "dval"], None, None)
        self.assertLCAMultiWay(
            "this", None, ["cval", "dval", "eval", "fval"], "oval", "oval"
        )

    def test_no_lcas(self):
        self.assertLCAMultiWay("this", "bval", [], "bval", "tval")
        self.assertLCAMultiWay("other", "bval", [], "oval", "bval")
        self.assertLCAMultiWay("conflict", "bval", [], "oval", "tval")
        self.assertLCAMultiWay("this", "bval", [], "oval", "oval")

    def test_lca_supersedes_other_lca(self):
        """If one lca == base, the other lca takes precedence."""
        self.assertLCAMultiWay("this", "bval", ["bval", "lcaval"], "lcaval", "tval")
        self.assertLCAMultiWay("this", "bval", ["bval", "lcaval"], "lcaval", "bval")
        # This is actually considered a 'revert' because the 'lcaval' in LCAS
        # supersedes the BASE val (in the other LCA) but then OTHER reverts it
        # back to bval.
        self.assertLCAMultiWay("other", "bval", ["bval", "lcaval"], "bval", "lcaval")
        self.assertLCAMultiWay("conflict", "bval", ["bval", "lcaval"], "bval", "tval")

    def test_other_and_this_pick_different_lca(self):
        # OTHER and THIS resolve the lca conflict in different ways
        self.assertLCAMultiWay(
            "conflict", "bval", ["lca1val", "lca2val"], "lca1val", "lca2val"
        )
        self.assertLCAMultiWay(
            "conflict", "bval", ["lca1val", "lca2val", "lca3val"], "lca1val", "lca2val"
        )
        self.assertLCAMultiWay(
            "conflict", "bval", ["lca1val", "lca2val", "bval"], "lca1val", "lca2val"
        )

    def test_other_in_lca(self):
        # OTHER takes a value of one of the LCAs, THIS takes a new value, which
        # theoretically supersedes both LCA values and 'wins'
        self.assertLCAMultiWay(
            "this", "bval", ["lca1val", "lca2val"], "lca1val", "newval"
        )
        self.assertLCAMultiWay(
            "this", "bval", ["lca1val", "lca2val", "lca3val"], "lca1val", "newval"
        )
        self.assertLCAMultiWay(
            "conflict",
            "bval",
            ["lca1val", "lca2val"],
            "lca1val",
            "newval",
            allow_overriding_lca=False,
        )
        self.assertLCAMultiWay(
            "conflict",
            "bval",
            ["lca1val", "lca2val", "lca3val"],
            "lca1val",
            "newval",
            allow_overriding_lca=False,
        )
        # THIS reverted back to BASE, but that is an explicit supersede of all
        # LCAs
        self.assertLCAMultiWay(
            "this", "bval", ["lca1val", "lca2val", "lca3val"], "lca1val", "bval"
        )
        self.assertLCAMultiWay(
            "this", "bval", ["lca1val", "lca2val", "bval"], "lca1val", "bval"
        )
        self.assertLCAMultiWay(
            "conflict",
            "bval",
            ["lca1val", "lca2val", "lca3val"],
            "lca1val",
            "bval",
            allow_overriding_lca=False,
        )
        self.assertLCAMultiWay(
            "conflict",
            "bval",
            ["lca1val", "lca2val", "bval"],
            "lca1val",
            "bval",
            allow_overriding_lca=False,
        )

    def test_this_in_lca(self):
        # THIS takes a value of one of the LCAs, OTHER takes a new value, which
        # theoretically supersedes both LCA values and 'wins'
        self.assertLCAMultiWay(
            "other", "bval", ["lca1val", "lca2val"], "oval", "lca1val"
        )
        self.assertLCAMultiWay(
            "other", "bval", ["lca1val", "lca2val"], "oval", "lca2val"
        )
        self.assertLCAMultiWay(
            "conflict",
            "bval",
            ["lca1val", "lca2val"],
            "oval",
            "lca1val",
            allow_overriding_lca=False,
        )
        self.assertLCAMultiWay(
            "conflict",
            "bval",
            ["lca1val", "lca2val"],
            "oval",
            "lca2val",
            allow_overriding_lca=False,
        )
        # OTHER reverted back to BASE, but that is an explicit supersede of all
        # LCAs
        self.assertLCAMultiWay(
            "other", "bval", ["lca1val", "lca2val", "lca3val"], "bval", "lca3val"
        )
        self.assertLCAMultiWay(
            "conflict",
            "bval",
            ["lca1val", "lca2val", "lca3val"],
            "bval",
            "lca3val",
            allow_overriding_lca=False,
        )

    def test_all_differ(self):
        self.assertLCAMultiWay(
            "conflict", "bval", ["lca1val", "lca2val"], "oval", "tval"
        )
        self.assertLCAMultiWay(
            "conflict", "bval", ["lca1val", "lca2val", "lca2val"], "oval", "tval"
        )
        self.assertLCAMultiWay(
            "conflict", "bval", ["lca1val", "lca2val", "lca3val"], "oval", "tval"
        )


class TestConfigurableFileMerger(tests.TestCaseWithTransport):
    def setUp(self):
        super().setUp()
        self.calls = []

    def get_merger_factory(self):
        # Allows  the inner methods to access the test attributes
        calls = self.calls

        class FooMerger(_mod_merge.ConfigurableFileMerger):
            name_prefix = "foo"
            default_files = ["bar"]

            def merge_text(self, params):
                calls.append("merge_text")
                return ("not_applicable", None)

        def factory(merger):
            result = FooMerger(merger)
            # Make sure we start with a clean slate
            self.assertEqual(None, result.affected_files)
            # Track the original merger
            self.merger = result
            return result

        return factory

    def _install_hook(self, factory):
        _mod_merge.Merger.hooks.install_named_hook(
            "merge_file_content", factory, "test factory"
        )

    def make_builder(self):
        builder = test_merge_core.MergeBuilder(self.test_base_dir)
        self.addCleanup(builder.cleanup)
        return builder

    def make_text_conflict(self, file_name="bar"):
        factory = self.get_merger_factory()
        self._install_hook(factory)
        builder = self.make_builder()
        trans_ids = builder.add_file(
            builder.root(), file_name, b"text1", True, file_id=b"bar-id"
        )
        builder.change_contents(trans_ids, other=b"text4", this=b"text3")
        return builder

    def make_kind_change(self):
        factory = self.get_merger_factory()
        self._install_hook(factory)
        builder = self.make_builder()
        builder.add_file(
            builder.root(), "bar", b"text1", True, this=False, file_id=b"bar-id"
        )
        builder.add_dir(
            builder.root(), "bar-id", base=False, other=False, file_id=b"bar-dir"
        )
        return builder

    def test_uses_this_branch(self):
        builder = self.make_text_conflict()
        with builder.make_preview_transform():
            pass

    def test_affected_files_cached(self):
        """Ensures that the config variable is cached."""
        builder = self.make_text_conflict()
        conflicts = builder.merge()
        # The hook should set the variable
        self.assertEqual(["bar"], self.merger.affected_files)
        self.assertEqual(1, len(conflicts))

    def test_hook_called_for_text_conflicts(self):
        builder = self.make_text_conflict()
        builder.merge()
        # The hook should call the merge_text() method
        self.assertEqual(["merge_text"], self.calls)

    def test_hook_not_called_for_kind_change(self):
        builder = self.make_kind_change()
        builder.merge()
        # The hook should not call the merge_text() method
        self.assertEqual([], self.calls)

    def test_hook_not_called_for_other_files(self):
        builder = self.make_text_conflict("foobar")
        builder.merge()
        # The hook should not call the merge_text() method
        self.assertEqual([], self.calls)


class TestMergeIntoBase(tests.TestCaseWithTransport):
    def setup_simple_branch(self, relpath, shape=None, root_id=None):
        """One commit, containing tree specified by optional shape.

        Default is empty tree (just root entry).
        """
        if root_id is None:
            root_id = b"%s-root-id" % (relpath.encode("ascii"),)
        wt = self.make_branch_and_tree(relpath)
        wt.set_root_id(root_id)
        if shape is not None:
            adjusted_shape = [relpath + "/" + elem for elem in shape]
            self.build_tree(adjusted_shape)
            ids = [
                (
                    b"%s-%s-id"
                    % (
                        relpath.encode("utf-8"),
                        basename(elem.rstrip("/")).encode("ascii"),
                    )
                )
                for elem in shape
            ]
            wt.add(shape, ids=ids)
        rev_id = b"r1-%s" % (relpath.encode("utf-8"),)
        wt.commit(f"Initial commit of {relpath}", rev_id=rev_id)
        self.assertEqual(root_id, wt.path2id(""))
        return wt

    def setup_two_branches(self, custom_root_ids=True):
        """Setup 2 branches, one will be a library, the other a project."""
        root_id = None if custom_root_ids else inventory.ROOT_ID
        project_wt = self.setup_simple_branch(
            "project", ["README", "dir/", "dir/file.c"], root_id
        )
        lib_wt = self.setup_simple_branch(
            "lib1", ["README", "Makefile", "foo.c"], root_id
        )

        return project_wt, lib_wt

    def do_merge_into(self, location, merge_as):
        """Helper for using MergeIntoMerger.

        :param location: location of directory to merge from, either the
            location of a branch or of a path inside a branch.
        :param merge_as: the path in a tree to add the new directory as.
        :returns: the conflicts from 'do_merge'.
        """
        with contextlib.ExitStack() as stack:
            # Open and lock the various tree and branch objects
            wt, subdir_relpath = WorkingTree.open_containing(merge_as)
            stack.enter_context(wt.lock_write())
            branch_to_merge, subdir_to_merge = _mod_branch.Branch.open_containing(
                location
            )
            stack.enter_context(branch_to_merge.lock_read())
            other_tree = branch_to_merge.basis_tree()
            stack.enter_context(other_tree.lock_read())
            # Perform the merge
            merger = _mod_merge.MergeIntoMerger(
                this_tree=wt,
                other_tree=other_tree,
                other_branch=branch_to_merge,
                target_subdir=subdir_relpath,
                source_subpath=subdir_to_merge,
            )
            merger.set_base_revision(_mod_revision.NULL_REVISION, branch_to_merge)
            conflicts = merger.do_merge()
            merger.set_pending()
            return conflicts

    def assertTreeEntriesEqual(self, expected_entries, tree):
        """Assert that 'tree' contains the expected inventory entries.

        :param expected_entries: sequence of (path, file-id) pairs.
        """
        files = [(path, ie.file_id) for path, ie in tree.iter_entries_by_dir()]
        self.assertEqual(expected_entries, files)


class TestMergeInto(TestMergeIntoBase):
    def test_newdir_with_unique_roots(self):
        """Merge a branch with a unique root into a new directory."""
        project_wt, _lib_wt = self.setup_two_branches()
        self.do_merge_into("lib1", "project/lib1")
        project_wt.lock_read()
        self.addCleanup(project_wt.unlock)
        # The r1-lib1 revision should be merged into this one
        self.assertEqual([b"r1-project", b"r1-lib1"], project_wt.get_parent_ids())
        self.assertTreeEntriesEqual(
            [
                ("", b"project-root-id"),
                ("README", b"project-README-id"),
                ("dir", b"project-dir-id"),
                ("lib1", b"lib1-root-id"),
                ("dir/file.c", b"project-file.c-id"),
                ("lib1/Makefile", b"lib1-Makefile-id"),
                ("lib1/README", b"lib1-README-id"),
                ("lib1/foo.c", b"lib1-foo.c-id"),
            ],
            project_wt,
        )

    def test_subdir(self):
        """Merge a branch into a subdirectory of an existing directory."""
        project_wt, _lib_wt = self.setup_two_branches()
        self.do_merge_into("lib1", "project/dir/lib1")
        project_wt.lock_read()
        self.addCleanup(project_wt.unlock)
        # The r1-lib1 revision should be merged into this one
        self.assertEqual([b"r1-project", b"r1-lib1"], project_wt.get_parent_ids())
        self.assertTreeEntriesEqual(
            [
                ("", b"project-root-id"),
                ("README", b"project-README-id"),
                ("dir", b"project-dir-id"),
                ("dir/file.c", b"project-file.c-id"),
                ("dir/lib1", b"lib1-root-id"),
                ("dir/lib1/Makefile", b"lib1-Makefile-id"),
                ("dir/lib1/README", b"lib1-README-id"),
                ("dir/lib1/foo.c", b"lib1-foo.c-id"),
            ],
            project_wt,
        )

    def test_newdir_with_repeat_roots(self):
        """If the file-id of the dir to be merged already exists a new ID will
        be allocated to let the merge happen.
        """
        project_wt, _lib_wt = self.setup_two_branches(custom_root_ids=False)
        root_id = project_wt.path2id("")
        self.do_merge_into("lib1", "project/lib1")
        project_wt.lock_read()
        self.addCleanup(project_wt.unlock)
        # The r1-lib1 revision should be merged into this one
        self.assertEqual([b"r1-project", b"r1-lib1"], project_wt.get_parent_ids())
        new_lib1_id = project_wt.path2id("lib1")
        self.assertNotEqual(None, new_lib1_id)
        self.assertTreeEntriesEqual(
            [
                ("", root_id),
                ("README", b"project-README-id"),
                ("dir", b"project-dir-id"),
                ("lib1", new_lib1_id),
                ("dir/file.c", b"project-file.c-id"),
                ("lib1/Makefile", b"lib1-Makefile-id"),
                ("lib1/README", b"lib1-README-id"),
                ("lib1/foo.c", b"lib1-foo.c-id"),
            ],
            project_wt,
        )

    def test_name_conflict(self):
        """When the target directory name already exists a conflict is
        generated and the original directory is renamed to foo.moved.
        """
        dest_wt = self.setup_simple_branch("dest", ["dir/", "dir/file.txt"])
        self.setup_simple_branch("src", ["README"])
        conflicts = self.do_merge_into("src", "dest/dir")
        self.assertEqual(1, len(conflicts))
        dest_wt.lock_read()
        self.addCleanup(dest_wt.unlock)
        # The r1-lib1 revision should be merged into this one
        self.assertEqual([b"r1-dest", b"r1-src"], dest_wt.get_parent_ids())
        self.assertTreeEntriesEqual(
            [
                ("", b"dest-root-id"),
                ("dir", b"src-root-id"),
                ("dir.moved", b"dest-dir-id"),
                ("dir/README", b"src-README-id"),
                ("dir.moved/file.txt", b"dest-file.txt-id"),
            ],
            dest_wt,
        )

    def test_file_id_conflict(self):
        """A conflict is generated if the merge-into adds a file (or other
        inventory entry) with a file-id that already exists in the target tree.
        """
        self.setup_simple_branch("dest", ["file.txt"])
        # Make a second tree with a file-id that will clash with file.txt in
        # dest.
        src_wt = self.make_branch_and_tree("src")
        self.build_tree(["src/README"])
        src_wt.add(["README"], ids=[b"dest-file.txt-id"])
        src_wt.commit("Rev 1 of src.", rev_id=b"r1-src")
        conflicts = self.do_merge_into("src", "dest/dir")
        # This is an edge case that shouldn't happen to users very often.  So
        # we don't care really about the exact presentation of the conflict,
        # just that there is one.
        self.assertEqual(1, len(conflicts))

    def test_only_subdir(self):
        """When the location points to just part of a tree, merge just that
        subtree.
        """
        dest_wt = self.setup_simple_branch("dest")
        self.setup_simple_branch("src", ["hello.txt", "dir/", "dir/foo.c"])
        self.do_merge_into("src/dir", "dest/dir")
        dest_wt.lock_read()
        self.addCleanup(dest_wt.unlock)
        # The r1-lib1 revision should NOT be merged into this one (this is a
        # partial merge).
        self.assertEqual([b"r1-dest"], dest_wt.get_parent_ids())
        self.assertTreeEntriesEqual(
            [
                ("", b"dest-root-id"),
                ("dir", b"src-dir-id"),
                ("dir/foo.c", b"src-foo.c-id"),
            ],
            dest_wt,
        )

    def test_only_file(self):
        """An edge case: merge just one file, not a whole dir."""
        dest_wt = self.setup_simple_branch("dest")
        self.setup_simple_branch("two-file", ["file1.txt", "file2.txt"])
        self.do_merge_into("two-file/file1.txt", "dest/file1.txt")
        dest_wt.lock_read()
        self.addCleanup(dest_wt.unlock)
        # The r1-lib1 revision should NOT be merged into this one
        self.assertEqual([b"r1-dest"], dest_wt.get_parent_ids())
        self.assertTreeEntriesEqual(
            [("", b"dest-root-id"), ("file1.txt", b"two-file-file1.txt-id")], dest_wt
        )

    def test_no_such_source_path(self):
        """PathNotInTree is raised if the specified path in the source tree
        does not exist.
        """
        dest_wt = self.setup_simple_branch("dest")
        self.setup_simple_branch("src", ["dir/"])
        self.assertRaises(
            _mod_merge.PathNotInTree, self.do_merge_into, "src/no-such-dir", "dest/foo"
        )
        dest_wt.lock_read()
        self.addCleanup(dest_wt.unlock)
        # The dest tree is unmodified.
        self.assertEqual([b"r1-dest"], dest_wt.get_parent_ids())
        self.assertTreeEntriesEqual([("", b"dest-root-id")], dest_wt)

    def test_no_such_target_path(self):
        """PathNotInTree is also raised if the specified path in the target
        tree does not exist.
        """
        dest_wt = self.setup_simple_branch("dest")
        self.setup_simple_branch("src", ["file.txt"])
        self.assertRaises(
            _mod_merge.PathNotInTree, self.do_merge_into, "src", "dest/no-such-dir/foo"
        )
        dest_wt.lock_read()
        self.addCleanup(dest_wt.unlock)
        # The dest tree is unmodified.
        self.assertEqual([b"r1-dest"], dest_wt.get_parent_ids())
        self.assertTreeEntriesEqual([("", b"dest-root-id")], dest_wt)


class TestMergeHooks(TestCaseWithTransport):
    def setUp(self):
        super().setUp()
        self.tree_a = self.make_branch_and_tree("tree_a")
        self.build_tree_contents([("tree_a/file", b"content_1")])
        self.tree_a.add("file", ids=b"file-id")
        self.tree_a.commit("added file")

        self.tree_b = self.tree_a.controldir.sprout("tree_b").open_workingtree()
        self.build_tree_contents([("tree_b/file", b"content_2")])
        self.tree_b.commit("modify file")

    def test_pre_merge_hook_inject_different_tree(self):
        tree_c = self.tree_b.controldir.sprout("tree_c").open_workingtree()
        self.build_tree_contents([("tree_c/file", b"content_3")])
        tree_c.commit("more content")
        calls = []

        def factory(merger):
            self.assertIsInstance(merger, _mod_merge.Merge3Merger)
            merger.other_tree = tree_c
            calls.append(merger)

        _mod_merge.Merger.hooks.install_named_hook("pre_merge", factory, "test factory")
        self.tree_a.merge_from_branch(self.tree_b.branch)

        self.assertFileEqual(b"content_3", "tree_a/file")
        self.assertLength(1, calls)

    def test_post_merge_hook_called(self):
        calls = []

        def factory(merger):
            self.assertIsInstance(merger, _mod_merge.Merge3Merger)
            calls.append(merger)

        _mod_merge.Merger.hooks.install_named_hook(
            "post_merge", factory, "test factory"
        )

        self.tree_a.merge_from_branch(self.tree_b.branch)

        self.assertFileEqual(b"content_2", "tree_a/file")
        self.assertLength(1, calls)
