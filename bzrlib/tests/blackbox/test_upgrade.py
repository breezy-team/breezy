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

from bzrlib.branch import Branch, BzrBranchFormat5
from bzrlib.tests import TestCaseWithTransport
from bzrlib.transport import get_transport


class TestUpgrade(TestCaseWithTransport):

    def setUp(self):
        super(TestUpgrade, self).setUp()
        # FIXME RBC 20060120 we should be able to do this via ui calls only.
        # setup a format 5 branch we can upgrade from.
        t = get_transport(self.get_url())
        t.mkdir('old_branch')
        BzrBranchFormat5().initialize(self.get_url('old_branch'))

    def test_readonly_url_error(self):
        (out, err) = self.run_bzr_captured(
            ['upgrade', self.get_readonly_url('old_branch')], 3)
        self.assertEqual(out, "")
        self.assertEqual(err, "bzr: ERROR: Upgrade URL cannot work with readonly URL's.\n")
