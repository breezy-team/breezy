# Copyright (C) 2010, 2011, 2012, 2016 Canonical Ltd
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

"""Tests for bzr directories that support colocated branches."""

from breezy import branchbuilder, errors, tests, urlutils
from breezy.tests import per_controldir

from ...branch import Branch
from ...controldir import BranchReferenceLoop
from ..features import UnicodeFilenameFeature


class TestColocatedBranchSupport(per_controldir.TestCaseWithControlDir):
    def create_branch(self, bzrdir, name=None):
        branch = bzrdir.create_branch(name=name)
        # Create a commit on the branch, just because some formats
        # have nascent branches that don't hit disk.
        bb = branchbuilder.BranchBuilder(branch=branch)
        bb.build_commit()
        return branch

    def test_destroy_colocated_branch(self):
        branch = self.make_branch("branch")
        bzrdir = branch.controldir
        self.create_branch(bzrdir, "colo")
        try:
            bzrdir.destroy_branch("colo")
        except (errors.UnsupportedOperation, errors.TransportNotPossible) as e:
            raise tests.TestNotApplicable(
                "Format does not support destroying branch"
            ) from e
        self.assertRaises(errors.NotBranchError, bzrdir.open_branch, "colo")

    def test_create_colo_branch(self):
        # a bzrdir can construct a branch and repository for itself.
        if not self.bzrdir_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            raise tests.TestNotApplicable("Control dir format not supported")
        t = self.get_transport()
        try:
            made_control = self.bzrdir_format.initialize(t.base)
        except errors.UninitializableFormat as e:
            raise tests.TestNotApplicable(
                "Control dir does not support creating new branches."
            ) from e
        made_control.create_repository()
        made_branch = made_control.create_branch("colo")
        self.assertIsInstance(made_branch, Branch)
        self.assertEqual("colo", made_branch.name)
        self.assertEqual(made_control, made_branch.controldir)

    def test_open_by_url(self):
        # a bzrdir can construct a branch and repository for itself.
        if not self.bzrdir_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            raise tests.TestNotApplicable("Control dir format not supported")
        t = self.get_transport()
        try:
            made_control = self.bzrdir_format.initialize(t.base)
        except errors.UninitializableFormat as e:
            raise tests.TestNotApplicable(
                "Control dir does not support creating new branches."
            ) from e
        made_control.create_repository()
        made_branch = self.create_branch(made_control, name="colo")
        other_branch = self.create_branch(made_control, name="othercolo")
        self.assertIsInstance(made_branch, Branch)
        self.assertEqual(made_control, made_branch.controldir)
        self.assertNotEqual(made_branch.user_url, other_branch.user_url)
        self.assertNotEqual(made_branch.control_url, other_branch.control_url)
        re_made_branch = Branch.open(made_branch.user_url)
        self.assertEqual(re_made_branch.name, "colo")
        self.assertEqual(made_branch.control_url, re_made_branch.control_url)
        self.assertEqual(made_branch.user_url, re_made_branch.user_url)

    def test_sprout_into_colocated(self):
        # a bzrdir can construct a branch and repository for itself.
        if not self.bzrdir_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            raise tests.TestNotApplicable("Control dir format not supported")
        from_tree = self.make_branch_and_tree("from")
        revid = from_tree.commit("rev1")
        try:
            other_branch = self.make_branch("to")
        except errors.UninitializableFormat as e:
            raise tests.TestNotApplicable(
                "Control dir does not support creating new branches."
            ) from e
        to_dir = from_tree.controldir.sprout(
            urlutils.join_segment_parameters(
                other_branch.user_url, {"branch": "target"}
            )
        )
        to_branch = to_dir.open_branch(name="target")
        self.assertEqual(revid, to_branch.last_revision())

    def test_sprout_into_colocated_leaves_workingtree(self):
        # a bzrdir can construct a branch and repository for itself.
        if not self.bzrdir_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            raise tests.TestNotApplicable("Control dir format not supported")
        if not self.bzrdir_format.supports_workingtrees:
            raise tests.TestNotApplicable(
                "Control dir format does not support working trees"
            )
        from_tree = self.make_branch_and_tree("from")
        self.build_tree_contents([("from/foo", "contents")])
        from_tree.add(["foo"])
        revid1 = from_tree.commit("rev1")
        self.build_tree_contents([("from/foo", "new contents")])
        revid2 = from_tree.commit("rev2")
        try:
            other_branch = self.make_branch_and_tree("to")
        except errors.UninitializableFormat as e:
            raise tests.TestNotApplicable(
                "Control dir does not support creating new branches."
            ) from e

        result = other_branch.controldir.push_branch(
            from_tree.branch, revision_id=revid1
        )
        self.assertTrue(result.workingtree_updated)
        self.assertFileEqual("contents", "to/foo")

        from_tree.controldir.sprout(
            urlutils.join_segment_parameters(
                other_branch.user_url, {"branch": "target"}
            ),
            revision_id=revid2,
        )
        active_branch = other_branch.controldir.open_branch(name="")
        self.assertEqual(revid1, active_branch.last_revision())
        to_branch = other_branch.controldir.open_branch(name="target")
        self.assertEqual(revid2, to_branch.last_revision())
        self.assertFileEqual("contents", "to/foo")

    def test_unicode(self):
        self.requireFeature(UnicodeFilenameFeature)
        if not self.bzrdir_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            raise tests.TestNotApplicable("Control dir format not supported")
        t = self.get_transport()
        try:
            made_control = self.bzrdir_format.initialize(t.base)
        except errors.UninitializableFormat as e:
            raise tests.TestNotApplicable(
                "Control dir does not support creating new branches."
            ) from e
        made_control.create_repository()
        made_branch = self.create_branch(made_control, name="col\xe9")
        self.assertIn("col\xe9", [b.name for b in made_control.list_branches()])
        made_branch = Branch.open(made_branch.user_url)
        self.assertEqual("col\xe9", made_branch.name)
        made_control.destroy_branch("col\xe9")

    def test_get_branches(self):
        repo = self.make_repository("branch-1")
        self.assertNotIn("foo", list(repo.controldir.get_branches()))
        target_branch = self.create_branch(repo.controldir, name="foo")
        self.assertIn("foo", list(repo.controldir.get_branches()))
        self.assertEqual(target_branch.base, repo.controldir.get_branches()["foo"].base)

    def test_branch_names(self):
        repo = self.make_repository("branch-1")
        self.create_branch(repo.controldir, name="foo")
        self.assertIn("foo", repo.controldir.branch_names())

    def test_branch_name_with_slash(self):
        repo = self.make_repository("branch-1")
        try:
            target_branch = self.create_branch(repo.controldir, name="foo/bar")
        except errors.InvalidBranchName as e:
            raise tests.TestNotApplicable(
                "format does not support branches with / in their name"
            ) from e
        self.assertIn("foo/bar", list(repo.controldir.get_branches()))
        self.assertEqual(
            target_branch.base, repo.controldir.open_branch(name="foo/bar").base
        )

    def test_branch_reference(self):
        referenced = self.make_branch("referenced")
        repo = self.make_repository("repo")
        try:
            repo.controldir.set_branch_reference(referenced, name="foo")
        except errors.IncompatibleFormat as e:
            raise tests.TestNotApplicable(
                "Control dir does not support creating branch references."
            ) from e
        self.assertEqual(
            referenced.user_url, repo.controldir.get_branch_reference("foo")
        )

    def test_branch_reference_loop(self):
        repo = self.make_repository("repo")
        to_branch = self.create_branch(repo.controldir, name="somebranch")
        try:
            self.assertRaises(
                BranchReferenceLoop,
                repo.controldir.set_branch_reference,
                to_branch,
                name="somebranch",
            )
        except errors.IncompatibleFormat as e:
            raise tests.TestNotApplicable(
                "Control dir does not support creating branch references."
            ) from e
