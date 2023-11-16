# Copyright (C) 2011 Canonical Ltd
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


from breezy import workingtree
from breezy.tests import TestCaseWithTransport


class TestRepairWorkingTree(TestCaseWithTransport):
    def break_dirstate(self, tree, completely=False):
        """Write garbage into the dirstate file."""
        # This test assumes that the format uses a DirState file, which we then
        # manually corrupt. If we change the way to get at that dirstate file,
        # then we can update how this is done
        self.assertIsNot(None, getattr(tree, "current_dirstate", None))
        with tree.lock_read():
            dirstate = tree.current_dirstate()
            dirstate_path = dirstate._filename
            self.assertPathExists(dirstate_path)
        # We have to have the tree unlocked at this point, so we can safely
        # mutate the state file on all platforms.
        if completely:
            f = open(dirstate_path, "wb")
        else:
            f = open(dirstate_path, "ab")
        try:
            f.write(b"garbage-at-end-of-file\n")
        finally:
            f.close()

    def make_initial_tree(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/foo", "tree/dir/", "tree/dir/bar"])
        tree.add(["foo", "dir", "dir/bar"])
        tree.commit("first")
        return tree

    def test_repair_refuses_uncorrupted(self):
        self.make_initial_tree()
        # If the tree doesn't appear to be corrupt, we refuse, but prompt the
        # user to let them know that:
        # a) they may want to use 'brz revert' instead of repair-workingtree
        # b) they can use --force if they really want to do this
        self.run_bzr_error(
            ["The tree does not appear to be corrupt", '"brz revert"', "--force"],
            "repair-workingtree -d tree",
        )

    def test_repair_forced(self):
        tree = self.make_initial_tree()
        tree.rename_one("dir", "alt_dir")
        self.assertTrue(tree.is_versioned("alt_dir"))
        self.run_bzr("repair-workingtree -d tree --force")
        # This requires the tree has reloaded the working state
        self.assertFalse(tree.is_versioned("alt_dir"))
        self.assertPathExists("tree/alt_dir")

    def test_repair_corrupted_dirstate(self):
        tree = self.make_initial_tree()
        self.break_dirstate(tree)
        self.run_bzr("repair-workingtree -d tree")
        tree = workingtree.WorkingTree.open("tree")
        # At this point, check should be happy
        tree.check_state()

    def test_repair_naive_destroyed_fails(self):
        tree = self.make_initial_tree()
        self.break_dirstate(tree, completely=True)
        self.run_bzr_error(
            ["the header appears corrupt, try passing"], "repair-workingtree -d tree"
        )

    def test_repair_destroyed_with_revs_passes(self):
        tree = self.make_initial_tree()
        self.break_dirstate(tree, completely=True)
        self.run_bzr("repair-workingtree -d tree -r -1")
        tree = workingtree.WorkingTree.open("tree")
        # At this point, check should be happy
        tree.check_state()
