# Copyright (C) 2006 Jelmer Vernooij <jelmer@samba.org>

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

import svn
import os
import format
from tests import TestCaseWithSubversionRepository
from bzrlib.bzrdir import BzrDir
from bzrlib.bzrdir import BzrDirTestProviderAdapter, BzrDirFormat

class WorkingBoundSubversionBranch(TestCaseWithSubversionRepository):
    def setUp(self):
        TestCaseWithSubversionRepository(self)

    def test_light_checkout(self):
        source = self.open_branch()

        to_location = os.path.join(self.test_dir, "checkout")

        checkout = bzrdir.BzrDirMetaFormat1().initialize(to_location)
        bzrlib.branch.BranchReferenceFormat().initialize(checkout, source)

        checkout.create_workingtree(source.last_revision())
