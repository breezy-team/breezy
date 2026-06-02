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


"""Tests of bound branches (binding, unbinding, commit, etc) command."""

from breezy import branch, controldir, errors, tests
from breezy.tests import script


class TestBoundBranches(tests.TestCaseWithTransport):
    def create_branches(self):
        base_tree = self.make_branch_and_tree("base")
        base_tree.lock_write()
        self.build_tree(["base/a", "base/b"])
        base_tree.add(["a", "b"])
        base_tree.commit("init")
        base_tree.unlock()

        child_tree = base_tree.branch.create_checkout("child")

        self.check_revno(1, "child")
        d = controldir.ControlDir.open("child")
        self.assertNotEqual(None, d.open_branch().get_master_branch())

        return base_tree, child_tree

    def check_revno(self, val, loc="."):
        self.assertEqual(
            val, controldir.ControlDir.open(loc).open_branch().last_revision_info()[0]
        )

    def test_simple_binding(self):
        tree = self.make_branch_and_tree("base")
        self.build_tree(["base/a", "base/b"])
        tree.add("a", ids=b"b")
        tree.commit(message="init")

        tree.controldir.sprout("child")

        self.run_bzr("bind ../base", working_dir="child")

        d = controldir.ControlDir.open("child")
        self.assertNotEqual(None, d.open_branch().get_master_branch())

        self.run_bzr("unbind", working_dir="child")
        self.assertEqual(None, d.open_branch().get_master_branch())

        self.run_bzr("unbind", retcode=3, working_dir="child")

    def test_bind_branch6(self):
        self.make_branch("branch1", format="dirstate-tags")
        error = self.run_bzr("bind", retcode=3, working_dir="branch1")[1]
        self.assertEndsWith(
            error, "No location supplied and no previous location known\n"
        )

    def setup_rebind(self, format):
        branch1 = self.make_branch("branch1")
        branch2 = self.make_branch("branch2", format=format)
        branch2.bind(branch1)
        branch2.unbind()

    def test_rebind_branch6(self):
        self.setup_rebind("dirstate-tags")
        self.run_bzr("bind", working_dir="branch2")
        b = branch.Branch.open("branch2")
        self.assertEndsWith(b.get_bound_location(), "/branch1/")

    def test_rebind_branch5(self):
        self.setup_rebind("knit")
        error = self.run_bzr("bind", retcode=3, working_dir="branch2")[1]
        self.assertEndsWith(
            error,
            "No location supplied.  This format does not remember old locations.\n",
        )

    def test_bound_commit(self):
        child_tree = self.create_branches()[1]

        self.build_tree_contents([("child/a", b"new contents")])
        child_tree.commit(message="child")

        self.check_revno(2, "child")

        # Make sure it committed on the parent
        self.check_revno(2, "base")

    def test_bound_fail(self):
        # Make sure commit fails if out of date.
        base_tree, child_tree = self.create_branches()

        self.build_tree_contents(
            [("base/a", b"new base contents\n"), ("child/b", b"new b child contents\n")]
        )
        base_tree.commit(message="base")
        self.check_revno(2, "base")

        self.check_revno(1, "child")
        self.assertRaises(
            errors.BoundBranchOutOfDate, child_tree.commit, message="child"
        )
        self.check_revno(1, "child")

        child_tree.update()
        self.check_revno(2, "child")

        child_tree.commit(message="child")
        self.check_revno(3, "child")
        self.check_revno(3, "base")

    def test_double_binding(self):
        child_tree = self.create_branches()[1]
        child_tree.controldir.sprout("child2")

        # Double binding succeeds, but committing to child2 should fail
        self.run_bzr("bind ../child", working_dir="child2")

        # Refresh the child tree object as 'unbind' modified it
        child2_tree = controldir.ControlDir.open("child2").open_workingtree()
        self.assertRaises(
            errors.CommitToDoubleBoundBranch,
            child2_tree.commit,
            message="child2",
            allow_pointless=True,
        )

    def test_unbinding(self):
        base_tree, child_tree = self.create_branches()

        self.build_tree_contents(
            [("base/a", b"new base contents\n"), ("child/b", b"new b child contents\n")]
        )

        base_tree.commit(message="base")
        self.check_revno(2, "base")

        self.check_revno(1, "child")
        self.run_bzr("commit -m child", retcode=3, working_dir="child")
        self.check_revno(1, "child")
        self.run_bzr("unbind", working_dir="child")
        # Refresh the child tree/branch objects as 'unbind' modified them
        child_tree = child_tree.controldir.open_workingtree()
        child_tree.commit(message="child")
        self.check_revno(2, "child")

    def test_commit_remote_bound(self):
        # It is not possible to commit to a branch
        # which is bound to a branch which is bound
        base_tree, _child_tree = self.create_branches()
        base_tree.controldir.sprout("newbase")

        # There is no way to know that B has already
        # been bound by someone else, otherwise it
        # might be nice if this would fail
        self.run_bzr("bind ../newbase", working_dir="base")

        self.run_bzr("commit -m failure --unchanged", retcode=3, working_dir="child")

    def test_pull_updates_both(self):
        base_tree = self.create_branches()[0]
        newchild_tree = base_tree.controldir.sprout("newchild").open_workingtree()
        self.build_tree_contents([("newchild/b", b"newchild b contents\n")])
        newchild_tree.commit(message="newchild")
        self.check_revno(2, "newchild")

        # The pull should succeed, and update
        # the bound parent branch
        self.run_bzr("pull ../newchild", working_dir="child")
        self.check_revno(2, "child")
        self.check_revno(2, "base")

    def test_pull_local_updates_local(self):
        base_tree = self.create_branches()[0]
        newchild_tree = base_tree.controldir.sprout("newchild").open_workingtree()
        self.build_tree_contents([("newchild/b", b"newchild b contents\n")])
        newchild_tree.commit(message="newchild")
        self.check_revno(2, "newchild")

        # The pull should succeed, and update
        # the bound parent branch
        self.run_bzr("pull ../newchild --local", working_dir="child")
        self.check_revno(2, "child")
        self.check_revno(1, "base")

    def test_bind_diverged(self):
        base_tree, child_tree = self.create_branches()

        self.run_bzr("unbind", working_dir="child")

        # Refresh the child tree/branch objects as 'unbind' modified them
        child_tree = child_tree.controldir.open_workingtree()
        child_tree.commit(message="child", allow_pointless=True)
        self.check_revno(2, "child")

        self.check_revno(1, "base")
        base_tree.commit(message="base", allow_pointless=True)
        self.check_revno(2, "base")

        # These branches have diverged, but bind should succeed anyway
        self.run_bzr("bind ../base", working_dir="child")

        # Refresh the child tree/branch objects as 'bind' modified them
        child_tree = child_tree.controldir.open_workingtree()
        # This should turn the local commit into a merge
        child_tree.update()
        child_tree.commit(message="merged")
        self.check_revno(3, "child")
        self.assertEqual(
            child_tree.branch.last_revision(), base_tree.branch.last_revision()
        )

    def test_bind_parent_ahead(self):
        base_tree = self.create_branches()[0]

        self.run_bzr("unbind", working_dir="child")

        base_tree.commit(message="base", allow_pointless=True)

        self.check_revno(1, "child")
        self.run_bzr("bind ../base", working_dir="child")

        # binding does not pull data:
        self.check_revno(1, "child")
        self.run_bzr("unbind", working_dir="child")

        # Check and make sure it also works if parent is ahead multiple
        base_tree.commit(message="base 3", allow_pointless=True)
        base_tree.commit(message="base 4", allow_pointless=True)
        base_tree.commit(message="base 5", allow_pointless=True)
        self.check_revno(5, "base")

        self.check_revno(1, "child")
        self.run_bzr("bind ../base", working_dir="child")
        self.check_revno(1, "child")

    def test_bind_child_ahead(self):
        # test binding when the master branches history is a prefix of the
        # childs - it should bind ok but the revision histories should not
        # be altered
        child_tree = self.create_branches()[1]

        self.run_bzr("unbind", working_dir="child")
        # Refresh the child tree/branch objects as 'bind' modified them
        child_tree = child_tree.controldir.open_workingtree()
        child_tree.commit(message="child", allow_pointless=True)
        self.check_revno(2, "child")
        self.check_revno(1, "base")

        self.run_bzr("bind ../base", working_dir="child")
        self.check_revno(1, "base")

        # Check and make sure it also works if child is ahead multiple
        self.run_bzr("unbind", working_dir="child")
        child_tree.commit(message="child 3", allow_pointless=True)
        child_tree.commit(message="child 4", allow_pointless=True)
        child_tree.commit(message="child 5", allow_pointless=True)
        self.check_revno(5, "child")

        self.check_revno(1, "base")
        self.run_bzr("bind ../base", working_dir="child")
        self.check_revno(1, "base")

    def test_bind_fail_if_missing(self):
        """We should not be able to bind to a missing branch."""
        tree = self.make_branch_and_tree("tree_1")
        tree.commit("dummy commit")
        self.run_bzr_error(
            ["Not a branch.*no-such-branch/"],
            ["bind", "../no-such-branch"],
            working_dir="tree_1",
        )
        self.assertIs(None, tree.branch.get_bound_location())

    def test_commit_after_merge(self):
        base_tree, child_tree = self.create_branches()

        # We want merge to be able to be a local only
        # operation, because it can be without violating
        # the binding invariants.
        # But we can't fail afterwards
        other_tree = child_tree.controldir.sprout("other").open_workingtree()
        other_branch = other_tree.branch

        self.build_tree_contents([("other/c", b"file c\n")])
        other_tree.add("c")
        other_tree.commit(message="adding c")
        new_rev_id = other_branch.last_revision()

        child_tree.merge_from_branch(other_branch)

        self.assertPathExists("child/c")
        self.assertEqual([new_rev_id], child_tree.get_parent_ids()[1:])

        # Make sure the local branch has the installed revision
        self.assertTrue(child_tree.branch.repository.has_revision(new_rev_id))

        # And make sure that the base tree does not
        self.assertFalse(base_tree.branch.repository.has_revision(new_rev_id))

        # Commit should succeed, and cause merged revisions to
        # be pulled into base
        self.run_bzr(["commit", "-m", "merge other"], working_dir="child")
        self.check_revno(2, "child")
        self.check_revno(2, "base")
        self.assertTrue(base_tree.branch.repository.has_revision(new_rev_id))

    def test_pull_overwrite(self):
        # XXX: This test should be moved to branch-implemenations/test_pull
        child_tree = self.create_branches()[1]

        other_tree = child_tree.controldir.sprout("other").open_workingtree()

        self.build_tree_contents([("other/a", b"new contents\n")])
        other_tree.commit(message="changed a")
        self.check_revno(2, "other")
        self.build_tree_contents([("other/a", b"new contents\nand then some\n")])
        other_tree.commit(message="another a")
        self.check_revno(3, "other")
        self.build_tree_contents(
            [("other/a", b"new contents\nand then some\nand some more\n")]
        )
        other_tree.commit("yet another a")
        self.check_revno(4, "other")

        self.build_tree_contents([("child/a", b"also changed a\n")])
        child_tree.commit(message="child modified a")

        self.check_revno(2, "child")
        self.check_revno(2, "base")

        self.run_bzr("pull --overwrite ../other", working_dir="child")

        # both the local and master should have been updated.
        self.check_revno(4, "child")
        self.check_revno(4, "base")

    def test_bind_directory(self):
        """Test --directory option."""
        tree = self.make_branch_and_tree("base")
        self.build_tree(["base/a", "base/b"])
        tree.add("a", ids=b"b")
        tree.commit(message="init")
        tree.controldir.sprout("child")
        self.run_bzr("bind --directory=child base")
        d = controldir.ControlDir.open("child")
        self.assertNotEqual(None, d.open_branch().get_master_branch())
        self.run_bzr("unbind -d child")
        self.assertEqual(None, d.open_branch().get_master_branch())
        self.run_bzr("unbind --directory child", retcode=3)


class TestBind(script.TestCaseWithTransportAndScript):
    def test_bind_when_bound(self):
        self.run_script(
            """
$ brz init trunk
...
$ brz init copy
...
$ cd copy
$ brz bind ../trunk
$ brz bind
2>brz: ERROR: Branch is already bound
"""
        )

    def test_bind_before_bound(self):
        self.run_script(
            """
$ brz init trunk
...
$ cd trunk
$ brz bind
2>brz: ERROR: No location supplied and no previous location known
"""
        )
