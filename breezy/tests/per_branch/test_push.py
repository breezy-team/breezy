# Copyright (C) 2007-2011 Canonical Ltd
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

"""Tests for branch.push behaviour."""

import os
from io import BytesIO

from ... import (
    branch,
    builtins,
    check,
    controldir,
    errors,
    push,
    revision,
    tests,
    transport,
)
from ...bzr import branch as bzrbranch
from ...bzr.smart import client
from .. import per_branch, test_server


class TestPush(per_branch.TestCaseWithBranch):
    def test_push_convergence_simple(self):
        # when revisions are pushed, the left-most accessible parents must
        # become the revision-history.
        mine = self.make_branch_and_tree("mine")
        mine.commit("1st post", allow_pointless=True)
        other = mine.controldir.sprout("other").open_workingtree()
        m1 = other.commit("my change", allow_pointless=True)
        mine.merge_from_branch(other.branch)
        p2 = mine.commit("merge my change")
        result = mine.branch.push(other.branch)
        self.assertEqual(p2, other.branch.last_revision())
        # result object contains some structured data
        self.assertEqual(result.old_revid, m1)
        self.assertEqual(result.new_revid, p2)

    def test_push_merged_indirect(self):
        # it should be possible to do a push from one branch into another
        # when the tip of the target was merged into the source branch
        # via a third branch - so its buried in the ancestry and is not
        # directly accessible.
        mine = self.make_branch_and_tree("mine")
        mine.commit("1st post", allow_pointless=True)
        target = mine.controldir.sprout("target").open_workingtree()
        target.commit("my change", allow_pointless=True)
        other = mine.controldir.sprout("other").open_workingtree()
        other.merge_from_branch(target.branch)
        other.commit("merge my change")
        mine.merge_from_branch(other.branch)
        p2 = mine.commit("merge other")
        mine.branch.push(target.branch)
        self.assertEqual(p2, target.branch.last_revision())

    def test_push_to_checkout_updates_master(self):
        """Pushing into a checkout updates the checkout and the master branch."""
        master_tree = self.make_branch_and_tree("master")
        checkout = self.make_branch_and_tree("checkout")
        try:
            checkout.branch.bind(master_tree.branch)
        except branch.BindingUnsupported:
            # cant bind this format, the test is irrelevant.
            return
        checkout.commit("master")

        other = master_tree.branch.controldir.sprout("other").open_workingtree()
        rev2 = other.commit("other commit")
        # now push, which should update both checkout and master.
        other.branch.push(checkout.branch)
        self.assertEqual(rev2, checkout.branch.last_revision())
        self.assertEqual(rev2, master_tree.branch.last_revision())

    def test_push_raises_specific_error_on_master_connection_error(self):
        master_tree = self.make_branch_and_tree("master")
        checkout = self.make_branch_and_tree("checkout")
        try:
            checkout.branch.bind(master_tree.branch)
        except branch.BindingUnsupported:
            # cant bind this format, the test is irrelevant.
            return
        other = master_tree.branch.controldir.sprout("other").open_workingtree()
        # move the branch out of the way on disk to cause a connection
        # error.
        os.rename("master", "master_gone")
        # try to push, which should raise a BoundBranchConnectionFailure.
        self.assertRaises(
            errors.BoundBranchConnectionFailure, other.branch.push, checkout.branch
        )

    def test_push_new_tag_to_bound_branch(self):
        master = self.make_branch("master")
        bound = self.make_branch("bound")
        try:
            bound.bind(master)
        except branch.BindingUnsupported as e:
            raise tests.TestNotApplicable(
                "Format does not support bound branches"
            ) from e
        other = bound.controldir.sprout("other").open_branch()
        try:
            other.tags.set_tag("new-tag", b"some-rev")
        except errors.TagsNotSupported as err:
            raise tests.TestNotApplicable("Format does not support tags") from err
        other.push(bound)
        self.assertEqual({"new-tag": b"some-rev"}, bound.tags.get_tag_dict())
        self.assertEqual({"new-tag": b"some-rev"}, master.tags.get_tag_dict())

    def test_push_uses_read_lock(self):
        """Push should only need a read lock on the source side."""
        source = self.make_branch_and_tree("source")
        target = self.make_branch("target")

        self.build_tree(["source/a"])
        source.add(["a"])
        source.commit("a")

        with source.branch.lock_read(), target.lock_write():
            source.branch.push(target, stop_revision=source.last_revision())

    def test_push_within_repository(self):
        """Push from one branch to another inside the same repository."""
        try:
            repo = self.make_repository("repo", shared=True)
        except (errors.IncompatibleFormat, errors.UninitializableFormat):
            # This Branch format cannot create shared repositories
            return
        if not repo._format.supports_nesting_repositories:
            return
        # This is a little bit trickier because make_branch_and_tree will not
        # re-use a shared repository.
        a_controldir = self.make_controldir("repo/tree")
        try:
            a_branch = self.branch_format.initialize(a_controldir)
        except errors.UninitializableFormat:
            # Cannot create these branches
            return
        try:
            tree = a_branch.controldir.create_workingtree()
        except errors.NotLocalUrl:
            if self.vfs_transport_factory is test_server.LocalURLServer:
                # the branch is colocated on disk, we cannot create a checkout.
                # hopefully callers will expect this.
                local_controldir = controldir.ControlDir.open(
                    self.get_vfs_only_url("repo/tree")
                )
                tree = local_controldir.create_workingtree()
            else:
                tree = a_branch.create_checkout("repo/tree", lightweight=True)
        self.build_tree(["repo/tree/a"])
        tree.add(["a"])
        tree.commit("a")

        to_bzrdir = self.make_controldir("repo/branch")
        to_branch = self.branch_format.initialize(to_bzrdir)
        tree.branch.push(to_branch)

        self.assertEqual(tree.branch.last_revision(), to_branch.last_revision())

    def test_push_overwrite_with_older_mainline_rev(self):
        """Pushing an older mainline revision with overwrite.

        This was <https://bugs.launchpad.net/bzr/+bug/386576>.
        """
        source = self.make_branch_and_tree("source")
        target = self.make_branch("target")

        source.commit("1st commit")
        rev2 = source.commit("2nd commit")
        source.commit("3rd commit")
        source.branch.push(target)
        source.branch.push(target, stop_revision=rev2, overwrite=True)
        self.assertEqual(rev2, target.last_revision())

    def test_push_overwrite_of_non_tip_with_stop_revision(self):
        """Combining the stop_revision and overwrite options works.

        This was <https://bugs.launchpad.net/bzr/+bug/234229>.
        """
        source = self.make_branch_and_tree("source")
        target = self.make_branch("target")

        source.commit("1st commit")
        source.branch.push(target)
        rev2 = source.commit("2nd commit")
        source.commit("3rd commit")

        source.branch.push(target, stop_revision=rev2, overwrite=True)
        self.assertEqual(rev2, target.last_revision())

    def test_push_repository_no_branch_doesnt_fetch_all_revs(self):
        # See https://bugs.launchpad.net/bzr/+bug/465517
        t = self.get_transport("target")
        t.ensure_base()
        try:
            bzrdir = self.bzrdir_format.initialize_on_transport(t)
        except errors.UninitializableFormat as e:
            raise tests.TestNotApplicable("cannot initialize this format") from e
        try:
            bzrdir.open_branch()
        except errors.NotBranchError:
            pass
        else:
            raise tests.TestNotApplicable(
                "some formats can't have a repo without a branch"
            )
        try:
            source = self.make_branch_builder("source", format=self.bzrdir_format)
        except errors.UninitializableFormat as e:
            raise tests.TestNotApplicable("cannot initialize this format") from e
        source.start_series()
        revid_a = source.build_snapshot(
            None, [("add", ("", b"root-id", "directory", None))]
        )
        source.build_snapshot([revid_a], [])
        revid_c = source.build_snapshot([revid_a], [])
        source.finish_series()
        b = source.get_branch()
        # Note: We can't read lock the source branch. Some formats take a write
        # lock to 'set_push_location', which breaks
        self.addCleanup(b.lock_write().unlock)
        repo = bzrdir.create_repository()
        # This means 'push the source branch into this dir'
        bzrdir.push_branch(b)
        self.addCleanup(repo.lock_read().unlock)
        # We should have pushed revid_c, but not revid_b, since it isn't in the
        # ancestry
        self.assertEqual({revid_a, revid_c}, set(repo.all_revision_ids()))

    def test_push_with_default_stacking_does_not_create_broken_branch(self):
        """Pushing a new standalone branch works even when there's a default
        stacking policy at the destination.

        The new branch will preserve the repo format (even if it isn't the
        default for the branch), and will be stacked when the repo format
        allows (which means that the branch format isn't necessarly preserved).
        """
        if self.bzrdir_format.fixed_components:
            raise tests.TestNotApplicable("Not a metadir format.")
        if isinstance(self.branch_format, bzrbranch.BranchReferenceFormat):
            # This test could in principle apply to BranchReferenceFormat, but
            # make_branch_builder doesn't support it.
            raise tests.TestSkipped("BranchBuilder can't make reference branches.")
        # Make a branch called "local" in a stackable repository
        # The branch has 3 revisions:
        #   - rev-1, adds a file
        #   - rev-2, no changes
        #   - rev-3, modifies the file.
        self.make_repository("repo", shared=True, format="1.6")
        builder = self.make_branch_builder("repo/local")
        builder.start_series()
        revid1 = builder.build_snapshot(
            None,
            [
                ("add", ("", b"root-id", "directory", b"")),
                ("add", ("filename", b"f-id", "file", b"content\n")),
            ],
        )
        revid2 = builder.build_snapshot([revid1], [])
        builder.build_snapshot([revid2], [("modify", ("filename", b"new-content\n"))])
        builder.finish_series()
        trunk = builder.get_branch()
        # Sprout rev-1 to "trunk", so that we can stack on it.
        trunk.controldir.sprout(self.get_url("trunk"), revision_id=revid1)
        # Set a default stacking policy so that new branches will automatically
        # stack on trunk.
        self.make_controldir(".").get_config().set_default_stack_on("trunk")
        # Push rev-2 to a new branch "remote".  It will be stacked on "trunk".
        output = BytesIO()
        push._show_push_branch(trunk, revid2, self.get_url("remote"), output)
        # Push rev-3 onto "remote".  If "remote" not stacked and is missing the
        # fulltext record for f-id @ rev-1, then this will fail.
        remote_branch = branch.Branch.open(self.get_url("remote"))
        trunk.push(remote_branch)
        check.check_dwim(remote_branch.base, False, True, True)


class TestPushHook(per_branch.TestCaseWithBranch):
    def setUp(self):
        self.hook_calls = []
        super().setUp()

    def capture_post_push_hook(self, result):
        """Capture post push hook calls to self.hook_calls.

        The call is logged, as is some state of the two branches.
        """
        if result.local_branch:
            local_locked = result.local_branch.is_locked()
            local_base = result.local_branch.base
        else:
            local_locked = None
            local_base = None
        self.hook_calls.append(
            (
                "post_push",
                result.source_branch,
                local_base,
                result.master_branch.base,
                result.old_revno,
                result.old_revid,
                result.new_revno,
                result.new_revid,
                result.source_branch.is_locked(),
                local_locked,
                result.master_branch.is_locked(),
            )
        )

    def test_post_push_empty_history(self):
        target = self.make_branch("target")
        source = self.make_branch("source")
        branch.Branch.hooks.install_named_hook(
            "post_push", self.capture_post_push_hook, None
        )
        source.push(target)
        # with nothing there we should still get a notification, and
        # have both branches locked at the notification time.
        self.assertEqual(
            [
                (
                    "post_push",
                    source,
                    None,
                    target.base,
                    0,
                    revision.NULL_REVISION,
                    0,
                    revision.NULL_REVISION,
                    True,
                    None,
                    True,
                )
            ],
            self.hook_calls,
        )

    def test_post_push_bound_branch(self):
        # pushing to a bound branch should pass in the master branch to the
        # hook, allowing the correct number of emails to be sent, while still
        # allowing hooks that want to modify the target to do so to both
        # instances.
        target = self.make_branch("target")
        local = self.make_branch("local")
        try:
            local.bind(target)
        except branch.BindingUnsupported:
            # We can't bind this format to itself- typically it is the local
            # branch that doesn't support binding.  As of May 2007
            # remotebranches can't be bound.  Let's instead make a new local
            # branch of the default type, which does allow binding.
            # See https://bugs.launchpad.net/bzr/+bug/112020
            local = controldir.ControlDir.create_branch_convenience("local2")
            try:
                local.bind(target)
            except branch.BindingUnsupported as e:
                raise tests.TestNotApplicable(
                    "default format does not support binding"
                ) from e
        source = self.make_branch("source")
        branch.Branch.hooks.install_named_hook(
            "post_push", self.capture_post_push_hook, None
        )
        source.push(local)
        # with nothing there we should still get a notification, and
        # have both branches locked at the notification time.
        self.assertEqual(
            [
                (
                    "post_push",
                    source,
                    local.base,
                    target.base,
                    0,
                    revision.NULL_REVISION,
                    0,
                    revision.NULL_REVISION,
                    True,
                    True,
                    True,
                )
            ],
            self.hook_calls,
        )

    def test_post_push_nonempty_history(self):
        target = self.make_branch_and_memory_tree("target")
        target.lock_write()
        target.add("")
        rev1 = target.commit("rev 1")
        target.unlock()
        sourcedir = target.controldir.clone(self.get_url("source"))
        source = sourcedir.open_branch().create_memorytree()
        rev2 = source.commit("rev 2")
        branch.Branch.hooks.install_named_hook(
            "post_push", self.capture_post_push_hook, None
        )
        source.branch.push(target.branch)
        # with nothing there we should still get a notification, and
        # have both branches locked at the notification time.
        self.assertEqual(
            [
                (
                    "post_push",
                    source.branch,
                    None,
                    target.branch.base,
                    1,
                    rev1,
                    2,
                    rev2,
                    True,
                    None,
                    True,
                )
            ],
            self.hook_calls,
        )


class EmptyPushSmartEffortTests(per_branch.TestCaseWithBranch):
    """Tests that a push of 0 revisions should make a limited number of smart
    protocol RPCs.
    """

    def setUp(self):
        # Skip some scenarios that don't apply to these tests.
        if self.transport_server is not None and issubclass(
            self.transport_server, test_server.SmartTCPServer_for_testing
        ):
            raise tests.TestNotApplicable(
                "Does not apply when remote backing branch is also a smart branch"
            )
        if not self.branch_format.supports_leaving_lock():
            raise tests.TestNotApplicable("Branch format is not usable via HPSS.")
        super().setUp()
        # Create a smart server that publishes whatever the backing VFS server
        # does.
        self.smart_server = test_server.SmartTCPServer_for_testing()
        self.start_server(self.smart_server, self.get_server())
        # Make two empty branches, 'empty' and 'target'.
        self.empty_branch = self.make_branch("empty")
        self.make_branch("target")
        # Log all HPSS calls into self.hpss_calls.
        client._SmartClient.hooks.install_named_hook(
            "call", self.capture_hpss_call, None
        )
        self.hpss_calls = []

    def capture_hpss_call(self, params):
        self.hpss_calls.append(params.method)

    def test_empty_branch_api(self):
        """The branch_obj.push API should make a limited number of HPSS calls."""
        t = transport.get_transport_from_url(self.smart_server.get_url()).clone(
            "target"
        )
        target = branch.Branch.open_from_transport(t)
        self.empty_branch.push(target)
        self.assertEqual(
            [
                b"BzrDir.open_2.1",
                b"BzrDir.open_branchV3",
                b"BzrDir.find_repositoryV3",
                b"Branch.get_stacked_on_url",
                b"Branch.lock_write",
                b"Branch.last_revision_info",
                b"Branch.unlock",
            ],
            self.hpss_calls,
        )

    def test_empty_branch_command(self):
        """The 'bzr push' command should make a limited number of HPSS calls."""
        cmd = builtins.cmd_push()
        cmd.outf = BytesIO()
        cmd.run(
            directory=self.get_url("empty"),
            location=self.smart_server.get_url() + "target",
        )
        # HPSS calls as of 2008/09/22:
        # [BzrDir.open, BzrDir.open_branch, BzrDir.find_repositoryV2,
        # Branch.get_stacked_on_url, get, get, Branch.lock_write,
        # Branch.last_revision_info, Branch.unlock]
        self.assertLessEqual(len(self.hpss_calls), 9, self.hpss_calls)


class TestLossyPush(per_branch.TestCaseWithBranch):
    def setUp(self):
        self.hook_calls = []
        super().setUp()

    def test_lossy_push_raises_same_vcs(self):
        target = self.make_branch("target")
        source = self.make_branch("source")
        self.assertRaises(errors.LossyPushToSameVCS, source.push, target, lossy=True)
