# Copyright (C) 2009, 2010 Canonical Ltd
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

from io import BytesIO

from testtools.matchers import Equals, MatchesAny

from ... import branch, check, controldir, errors, push, tests
from ...branch import BindingUnsupported, Branch
from ...bzr import branch as bzrbranch
from ...bzr import vf_repository
from ...bzr.smart.repository import SmartServerRepositoryGetParentMap
from ...controldir import ControlDir
from ...revision import NULL_REVISION
from .. import test_server
from . import TestCaseWithInterBranch

# These tests are based on similar tests in
# breezy.tests.per_branch.test_push.


class TestPush(TestCaseWithInterBranch):
    def test_push_convergence_simple(self):
        # when revisions are pushed, the left-most accessible parents must
        # become the revision-history.
        mine = self.make_from_branch_and_tree("mine")
        mine.commit("1st post", allow_pointless=True)
        try:
            other = self.sprout_to(mine.controldir, "other").open_workingtree()
        except errors.NoRoundtrippingSupport:
            raise tests.TestNotApplicable(
                "lossless push between {!r} and {!r} not supported".format(
                    self.branch_format_from, self.branch_format_to
                )
            )
        m1 = other.commit("my change", allow_pointless=True)
        try:
            mine.merge_from_branch(other.branch)
        except errors.NoRoundtrippingSupport:
            raise tests.TestNotApplicable(
                "lossless push between {!r} and {!r} not supported".format(
                    self.branch_format_from, self.branch_format_to
                )
            )
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
        mine = self.make_from_branch_and_tree("mine")
        mine.commit("1st post", allow_pointless=True)
        try:
            target = self.sprout_to(mine.controldir, "target").open_workingtree()
        except errors.NoRoundtrippingSupport:
            raise tests.TestNotApplicable(
                "lossless push between {!r} and {!r} not supported".format(
                    self.branch_format_from, self.branch_format_to
                )
            )
        target.commit("my change", allow_pointless=True)
        other = self.sprout_to(mine.controldir, "other").open_workingtree()
        other.merge_from_branch(target.branch)
        other.commit("merge my change")
        try:
            mine.merge_from_branch(other.branch)
        except errors.NoRoundtrippingSupport:
            raise tests.TestNotApplicable(
                "lossless push between {!r} and {!r} not supported".format(
                    self.branch_format_from, self.branch_format_to
                )
            )
        p2 = mine.commit("merge other")
        mine.branch.push(target.branch)
        self.assertEqual(p2, target.branch.last_revision())

    def test_push_to_checkout_updates_master(self):
        """Pushing into a checkout updates the checkout and the master branch."""
        master_tree = self.make_to_branch_and_tree("master")
        checkout = self.make_to_branch_and_tree("checkout")
        try:
            checkout.branch.bind(master_tree.branch)
        except BindingUnsupported:
            # cant bind this format, the test is irrelevant.
            return
        checkout.commit("master")

        try:
            other_bzrdir = self.sprout_from(master_tree.branch.controldir, "other")
        except errors.NoRoundtrippingSupport:
            raise tests.TestNotApplicable(
                "lossless push between {!r} and {!r} not supported".format(
                    self.branch_format_from, self.branch_format_to
                )
            )
        other = other_bzrdir.open_workingtree()
        rev2 = other.commit("other commit")
        # now push, which should update both checkout and master.
        other.branch.push(checkout.branch)
        self.assertEqual(rev2, checkout.branch.last_revision())
        self.assertEqual(rev2, master_tree.branch.last_revision())

    def test_push_raises_specific_error_on_master_connection_error(self):
        master_tree = self.make_to_branch_and_tree("master")
        checkout = self.make_to_branch_and_tree("checkout")
        try:
            checkout.branch.bind(master_tree.branch)
        except BindingUnsupported:
            # cant bind this format, the test is irrelevant.
            return
        other_bzrdir = self.sprout_from(master_tree.branch.controldir, "other")
        other = other_bzrdir.open_workingtree()
        # move the branch out of the way on disk to cause a connection
        # error.
        master_tree.controldir.destroy_branch()
        # try to push, which should raise a BoundBranchConnectionFailure.
        self.assertRaises(
            errors.BoundBranchConnectionFailure, other.branch.push, checkout.branch
        )

    def test_push_uses_read_lock(self):
        """Push should only need a read lock on the source side."""
        source = self.make_from_branch_and_tree("source")
        target = self.make_to_branch("target")

        self.build_tree(["source/a"])
        source.add(["a"])
        source.commit("a")

        try:
            with source.branch.lock_read(), target.lock_write():
                source.branch.push(target, stop_revision=source.last_revision())
        except errors.NoRoundtrippingSupport:
            raise tests.TestNotApplicable(
                "lossless push between {!r} and {!r} not supported".format(
                    self.branch_format_from, self.branch_format_to
                )
            )

    def test_push_uses_read_lock_lossy(self):
        """Push should only need a read lock on the source side."""
        source = self.make_from_branch_and_tree("source")
        target = self.make_to_branch("target")

        self.build_tree(["source/a"])
        source.add(["a"])
        source.commit("a")

        try:
            with source.branch.lock_read(), target.lock_write():
                source.branch.push(
                    target, stop_revision=source.last_revision(), lossy=True
                )
        except errors.LossyPushToSameVCS:
            raise tests.TestNotApplicable("push between branches of same format")

    def test_between_colocated(self):
        """Pushing from one colocated branch to another doesn't change the active branch."""
        source = self.make_from_branch_and_tree("source")
        target = self.make_to_branch("target")

        self.build_tree(["source/a"])
        source.add(["a"])
        revid1 = source.commit("a")

        self.build_tree(["source/b"])
        source.add(["b"])
        revid2 = source.commit("b")

        source_colo = source.controldir.create_branch("colo")
        source_colo.generate_revision_history(revid1)
        try:
            source_colo.push(target)
        except errors.NoRoundtrippingSupport:
            raise tests.TestNotApplicable("push between branches of different format")
        self.assertEqual(source_colo.last_revision(), revid1)
        self.assertEqual(source.last_revision(), revid2)
        self.assertEqual(target.last_revision(), revid1)

    def test_push_within_repository(self):
        """Push from one branch to another inside the same repository."""
        try:
            self.make_repository("repo", shared=True)
        except (errors.IncompatibleFormat, errors.UninitializableFormat):
            # This Branch format cannot create shared repositories
            return
        # This is a little bit trickier because make_from_branch_and_tree will not
        # re-use a shared repository.
        try:
            a_branch = self.make_from_branch("repo/tree")
        except errors.UninitializableFormat:
            # Cannot create these branches
            return
        try:
            tree = a_branch.controldir.create_workingtree()
        except errors.UnsupportedOperation:
            self.assertFalse(a_branch.controldir._format.supports_workingtrees)
            tree = a_branch.create_checkout("repo/tree", lightweight=True)
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

        to_branch = self.make_to_branch("repo/branch")
        try:
            tree.branch.push(to_branch)
        except errors.NoRoundtrippingSupport:
            tree.branch.push(to_branch, lossy=True)
        else:
            self.assertEqual(tree.branch.last_revision(), to_branch.last_revision())

    def test_push_overwrite_of_non_tip_with_stop_revision(self):
        """Combining the stop_revision and overwrite options works.

        This was <https://bugs.launchpad.net/bzr/+bug/234229>.
        """
        source = self.make_from_branch_and_tree("source")
        target = self.make_to_branch("target")

        source.commit("1st commit")
        try:
            source.branch.push(target)
        except errors.NoRoundtrippingSupport:
            raise tests.TestNotApplicable(
                "lossless push between {!r} and {!r} not supported".format(
                    self.branch_format_from, self.branch_format_to
                )
            )
        rev2 = source.commit("2nd commit")
        source.commit("3rd commit")

        source.branch.push(target, stop_revision=rev2, overwrite=True)
        self.assertEqual(rev2, target.last_revision())

    def test_push_with_default_stacking_does_not_create_broken_branch(self):
        """Pushing a new standalone branch works even when there's a default
        stacking policy at the destination.

        The new branch will preserve the repo format (even if it isn't the
        default for the branch), and will be stacked when the repo format
        allows (which means that the branch format isn't necessarly preserved).
        """
        if isinstance(self.branch_format_from, bzrbranch.BranchReferenceFormat):
            # This test could in principle apply to BranchReferenceFormat, but
            # make_branch_builder doesn't support it.
            raise tests.TestSkipped("BranchBuilder can't make reference branches.")
        # Make a branch called "local" in a stackable repository
        # The branch has 3 revisions:
        #   - rev-1, adds a file
        #   - rev-2, no changes
        #   - rev-3, modifies the file.
        self.make_repository("repo", shared=True, format="1.6")
        try:
            builder = self.make_from_branch_builder("repo/local")
        except errors.UninitializableFormat:
            raise tests.TestNotApplicable(
                "BranchBuilder can not initialize some formats"
            )
        builder.start_series()
        revid1 = builder.build_snapshot(
            None,
            [
                ("add", ("", None, "directory", "")),
                ("add", ("filename", None, "file", b"content\n")),
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
        remote_branch = Branch.open(self.get_url("remote"))
        trunk.push(remote_branch)
        check.check_dwim(remote_branch.base, False, True, True)

    def test_no_get_parent_map_after_insert_stream(self):
        # Effort test for bug 331823
        self.setup_smart_server_with_call_log()
        # Make a local branch with four revisions.  Four revisions because:
        # one to push, one there for _walk_to_common_revisions to find, one we
        # don't want to access, one for luck :)
        if isinstance(self.branch_format_from, bzrbranch.BranchReferenceFormat):
            # This test could in principle apply to BranchReferenceFormat, but
            # make_branch_builder doesn't support it.
            raise tests.TestSkipped("BranchBuilder can't make reference branches.")
        try:
            builder = self.make_from_branch_builder("local")
        except (errors.TransportNotPossible, errors.UninitializableFormat):
            raise tests.TestNotApplicable("format not directly constructable")
        builder.start_series()
        first = builder.build_snapshot(None, [("add", ("", None, "directory", ""))])
        second = builder.build_snapshot([first], [])
        third = builder.build_snapshot([second], [])
        builder.build_snapshot([third], [])
        builder.finish_series()
        local = branch.Branch.open(self.get_vfs_only_url("local"))
        # Initial push of three revisions
        remote_bzrdir = local.controldir.sprout(
            self.get_url("remote"), revision_id=third
        )
        remote = remote_bzrdir.open_branch()
        if not remote.repository._format.supports_full_versioned_files:
            raise tests.TestNotApplicable("remote is not a VersionedFile repository")
        # Push fourth revision
        self.reset_smart_call_log()
        self.disableOptimisticGetParentMap()
        self.assertFalse(local.is_locked())
        local.push(remote)
        hpss_call_names = [item.call.method for item in self.hpss_calls]
        self.assertIn(b"Repository.insert_stream_1.19", hpss_call_names)
        insert_stream_idx = hpss_call_names.index(b"Repository.insert_stream_1.19")
        calls_after_insert_stream = hpss_call_names[insert_stream_idx:]
        # After inserting the stream the client has no reason to query the
        # remote graph any further.
        bzr_core_trace = Equals(
            [
                b"Repository.insert_stream_1.19",
                b"Repository.insert_stream_1.19",
                b"Branch.set_last_revision_info",
                b"Branch.unlock",
            ]
        )
        bzr_loom_trace = Equals(
            [
                b"Repository.insert_stream_1.19",
                b"Repository.insert_stream_1.19",
                b"Branch.set_last_revision_info",
                b"get",
                b"Branch.unlock",
            ]
        )
        self.assertThat(
            calls_after_insert_stream, MatchesAny(bzr_core_trace, bzr_loom_trace)
        )

    def disableOptimisticGetParentMap(self):
        # Tweak some class variables to stop remote get_parent_map calls asking
        # for or receiving more data than the caller asked for.
        self.overrideAttr(
            vf_repository.InterVersionedFileRepository,
            "_walk_to_common_revisions_batch_size",
            1,
        )
        self.overrideAttr(SmartServerRepositoryGetParentMap, "no_extra_results", True)

    def test_push_tag_selector(self):
        if not self.branch_format_from.supports_tags():
            raise tests.TestNotApplicable("from format does not support tags")
        if not self.branch_format_to.supports_tags():
            raise tests.TestNotApplicable("to format does not support tags")
        tree_a = self.make_from_branch_and_tree("tree_a")
        revid1 = tree_a.commit("message 1")
        try:
            tree_b = self.sprout_to(tree_a.controldir, "tree_b").open_workingtree()
        except errors.NoRoundtrippingSupport:
            raise tests.TestNotApplicable(
                "lossless push between {!r} and {!r} not supported".format(
                    self.branch_format_from, self.branch_format_to
                )
            )
        tree_b.branch.tags.set_tag("tag1", revid1)
        tree_b.branch.tags.set_tag("tag2", revid1)
        tree_b.branch.get_config_stack().set("branch.fetch_tags", True)
        tree_b.branch.push(tree_a.branch, tag_selector=lambda x: x == "tag1")
        self.assertEqual({"tag1": revid1}, tree_a.branch.tags.get_tag_dict())


class TestPushHook(TestCaseWithInterBranch):
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
        target = self.make_to_branch("target")
        source = self.make_from_branch("source")
        Branch.hooks.install_named_hook("post_push", self.capture_post_push_hook, None)
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
                    NULL_REVISION,
                    0,
                    NULL_REVISION,
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
        target = self.make_to_branch("target")
        local = self.make_from_branch("local")
        try:
            local.bind(target)
        except BindingUnsupported:
            # We can't bind this format to itself- typically it is the local
            # branch that doesn't support binding.  As of May 2007
            # remotebranches can't be bound.  Let's instead make a new local
            # branch of the default type, which does allow binding.
            # See https://bugs.launchpad.net/bzr/+bug/112020
            local = ControlDir.create_branch_convenience("local2")
            local.bind(target)
        source = self.make_from_branch("source")
        Branch.hooks.install_named_hook("post_push", self.capture_post_push_hook, None)
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
                    NULL_REVISION,
                    0,
                    NULL_REVISION,
                    True,
                    True,
                    True,
                )
            ],
            self.hook_calls,
        )

    def test_post_push_nonempty_history(self):
        target = self.make_to_branch_and_tree("target")
        target.lock_write()
        target.add("")
        rev1 = target.commit("rev 1")
        target.unlock()
        sourcedir = target.branch.controldir.clone(self.get_url("source"))
        source = sourcedir.open_branch().create_memorytree()
        rev2 = source.commit("rev 2")
        Branch.hooks.install_named_hook("post_push", self.capture_post_push_hook, None)
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
