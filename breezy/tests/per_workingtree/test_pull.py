# Copyright (C) 2006, 2007, 2009-2012, 2016 Canonical Ltd
# Authors:  Robert Collins <robert.collins@canonical.com>
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


from breezy import tests
from breezy.revision import NULL_REVISION
from breezy.tests import per_workingtree


class TestPull(per_workingtree.TestCaseWithWorkingTree):
    def get_pullable_trees(self):
        self.build_tree(["from/", "from/file", "to/"])
        tree = self.make_branch_and_tree("from")
        tree.add("file")
        a = tree.commit("foo")
        tree_b = self.make_branch_and_tree("to")
        return tree, tree_b, a

    def test_pull_null(self):
        tree_a, tree_b, rev_a = self.get_pullable_trees()
        if tree_a.supports_setting_file_ids():
            root_id = tree_a.path2id("")
            tree_a.pull(tree_b.branch, stop_revision=NULL_REVISION, overwrite=True)
            self.assertEqual(root_id, tree_a.path2id(""))
        else:
            tree_a.pull(tree_b.branch, stop_revision=NULL_REVISION, overwrite=True)

    def test_pull(self):
        tree_a, tree_b, rev_a = self.get_pullable_trees()
        tree_b.pull(tree_a.branch)
        self.assertTrue(tree_b.branch.repository.has_revision(rev_a))
        self.assertEqual([rev_a], tree_b.get_parent_ids())

    def test_pull_overwrites(self):
        tree_a, tree_b, rev_a = self.get_pullable_trees()
        rev_b = tree_b.commit("foo")
        self.assertEqual(rev_b, tree_b.branch.last_revision())
        tree_b.pull(tree_a.branch, overwrite=True)
        self.assertTrue(tree_b.branch.repository.has_revision(rev_a))
        self.assertTrue(tree_b.branch.repository.has_revision(rev_b))
        self.assertEqual([rev_a], tree_b.get_parent_ids())

    def test_pull_merges_tree_content(self):
        tree_a, tree_b, rev_a = self.get_pullable_trees()
        tree_b.pull(tree_a.branch)
        self.assertFileEqual(b"contents of from/file\n", "to/file")

    def test_pull_changes_root_id(self):
        tree = self.make_branch_and_tree("from")
        if not tree._format.supports_versioned_directories:
            self.skipTest("format does not support custom root ids")
        tree.set_root_id(b"first_root_id")
        self.build_tree(["from/file"])
        tree.add(["file"])
        tree.commit("first")
        to_tree = tree.controldir.sprout("to").open_workingtree()
        self.assertEqual(b"first_root_id", to_tree.path2id(""))
        tree.set_root_id(b"second_root_id")
        tree.commit("second")
        to_tree.pull(tree.branch)
        self.assertEqual(b"second_root_id", to_tree.path2id(""))


class TestPullWithOrphans(per_workingtree.TestCaseWithWorkingTree):
    def make_branch_deleting_dir(self, relpath=None):
        if relpath is None:
            relpath = "trunk"
        builder = self.make_branch_builder(relpath)
        builder.start_series()

        # Create an empty trunk
        builder.build_snapshot(
            None, [("add", ("", b"root-id", "directory", ""))], revision_id=b"1"
        )
        builder.build_snapshot(
            [b"1"],
            [
                ("add", ("dir", b"dir-id", "directory", "")),
                ("add", ("file", b"file-id", "file", b"trunk content\n")),
            ],
            revision_id=b"2",
        )
        builder.build_snapshot(
            [b"2"],
            [
                ("unversion", "dir"),
            ],
            revision_id=b"3",
        )
        builder.finish_series()
        return builder.get_branch()

    def test_pull_orphans(self):
        if not self.workingtree_format.missing_parent_conflicts:
            raise tests.TestSkipped(
                "{!r} does not support missing parent conflicts".format(
                    self.workingtree_format
                )
            )
        trunk = self.make_branch_deleting_dir("trunk")
        work = trunk.controldir.sprout("work", revision_id=b"2").open_workingtree()
        work.branch.get_config_stack().set("transform.orphan_policy", "move")
        # Add some unversioned files in dir
        self.build_tree(["work/dir/foo", "work/dir/subdir/", "work/dir/subdir/foo"])
        work.pull(trunk)
        self.assertLength(0, work.conflicts())
        # The directory removal should succeed
        self.assertPathDoesNotExist("work/dir")
