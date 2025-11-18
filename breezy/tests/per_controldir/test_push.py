# Copyright (C) 2009, 2010, 2016 Canonical Ltd
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

"""Tests for controldir implementations - push."""

from breezy.tests.per_controldir import TestCaseWithControlDir

from ...controldir import NoColocatedBranchSupport
from ...errors import LossyPushToSameVCS, NoSuchRevision, TagsNotSupported
from .. import TestNotApplicable


class TestPush(TestCaseWithControlDir):
    def create_simple_tree(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/a"])
        tree.add(["a"])
        rev_1 = tree.commit("one")
        return tree, rev_1

    def test_push_new_branch(self):
        tree, _rev_1 = self.create_simple_tree()
        dir = self.make_repository("dir").controldir
        result = dir.push_branch(tree.branch)
        self.assertEqual(tree.branch, result.source_branch)
        self.assertEqual(dir.open_branch().base, result.target_branch.base)
        self.assertEqual(dir.open_branch().base, tree.branch.get_push_location())

    def test_push_to_colocated_active(self):
        tree, _rev_1 = self.create_simple_tree()
        dir = self.make_repository("dir").controldir
        try:
            result = dir.push_branch(tree.branch, name="colo")
        except NoColocatedBranchSupport:
            raise TestNotApplicable("no colocated branch support")
        self.assertEqual(tree.branch, result.source_branch)
        self.assertEqual(dir.open_branch(name="colo").base, result.target_branch.base)
        self.assertEqual(
            dir.open_branch(name="colo").base, tree.branch.get_push_location()
        )

    def test_push_to_colocated_new_inactive(self):
        tree, _rev_1 = self.create_simple_tree()
        target_tree = self.make_branch_and_tree("dir")
        rev_o = target_tree.commit("another")
        try:
            result = target_tree.branch.controldir.push_branch(tree.branch, name="colo")
        except NoColocatedBranchSupport:
            raise TestNotApplicable("no colocated branch support")
        target_branch = target_tree.branch.controldir.open_branch(name="colo")
        self.assertEqual(tree.branch, result.source_branch)
        self.assertEqual(target_tree.last_revision(), rev_o)
        self.assertEqual(target_tree.branch.last_revision(), rev_o)
        self.assertEqual(target_branch.base, result.target_branch.base)
        self.assertEqual(target_branch.base, tree.branch.get_push_location())
        self.assertNotEqual(target_branch.controldir.open_branch(name="").name, "colo")

    def test_push_to_colocated_existing_inactive(self):
        tree, _rev_1 = self.create_simple_tree()
        target_tree = self.make_branch_and_tree("dir")
        rev_o = target_tree.commit("another")
        try:
            target_tree.branch.controldir.create_branch(name="colo")
        except NoColocatedBranchSupport:
            raise TestNotApplicable("no colocated branch support")

        try:
            result = target_tree.branch.controldir.push_branch(tree.branch, name="colo")
        except NoColocatedBranchSupport:
            raise TestNotApplicable("no colocated branch support")
        target_branch = target_tree.branch.controldir.open_branch(name="colo")
        self.assertEqual(tree.branch, result.source_branch)
        self.assertEqual(target_tree.last_revision(), rev_o)
        self.assertEqual(target_tree.branch.last_revision(), rev_o)
        self.assertEqual(target_branch.base, result.target_branch.base)
        self.assertEqual(target_branch.base, tree.branch.get_push_location())

    def test_push_no_such_revision(self):
        tree, _rev_1 = self.create_simple_tree()
        dir = self.make_repository("dir").controldir
        self.assertRaises(
            NoSuchRevision, dir.push_branch, tree.branch, revision_id=b"idonotexist"
        )

    def test_push_new_branch_fetch_tags(self):
        builder = self.make_branch_builder("from")
        builder.start_series()
        rev_1 = builder.build_snapshot(
            None,
            [
                ("add", ("", None, "directory", "")),
                ("add", ("filename", None, "file", b"content")),
            ],
        )
        rev_2 = builder.build_snapshot(
            [rev_1], [("modify", ("filename", b"new-content\n"))]
        )
        rev_3 = builder.build_snapshot(
            [rev_1], [("modify", ("filename", b"new-new-content\n"))]
        )
        builder.finish_series()
        branch = builder.get_branch()
        try:
            branch.tags.set_tag("atag", rev_2)
        except TagsNotSupported:
            raise TestNotApplicable("source format does not support tags")

        dir = self.make_repository("target").controldir
        branch.get_config().set_user_option("branch.fetch_tags", True)
        result = dir.push_branch(branch)
        self.assertEqual(
            {rev_1, rev_2, rev_3},
            set(result.source_branch.repository.all_revision_ids()),
        )
        self.assertEqual({"atag": rev_2}, result.source_branch.tags.get_tag_dict())

    def test_push_new_branch_lossy(self):
        tree, _rev_1 = self.create_simple_tree()
        dir = self.make_repository("dir").controldir
        self.assertRaises(LossyPushToSameVCS, dir.push_branch, tree.branch, lossy=True)

    def test_push_new_empty(self):
        tree = self.make_branch_and_tree("tree")
        dir = self.make_repository("dir").controldir
        result = dir.push_branch(tree.branch)
        self.assertEqual(tree.branch.base, result.source_branch.base)
        self.assertEqual(dir.open_branch().base, result.target_branch.base)

    def test_push_incremental(self):
        tree, _rev1 = self.create_simple_tree()
        dir = self.make_repository("dir").controldir
        dir.push_branch(tree.branch)
        self.build_tree(["tree/b"])
        tree.add(["b"])
        tree.commit("two")
        result = dir.push_branch(tree.branch)
        self.assertEqual(tree.last_revision(), result.branch_push_result.new_revid)
        self.assertEqual(2, result.branch_push_result.new_revno)
        self.assertEqual(tree.branch.base, result.source_branch.base)
        self.assertEqual(dir.open_branch().base, result.target_branch.base)

    def test_push_tag_selector(self):
        tree, rev1 = self.create_simple_tree()
        try:
            tree.branch.tags.set_tag("tag1", rev1)
        except TagsNotSupported:
            raise TestNotApplicable("tags not supported")
        tree.branch.tags.set_tag("tag2", rev1)
        dir = self.make_repository("dir").controldir
        dir.push_branch(tree.branch, tag_selector=lambda x: x == "tag1")
        self.assertEqual({"tag1": rev1}, dir.open_branch().tags.get_tag_dict())
