# Copyright (C) 2006 Canonical Ltd

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

"""Tests for lock-breaking user interface"""

import os

from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir
from bzrlib.tests import TestCaseInTempDir

class TestBreakLock(TestCaseInTempDir):
    def test_break_lock_help(self):
        self.run_bzr('break-lock', '--help')
        # shouldn't fail

    def test_show_no_lock(self):
        wt = BzrDir.create_standalone_workingtree('.')
        out, err = self.run_bzr('break-lock', '--show', '.', retcode=3)
        # shouldn't see any information
        self.assertContainsRe(err, 'not locked')
