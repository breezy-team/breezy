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

from bzrlib.branch import Branch
from bzrlib import (
    errors,
    tests,
    urlutils,
    )
from bzrlib.tests import (
    per_controldir,
    )
from bzrlib.tests.features import (
    UnicodeFilenameFeature,
    )


class TestColocatedBranchSupport(per_controldir.TestCaseWithControlDir):

    def test_destroy_colocated_branch(self):
        branch = self.make_branch('branch')
        bzrdir = branch.bzrdir
        colo_branch = bzrdir.create_branch('colo')
        try:
            bzrdir.destroy_branch("colo")
        except (errors.UnsupportedOperation, errors.TransportNotPossible):
            raise tests.TestNotApplicable('Format does not support destroying branch')
        self.assertRaises(errors.NotBranchError, bzrdir.open_branch,
                          "colo")

    def test_create_colo_branch(self):
        # a bzrdir can construct a branch and repository for itself.
        if not self.bzrdir_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            raise tests.TestNotApplicable('Control dir format not supported')
        t = self.get_transport()
        try:
            made_control = self.bzrdir_format.initialize(t.base)
        except errors.UninitializableFormat:
            raise tests.TestNotApplicable(
                'Control dir does not support creating new branches.')
        made_control.create_repository()
        made_branch = made_control.create_branch("colo")
        self.assertIsInstance(made_branch, Branch)
        self.assertEqual("colo", made_branch.name)
        self.assertEqual(made_control, made_branch.bzrdir)

    def test_open_by_url(self):
        # a bzrdir can construct a branch and repository for itself.
        if not self.bzrdir_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            raise tests.TestNotApplicable('Control dir format not supported')
        t = self.get_transport()
        try:
            made_control = self.bzrdir_format.initialize(t.base)
        except errors.UninitializableFormat:
            raise tests.TestNotApplicable(
                'Control dir does not support creating new branches.')
        made_control.create_repository()
        made_branch = made_control.create_branch(name="colo")
        other_branch = made_control.create_branch(name="othercolo")
        self.assertIsInstance(made_branch, Branch)
        self.assertEqual(made_control, made_branch.bzrdir)
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
            raise tests.TestNotApplicable('Control dir format not supported')
        from_tree = self.make_branch_and_tree('from')
        revid = from_tree.commit("rev1")
        try:
            other_branch = self.make_branch("to")
        except errors.UninitializableFormat:
            raise tests.TestNotApplicable(
                'Control dir does not support creating new branches.')
        to_dir = from_tree.bzrdir.sprout(
            urlutils.join_segment_parameters(
                other_branch.bzrdir.user_url, {"branch": "target"}))
        to_branch = to_dir.open_branch(name="target")
        self.assertEqual(revid, to_branch.last_revision())

    def test_unicode(self):
        self.requireFeature(UnicodeFilenameFeature)
        if not self.bzrdir_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            raise tests.TestNotApplicable('Control dir format not supported')
        t = self.get_transport()
        try:
            made_control = self.bzrdir_format.initialize(t.base)
        except errors.UninitializableFormat:
            raise tests.TestNotApplicable(
                'Control dir does not support creating new branches.')
        made_control.create_repository()
        made_branch = made_control.create_branch(name=u"col\xe9")
        self.assertTrue(
            u"col\xe9" in [b.name for b in made_control.list_branches()])
        made_branch = Branch.open(made_branch.user_url)
        self.assertEqual(u"col\xe9", made_branch.name)
        made_control.destroy_branch(u"col\xe9")

    def test_get_branches(self):
        repo = self.make_repository('branch-1')
        target_branch = repo.bzrdir.create_branch(name='foo')
        self.assertEqual(['foo'], repo.bzrdir.get_branches().keys())
        self.assertEqual(target_branch.base,
                         repo.bzrdir.get_branches()['foo'].base)

    def test_branch_name_with_slash(self):
        repo = self.make_repository('branch-1')
        try:
            target_branch = repo.bzrdir.create_branch(name='foo/bar')
        except errors.InvalidBranchName:
            raise tests.TestNotApplicable(
                "format does not support branches with / in their name")
        self.assertEqual(['foo/bar'], repo.bzrdir.get_branches().keys())
        self.assertEqual(
            target_branch.base, repo.bzrdir.open_branch(name='foo/bar').base)

    def test_branch_reference(self):
        referenced = self.make_branch('referenced')
        repo = self.make_repository('repo')
        try:
            repo.bzrdir.set_branch_reference(referenced, name='foo')
        except errors.IncompatibleFormat:
            raise tests.TestNotApplicable(
                'Control dir does not support creating branch references.')
        self.assertEqual(referenced.base,
            repo.bzrdir.get_branch_reference('foo'))
