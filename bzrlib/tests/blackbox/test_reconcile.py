# Copyright (C) 2006 by Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Black box tests for the reconcile command."""


import bzrlib.bzrdir as bzrdir
import bzrlib.repository as repository
from bzrlib.tests import TestCaseWithTransport
from bzrlib.tests.blackbox import TestUIFactory
from bzrlib.transport import get_transport
import bzrlib.ui as ui


class TrivialTest(TestCaseWithTransport):

    def setUp(self):
        super(TrivialTest, self).setUp()
        self.old_format = bzrdir.BzrDirFormat.get_default_format()
        self.old_ui_factory = ui.ui_factory
        self.addCleanup(self.restoreDefaults)
        ui.ui_factory = TestUIFactory()

    def restoreDefaults(self):
        ui.ui_factory = self.old_ui_factory

    def test_trivial_reconcile(self):
        t = bzrdir.BzrDir.create_standalone_workingtree('.')
        (out, err) = self.run_bzr_captured(['reconcile'])
        self.assertEqualDiff(out, "Reconciling repository %s\n"
                                  "Backup Inventory created.\n"
                                  "Inventory regenerated.\n"
                                  "Reconciliation complete.\n" %
                                  t.bzrdir.root_transport.base)
        self.assertEqualDiff(err, "")

