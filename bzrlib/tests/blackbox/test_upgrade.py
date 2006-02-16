# Copyright (C) 2006 by Canonical Ltd
# Authors: Robert Collins <robert.collins@canonical.com>
# -*- coding: utf-8 -*-

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Black box tests for the upgrade ui."""

import os

import bzrlib.bzrdir as bzrdir
from bzrlib.tests import TestCaseWithTransport
from bzrlib.transport import get_transport
import bzrlib.ui as ui


class TestUIFactory(ui.UIFactory):
    """A UI Factory which never captures its output.
    """

    def note(self, fmt_string, *args, **kwargs):
        """See progress.ProgressBae.note()."""
        print fmt_string % args

    def progress_bar(self):
        return self


class TestWithUpgradableBranches(TestCaseWithTransport):

    def setUp(self):
        super(TestWithUpgradableBranches, self).setUp()
        self.old_format = bzrdir.BzrDirFormat.get_default_format()
        self.old_ui_factory = ui.ui_factory
        self.addCleanup(self.restoreDefaults)

        ui.ui_factory = TestUIFactory()
        bzrdir.BzrDirFormat.set_default_format(bzrdir.BzrDirMetaFormat1())
        # FIXME RBC 20060120 we should be able to do this via ui calls only.
        # setup a format 5 branch we can upgrade from.
        t = get_transport(self.get_url())
        t.mkdir('format_5_branch')
        bzrdir.BzrDirFormat5().initialize(self.get_url('format_5_branch'))
        bzrdir.BzrDir.create_standalone_workingtree('current_format_branch')
        self.run_bzr('checkout',
                     self.get_url('current_format_branch'),
                     'current_format_checkout')

    def restoreDefaults(self):
        bzrdir.BzrDirFormat.set_default_format(self.old_format)
        ui.ui_factory = self.old_ui_factory

    def test_readonly_url_error(self):
        (out, err) = self.run_bzr_captured(
            ['upgrade', self.get_readonly_url('format_5_branch')], 3)
        self.assertEqual(out, "")
        self.assertEqual(err, "bzr: ERROR: Upgrade URL cannot work with readonly URL's.\n")

    def test_upgrade_up_to_date(self):
        # when up to date we should get a message to that effect
        (out, err) = self.run_bzr_captured(
            ['upgrade', 'current_format_branch'], 3)
        self.assertEqual("", out)
        self.assertEqualDiff("bzr: ERROR: The branch format Bazaar-NG meta "
                             "directory, format 1 is already at the most "
                             "recent format.\n", err)

    def test_upgrade_up_to_date_checkout_warns_branch_left_alone(self):
        # when upgrading a checkout, the branch location and a suggestion
        # to upgrade it should be emitted even if the checkout is up to 
        # date
        (out, err) = self.run_bzr_captured(
            ['upgrade', 'current_format_checkout'], 3)
        self.assertEqual("This is a checkout. The branch (%s) needs to be "
                         "upgraded separately.\n" 
                         % get_transport(self.get_url('current_format_branch')).base,
                         out)
        self.assertEqualDiff("bzr: ERROR: The branch format Bazaar-NG meta "
                             "directory, format 1 is already at the most "
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
