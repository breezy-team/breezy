# Copyright (C) 2006, 2007, 2009 Canonical Ltd
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

"""Black box tests for the upgrade ui."""

import os

from bzrlib import (
    bzrdir,
    repository,
    ui,
    )
from bzrlib.tests import (
    TestCaseInTempDir,
    TestCaseWithTransport,
    TestUIFactory,
    )
from bzrlib.tests.test_sftp_transport import TestCaseWithSFTPServer
from bzrlib.transport import get_transport
from bzrlib.repofmt.knitrepo import (
    RepositoryFormatKnit1,
    )


class TestWithUpgradableBranches(TestCaseWithTransport):

    def setUp(self):
        super(TestWithUpgradableBranches, self).setUp()
        self.old_format = bzrdir.BzrDirFormat.get_default_format()
        self.old_ui_factory = ui.ui_factory
        self.addCleanup(self.restoreDefaults)
        ui.ui_factory = TestUIFactory()

    def restoreDefaults(self):
        ui.ui_factory = self.old_ui_factory
        bzrdir.BzrDirFormat._set_default_format(self.old_format)

    def make_current_format_branch_and_checkout(self):
        current_tree = self.make_branch_and_tree('current_format_branch',
                                                 format='default')
        current_tree.branch.create_checkout(
            self.get_url('current_format_checkout'), lightweight=True)

    def make_format_5_branch(self):
        # setup a format 5 branch we can upgrade from.
        self.make_branch_and_tree('format_5_branch',
                                  format=bzrdir.BzrDirFormat5())

    def make_metadir_weave_branch(self):
        self.make_branch_and_tree('metadir_weave_branch', format='metaweave')

    def test_readonly_url_error(self):
        self.make_format_5_branch()
        (out, err) = self.run_bzr(
            ['upgrade', self.get_readonly_url('format_5_branch')], retcode=3)
        self.assertEqual(out, "")
        self.assertEqual(err, "bzr: ERROR: Upgrade URL cannot work with readonly URLs.\n")

    def test_upgrade_up_to_date(self):
        self.make_current_format_branch_and_checkout()
        # when up to date we should get a message to that effect
        (out, err) = self.run_bzr('upgrade current_format_branch', retcode=3)
        self.assertEqual("", out)
        self.assertEqualDiff("bzr: ERROR: The branch format Meta "
                             "directory format 1 is already at the most "
                             "recent format.\n", err)

    def test_upgrade_up_to_date_checkout_warns_branch_left_alone(self):
        self.make_current_format_branch_and_checkout()
        # when upgrading a checkout, the branch location and a suggestion
        # to upgrade it should be emitted even if the checkout is up to
        # date
        (out, err) = self.run_bzr('upgrade current_format_checkout', retcode=3)
        self.assertEqual("This is a checkout. The branch (%s) needs to be "
                         "upgraded separately.\n"
                         % get_transport(self.get_url('current_format_branch')).base,
                         out)
        self.assertEqualDiff("bzr: ERROR: The branch format Meta "
                             "directory format 1 is already at the most "
                             "recent format.\n", err)

    def test_upgrade_checkout(self):
        # upgrading a checkout should work
        pass

    def test_upgrade_repository_scans_branches(self):
        # we should get individual upgrade notes for each branch even the
        # anonymous branch
        pass

    def test_ugrade_branch_in_repo(self):
        # upgrading a branch in a repo should warn about not upgrading the repo
        pass

    def test_upgrade_explicit_metaformat(self):
        # users can force an upgrade to metadir format.
        self.make_format_5_branch()
        url = get_transport(self.get_url('format_5_branch')).base
        # check --format takes effect
        bzrdir.BzrDirFormat._set_default_format(bzrdir.BzrDirFormat5())
        (out, err) = self.run_bzr(
            ['upgrade', '--format=metaweave', url])
        self.assertEqualDiff("""starting upgrade of %s
making backup of %s.bzr
  to %sbackup.bzr
starting upgrade from format 5 to 6
adding prefixes to weaves
adding prefixes to revision-store
starting upgrade from format 6 to metadir
finished
""" % (url, url, url), out)
        self.assertEqualDiff("", err)
        self.assertTrue(isinstance(
            bzrdir.BzrDir.open(self.get_url('format_5_branch'))._format,
            bzrdir.BzrDirMetaFormat1))

    def test_upgrade_explicit_knit(self):
        # users can force an upgrade to knit format from a metadir weave
        # branch
        self.make_metadir_weave_branch()
        url = get_transport(self.get_url('metadir_weave_branch')).base
        # check --format takes effect
        bzrdir.BzrDirFormat._set_default_format(bzrdir.BzrDirFormat5())
        (out, err) = self.run_bzr(
            ['upgrade', '--format=knit', url])
        self.assertEqualDiff("""starting upgrade of %s
making backup of %s.bzr
  to %sbackup.bzr
starting repository conversion
repository converted
finished
""" % (url, url, url), out)
        self.assertEqualDiff("", err)
        converted_dir = bzrdir.BzrDir.open(self.get_url('metadir_weave_branch'))
        self.assertTrue(isinstance(converted_dir._format,
                                   bzrdir.BzrDirMetaFormat1))
        self.assertTrue(isinstance(converted_dir.open_repository()._format,
                                   RepositoryFormatKnit1))

    def test_upgrade_repo(self):
        self.run_bzr('init-repository --format=metaweave repo')
        self.run_bzr('upgrade --format=knit repo')


class SFTPTests(TestCaseWithSFTPServer):
    """Tests for upgrade over sftp."""

    def setUp(self):
        super(SFTPTests, self).setUp()
        self.old_ui_factory = ui.ui_factory
        self.addCleanup(self.restoreDefaults)

        ui.ui_factory = TestUIFactory()

    def restoreDefaults(self):
        ui.ui_factory = self.old_ui_factory

    def test_upgrade_url(self):
        self.run_bzr('init --format=weave')
        t = get_transport(self.get_url())
        url = t.base
        out, err = self.run_bzr(['upgrade', '--format=knit', url])
        self.assertEqualDiff("""starting upgrade of %s
making backup of %s.bzr
  to %sbackup.bzr
starting upgrade from format 6 to metadir
starting repository conversion
repository converted
finished
""" % (url, url, url), out)
        self.assertEqual('', err)


class UpgradeRecommendedTests(TestCaseWithTransport):

    def test_recommend_upgrade_wt4(self):
        # using a deprecated format gives a warning
        self.run_bzr('init --knit a')
        out, err = self.run_bzr('status a')
        self.assertContainsRe(err, 'bzr upgrade .*[/\\\\]a')

    def test_no_upgrade_recommendation_from_bzrdir(self):
        # we should only get a recommendation to upgrade when we're accessing
        # the actual workingtree, not when we only open a bzrdir that contains
        # an old workngtree
        self.run_bzr('init --knit a')
        out, err = self.run_bzr('revno a')
        if err.find('upgrade') > -1:
            self.fail("message shouldn't suggest upgrade:\n%s" % err)

    def test_upgrade_shared_repo(self):
        repo = self.make_repository('repo', format='2a', shared=True)
        branch = self.make_branch_and_tree('repo/branch', format="pack-0.92")
        self.get_transport('repo/branch/.bzr/repository').delete_tree('.')
        out, err = self.run_bzr(['upgrade'], working_dir='repo/branch')
