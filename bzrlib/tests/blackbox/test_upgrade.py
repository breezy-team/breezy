# Copyright (C) 2006-2011 Canonical Ltd
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
import stat

from bzrlib import (
    bzrdir,
    controldir,
    transport,
    )
from bzrlib.tests import (
    features,
    TestCaseWithTransport,
    )
from bzrlib.tests.test_sftp_transport import TestCaseWithSFTPServer
from bzrlib.repofmt.knitrepo import (
    RepositoryFormatKnit1,
    )


class TestWithUpgradableBranches(TestCaseWithTransport):

    def setUp(self):
        super(TestWithUpgradableBranches, self).setUp()
        self.addCleanup(controldir.ControlDirFormat._set_default_format,
                        controldir.ControlDirFormat.get_default_format())

    def make_current_format_branch_and_checkout(self):
        current_tree = self.make_branch_and_tree('current_format_branch',
                                                 format='default')
        current_tree.branch.create_checkout(
            self.get_url('current_format_checkout'), lightweight=True)

    def make_format_5_branch(self):
        # setup a format 5 branch we can upgrade from.
        path = 'format_5_branch'
        self.make_branch_and_tree(path, format=bzrdir.BzrDirFormat5())
        return path

    def make_metadir_weave_branch(self):
        self.make_branch_and_tree('metadir_weave_branch', format='metaweave')

    def test_readonly_url_error(self):
        path = self.make_format_5_branch()
        (out, err) = self.run_bzr(
            ['upgrade', self.get_readonly_url(path)], retcode=3)
        err_msg = 'Upgrade URL cannot work with readonly URLs.'
        self.assertEqualDiff('conversion error: %s\nbzr: ERROR: %s\n'
                             % (err_msg, err_msg),
                             err)

    def test_upgrade_up_to_date(self):
        self.make_current_format_branch_and_checkout()
        # when up to date we should get a message to that effect
        (out, err) = self.run_bzr('upgrade current_format_branch', retcode=3)
        err_msg = ('The branch format %s is already at the most recent format.'
                   % ('Meta directory format 1'))
        self.assertEqualDiff('conversion error: %s\nbzr: ERROR: %s\n'
                             % (err_msg, err_msg),
                             err)

    def test_upgrade_up_to_date_checkout_warns_branch_left_alone(self):
        self.make_current_format_branch_and_checkout()
        # when upgrading a checkout, the branch location and a suggestion
        # to upgrade it should be emitted even if the checkout is up to
        # date
        burl = self.get_transport('current_format_branch').base
        curl = self.get_transport('current_format_checkout').base
        (out, err) = self.run_bzr('upgrade current_format_checkout', retcode=3)
        self.assertEqual(
            'Upgrading branch %s ...\nThis is a checkout.'
            ' The branch (%s) needs to be upgraded separately.\n'
            % (curl, burl),
            out)
        msg = 'The branch format %s is already at the most recent format.' % (
            'Meta directory format 1')
        self.assertEqualDiff('conversion error: %s\nbzr: ERROR: %s\n'
                             % (msg, msg),
                             err)

    def test_upgrade_checkout(self):
        # upgrading a checkout should work
        pass

    def test_upgrade_repository_scans_branches(self):
        # we should get individual upgrade notes for each branch even the
        # anonymous branch
        pass

    def test_upgrade_branch_in_repo(self):
        # upgrading a branch in a repo should warn about not upgrading the repo
        pass

    def test_upgrade_explicit_metaformat(self):
        # users can force an upgrade to metadir format.
        path = self.make_format_5_branch()
        url = self.get_transport(path).base
        # check --format takes effect
        controldir.ControlDirFormat._set_default_format(bzrdir.BzrDirFormat5())
        backup_dir = 'backup.bzr.~1~'
        (out, err) = self.run_bzr(
            ['upgrade', '--format=metaweave', url])
        self.assertEqualDiff("""Upgrading branch %s ...
starting upgrade of %s
making backup of %s.bzr
  to %s%s
starting upgrade from format 5 to 6
adding prefixes to weaves
adding prefixes to revision-store
starting upgrade from format 6 to metadir
finished
""" % (url, url, url, url, backup_dir), out)
        self.assertEqualDiff("", err)
        self.assertTrue(isinstance(
            bzrdir.BzrDir.open(self.get_url(path))._format,
            bzrdir.BzrDirMetaFormat1))

    def test_upgrade_explicit_knit(self):
        # users can force an upgrade to knit format from a metadir weave
        # branch
        self.make_metadir_weave_branch()
        url = self.get_transport('metadir_weave_branch').base
        # check --format takes effect
        controldir.ControlDirFormat._set_default_format(bzrdir.BzrDirFormat5())
        backup_dir = 'backup.bzr.~1~'
        (out, err) = self.run_bzr(
            ['upgrade', '--format=knit', url])
        self.assertEqualDiff("""Upgrading branch %s ...
starting upgrade of %s
making backup of %s.bzr
  to %s%s
starting repository conversion
repository converted
finished
""" % (url, url, url, url, backup_dir),
                             out)
        self.assertEqualDiff("", err)
        converted_dir = bzrdir.BzrDir.open(self.get_url('metadir_weave_branch'))
        self.assertTrue(isinstance(converted_dir._format,
                                   bzrdir.BzrDirMetaFormat1))
        self.assertTrue(isinstance(converted_dir.open_repository()._format,
                                   RepositoryFormatKnit1))

    def test_upgrade_repo(self):
        self.run_bzr('init-repository --format=metaweave repo')
        self.run_bzr('upgrade --format=knit repo')

    def assertLegalOption(self, option_str):
        # Confirm that an option is legal. (Lower level tests are
        # expected to validate the actual functionality.)
        self.run_bzr('init --format=pack-0.92 branch-foo')
        self.run_bzr('upgrade --format=2a branch-foo %s' % (option_str,))

    def assertBranchFormat(self, dir, format):
        branch = bzrdir.BzrDir.open_tree_or_branch(self.get_url(dir))[1]
        branch_format = branch._format
        meta_format = bzrdir.format_registry.make_bzrdir(format)
        expected_format = meta_format.get_branch_format()
        self.assertEqual(expected_format, branch_format)

    def test_upgrade_clean_supported(self):
        self.assertLegalOption('--clean')
        self.assertBranchFormat('branch-foo', '2a')
        backup_bzr_dir = os.path.join("branch-foo", "backup.bzr.~1~")
        self.assertFalse(os.path.exists(backup_bzr_dir))

    def test_upgrade_dry_run_supported(self):
        self.assertLegalOption('--dry-run')
        self.assertBranchFormat('branch-foo', 'pack-0.92')

    def test_upgrade_permission_check(self):
        """'backup.bzr' should retain permissions of .bzr. Bug #262450"""
        self.requireFeature(features.posix_permissions_feature)
        old_perms = stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR
        backup_dir = 'backup.bzr.~1~'
        self.run_bzr('init --format=1.6')
        os.chmod('.bzr', old_perms)
        self.run_bzr('upgrade')
        new_perms = os.stat(backup_dir).st_mode & 0777
        self.assertTrue(new_perms == old_perms)

    def test_upgrade_with_existing_backup_dir(self):
        path = self.make_format_5_branch()
        t = self.get_transport(path)
        url = t.base
        controldir.ControlDirFormat._set_default_format(bzrdir.BzrDirFormat5())
        backup_dir1 = 'backup.bzr.~1~'
        backup_dir2 = 'backup.bzr.~2~'
        # explicitly create backup_dir1. bzr should create the .~2~ directory
        # as backup
        t.mkdir(backup_dir1)
        (out, err) = self.run_bzr(
            ['upgrade', '--format=metaweave', url])
        self.assertEqualDiff("""Upgrading branch %s ...
starting upgrade of %s
making backup of %s.bzr
  to %s%s
starting upgrade from format 5 to 6
adding prefixes to weaves
adding prefixes to revision-store
starting upgrade from format 6 to metadir
finished
""" % (url, url, url, url, backup_dir2), out)
        self.assertEqualDiff("", err)
        self.assertTrue(isinstance(
            bzrdir.BzrDir.open(self.get_url(path))._format,
            bzrdir.BzrDirMetaFormat1))
        self.assertTrue(t.has(backup_dir2))


class SFTPTests(TestCaseWithSFTPServer):
    """Tests for upgrade over sftp."""

    def test_upgrade_url(self):
        self.run_bzr('init --format=weave')
        t = self.get_transport()
        url = t.base
        out, err = self.run_bzr(['upgrade', '--format=knit', url])
        backup_dir = 'backup.bzr.~1~'
        self.assertEqualDiff("""Upgrading branch %s ...
starting upgrade of %s
making backup of %s.bzr
  to %s%s
starting upgrade from format 6 to metadir
starting repository conversion
repository converted
finished
""" % (url, url, url, url,backup_dir), out)
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
