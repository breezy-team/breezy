# Copyright (C) 2009-2012 Canonical Ltd
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

"""Tests for branch.create_clone behaviour."""

from breezy import branch, errors, tests
from breezy.bzr import remote
from breezy.tests import per_branch
from breezy.transport import FileExists, NoSuchFile


class TestCreateClone(per_branch.TestCaseWithBranch):
    def test_create_clone_on_transport_missing_parent_dir(self):
        tree = self.make_branch_and_tree("source")
        tree.commit("a commit")
        target_transport = self.get_transport("subdir").clone("target")
        self.assertRaises(
            NoSuchFile, tree.branch.create_clone_on_transport, target_transport
        )
        self.assertFalse(self.get_transport(".").has("subdir"))

    def test_create_clone_on_transport_missing_parent_dir_create(self):
        tree = self.make_branch_and_tree("source")
        tree.commit("a commit")
        source = tree.branch
        target_transport = self.get_transport("subdir").clone("target")
        result = tree.branch.create_clone_on_transport(
            target_transport, create_prefix=True
        )
        self.assertEqual(source.last_revision(), result.last_revision())
        self.assertEqual(target_transport.base, result.controldir.root_transport.base)

    def test_create_clone_on_transport_use_existing_dir_false(self):
        tree = self.make_branch_and_tree("source")
        tree.commit("a commit")
        target_transport = self.get_transport("target")
        target_transport.create_prefix()
        self.assertRaises(
            FileExists, tree.branch.create_clone_on_transport, target_transport
        )
        self.assertFalse(target_transport.has(".bzr"))

    def test_create_clone_on_transport_use_existing_dir_true(self):
        tree = self.make_branch_and_tree("source")
        tree.commit("a commit")
        source = tree.branch
        target_transport = self.get_transport("target")
        target_transport.create_prefix()
        result = tree.branch.create_clone_on_transport(
            target_transport, use_existing_dir=True
        )
        self.assertEqual(source.last_revision(), result.last_revision())

    def test_create_clone_on_transport_no_revision_id(self):
        tree = self.make_branch_and_tree("source")
        tree.commit("a commit")
        source = tree.branch
        target_transport = self.get_transport("target")
        result = tree.branch.create_clone_on_transport(target_transport)
        self.assertEqual(source.last_revision(), result.last_revision())

    def test_create_clone_on_transport_revision_id(self):
        tree = self.make_branch_and_tree("source")
        old_revid = tree.commit("a commit")
        source_tip = tree.commit("a second commit")
        target_transport = self.get_transport("target")
        result = tree.branch.create_clone_on_transport(
            target_transport, revision_id=old_revid
        )
        self.assertEqual(old_revid, result.last_revision())
        result.lock_read()
        self.addCleanup(result.unlock)
        self.assertFalse(result.repository.has_revision(source_tip))

    def test_create_clone_on_transport_stacked(self):
        tree = self.make_branch_and_tree("source")
        tree.commit("a commit")
        trunk = tree.branch.create_clone_on_transport(self.get_transport("trunk"))
        revid = tree.commit("a second commit")
        target_transport = self.get_transport("target")
        try:
            result = tree.branch.create_clone_on_transport(
                target_transport, stacked_on=trunk.base
            )
        except branch.UnstackableBranchFormat:
            if not trunk.repository._format.supports_full_versioned_files:
                raise tests.TestNotApplicable("can not stack on format")
            raise
        self.assertEqual(revid, result.last_revision())
        self.assertEqual(trunk.base, result.get_stacked_on_url())

    def test_create_clone_of_multiple_roots(self):
        try:
            builder = self.make_branch_builder("local")
        except (errors.TransportNotPossible, errors.UninitializableFormat):
            raise tests.TestNotApplicable("format not directly constructable")
        builder.start_series()
        rev1 = builder.build_snapshot(None, [("add", ("", None, "directory", ""))])
        rev2 = builder.build_snapshot([rev1], [])
        other = builder.build_snapshot(None, [("add", ("", None, "directory", ""))])
        rev3 = builder.build_snapshot([rev2, other], [])
        builder.finish_series()
        local = builder.get_branch()
        local.controldir.clone(self.get_url("remote"), revision_id=rev3)

    def assertBranchHookBranchIsStacked(self, pre_change_params):
        # Just calling will either succeed or fail.
        pre_change_params.branch.get_stacked_on_url()
        self.hook_calls.append(pre_change_params)

    def test_create_clone_on_transport_stacked_hooks_get_stacked_branch(self):
        tree = self.make_branch_and_tree("source")
        tree.commit("a commit")
        trunk = tree.branch.create_clone_on_transport(self.get_transport("trunk"))
        revid = tree.commit("a second commit")
        target_transport = self.get_transport("target")
        self.hook_calls = []
        branch.Branch.hooks.install_named_hook(
            "pre_change_branch_tip", self.assertBranchHookBranchIsStacked, None
        )
        try:
            result = tree.branch.create_clone_on_transport(
                target_transport, stacked_on=trunk.base
            )
        except branch.UnstackableBranchFormat:
            if not trunk.repository._format.supports_full_versioned_files:
                raise tests.TestNotApplicable("can not stack on format")
            raise
        self.assertEqual(revid, result.last_revision())
        self.assertEqual(trunk.base, result.get_stacked_on_url())
        # Smart servers invoke hooks on both sides
        if isinstance(result, remote.RemoteBranch):
            expected_calls = 2
        else:
            expected_calls = 1
        self.assertEqual(expected_calls, len(self.hook_calls))
