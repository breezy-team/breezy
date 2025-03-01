# Copyright (C) 2007-2010 Canonical Ltd
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

"""Tests for the contract of commit on branches."""

from breezy import branch, revision
from breezy.tests import per_branch


class TestCommit(per_branch.TestCaseWithBranch):
    def test_commit_nicks(self):
        """Nicknames are committed to the revision"""
        self.get_transport().mkdir("bzr.dev")
        wt = self.make_branch_and_tree("bzr.dev")
        branch = wt.branch
        branch.nick = "My happy branch"
        wt.commit("My commit respect da nick.")
        committed = branch.repository.get_revision(branch.last_revision())
        if branch.repository._format.supports_storing_branch_nick:
            self.assertEqual(committed.properties["branch-nick"], "My happy branch")
        else:
            self.assertNotIn("branch-nick", committed.properties)


class TestCommitHook(per_branch.TestCaseWithBranch):
    def setUp(self):
        self.hook_calls = []
        super().setUp()

    def capture_post_commit_hook(
        self, local, master, old_revno, old_revid, new_revno, new_revid
    ):
        """Capture post commit hook calls to self.hook_calls.

        The call is logged, as is some state of the two branches.
        """
        if local:
            local_locked = local.is_locked()
            local_base = local.base
        else:
            local_locked = None
            local_base = None
        self.hook_calls.append(
            (
                "post_commit",
                local_base,
                master.base,
                old_revno,
                old_revid,
                new_revno,
                new_revid,
                local_locked,
                master.is_locked(),
            )
        )

    def capture_pre_commit_hook(
        self,
        local,
        master,
        old_revno,
        old_revid,
        new_revno,
        new_revid,
        tree_delta,
        future_tree,
    ):
        self.hook_calls.append(
            ("pre_commit", old_revno, old_revid, new_revno, new_revid, tree_delta)
        )

    def test_post_commit_to_origin(self):
        tree = self.make_branch_and_memory_tree("branch")
        branch.Branch.hooks.install_named_hook(
            "post_commit", self.capture_post_commit_hook, None
        )
        tree.lock_write()
        tree.add("")
        revid = tree.commit("a revision")
        # should have had one notification, from origin, and
        # have the branch locked at notification time.
        self.assertEqual(
            [
                (
                    "post_commit",
                    None,
                    tree.branch.base,
                    0,
                    revision.NULL_REVISION,
                    1,
                    revid,
                    None,
                    True,
                )
            ],
            self.hook_calls,
        )
        tree.unlock()

    def test_post_commit_bound(self):
        master = self.make_branch("master")
        tree = self.make_branch_and_memory_tree("local")
        try:
            tree.branch.bind(master)
        except branch.BindingUnsupported:
            # cant bind this format, the test is irrelevant.
            return
        branch.Branch.hooks.install_named_hook(
            "post_commit", self.capture_post_commit_hook, None
        )
        tree.lock_write()
        tree.add("")
        revid = tree.commit("a revision")
        # with a bound branch, local is set.
        self.assertEqual(
            [
                (
                    "post_commit",
                    tree.branch.base,
                    master.base,
                    0,
                    revision.NULL_REVISION,
                    1,
                    revid,
                    True,
                    True,
                )
            ],
            self.hook_calls,
        )
        tree.unlock()

    def test_post_commit_not_to_origin(self):
        tree = self.make_branch_and_memory_tree("branch")
        with tree.lock_write():
            tree.add("")
            revid = tree.commit("first revision")
            branch.Branch.hooks.install_named_hook(
                "post_commit", self.capture_post_commit_hook, None
            )
            revid2 = tree.commit("second revision")
            # having committed from up the branch, we should get the
            # before and after revnos and revids correctly.
            self.assertEqual(
                [
                    (
                        "post_commit",
                        None,
                        tree.branch.base,
                        1,
                        revid,
                        2,
                        revid2,
                        None,
                        True,
                    )
                ],
                self.hook_calls,
            )

    def get_rootfull_delta(self, repository, revid):
        tree = repository.revision_tree(revid)
        with repository.lock_read():
            parent_revid = repository.get_parent_map([revid])[revid][0]
            basis_tree = repository.revision_tree(parent_revid)
            tree = repository.revision_tree(revid)
            return tree.changes_from(basis_tree, include_root=True)

    def test_pre_commit_passes(self):
        tree = self.make_branch_and_memory_tree("branch")
        with tree.lock_write():
            tree.add("")
            branch.Branch.hooks.install_named_hook(
                "pre_commit", self.capture_pre_commit_hook, None
            )
            revid1 = tree.commit("first revision")
            revid2 = tree.commit("second revision")
            root_delta = self.get_rootfull_delta(tree.branch.repository, revid1)
            empty_delta = tree.branch.repository.get_revision_delta(revid2)
            self.assertEqual(
                [
                    ("pre_commit", 0, revision.NULL_REVISION, 1, revid1, root_delta),
                    ("pre_commit", 1, revid1, 2, revid2, empty_delta),
                ],
                self.hook_calls,
            )

    def test_pre_commit_fails(self):
        tree = self.make_branch_and_memory_tree("branch")
        with tree.lock_write():
            tree.add("")

            class PreCommitException(Exception):
                def __init__(self, revid):
                    self.revid = revid

            def hook_func(
                local,
                master,
                old_revno,
                old_revid,
                new_revno,
                new_revid,
                tree_delta,
                future_tree,
            ):
                raise PreCommitException(new_revid)

            branch.Branch.hooks.install_named_hook(
                "pre_commit", self.capture_pre_commit_hook, None
            )
            branch.Branch.hooks.install_named_hook("pre_commit", hook_func, None)
            revids = [None, None, None]
            # this commit will raise an exception
            # so the commit is rolled back and revno unchanged
            err = self.assertRaises(PreCommitException, tree.commit, "message")
            # we have to record the revid to use in assertEqual later
            revids[0] = err.revid
            # unregister all pre_commit hooks
            branch.Branch.hooks["pre_commit"] = []
            # and re-register the capture hook
            branch.Branch.hooks.install_named_hook(
                "pre_commit", self.capture_pre_commit_hook, None
            )
            # now these commits should go through
            for i in range(1, 3):
                revids[i] = tree.commit("message")
            self.assertEqual(
                [
                    (
                        "pre_commit",
                        0,
                        revision.NULL_REVISION,
                        1,
                        revids[0],
                        self.get_rootfull_delta(tree.branch.repository, revids[0]),
                    ),
                    (
                        "pre_commit",
                        0,
                        revision.NULL_REVISION,
                        1,
                        revids[1],
                        self.get_rootfull_delta(tree.branch.repository, revids[1]),
                    ),
                    (
                        "pre_commit",
                        1,
                        revids[1],
                        2,
                        revids[2],
                        self.get_rootfull_delta(tree.branch.repository, revids[2]),
                    ),
                ],
                self.hook_calls,
            )

    def test_pre_commit_delta(self):
        # This tests the TreeDelta object passed to pre_commit hook.
        # This does not try to validate data correctness in the delta.
        self.build_tree(["rootfile", "dir/", "dir/subfile"])
        tree = self.make_branch_and_tree(".")
        with tree.lock_write():
            # setting up a playground
            tree.add("rootfile")
            tree.put_file_bytes_non_atomic("rootfile", b"abc")
            tree.add("dir")
            tree.add("dir/subfile")
            tree.put_file_bytes_non_atomic("to_be_unversioned", b"blah")
            tree.add(["to_be_unversioned"])
            tree.put_file_bytes_non_atomic("dir/subfile", b"def")
            revid1 = tree.commit("first revision")

        with tree.lock_write():
            # making changes
            tree.put_file_bytes_non_atomic("rootfile", b"jkl")
            tree.rename_one("dir/subfile", "dir/subfile_renamed")
            tree.unversion(["to_be_unversioned"])
            tree.mkdir("added_dir")
            # start to capture pre_commit delta
            branch.Branch.hooks.install_named_hook(
                "pre_commit", self.capture_pre_commit_hook, None
            )
            revid2 = tree.commit("second revision")

        self.assertEqual(
            [
                (
                    "pre_commit",
                    1,
                    revid1,
                    2,
                    revid2,
                    self.get_rootfull_delta(tree.branch.repository, revid2),
                )
            ],
            self.hook_calls,
        )
