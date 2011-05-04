# Copyright (C) 2007-2010 Canonical Ltd
# -*- coding: utf-8 -*-
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

"""Tests related to setting the parent location when branching."""

import os

from bzrlib import (
        osutils,
        branch,
        tests
        )
from bzrlib.tests import script

class TestParentLocation(tests.TestCaseWithTransport):
    def setUp(self):
        """Set up a repository and branch ready for testing."""
        super(TestParentLocation, self).setUp()
        self.script_runner = script.ScriptRunner()
        self.script_runner.run_script(self, '''
                $ bzr init-repo --no-trees repo
                Shared repository...
                Location:
                  shared repository: repo
                $ bzr init repo/trunk
                Created a repository branch...
                Using shared repository: ...
                ''')

    def assertParentCorrect(self, branch, expected_parent):
        """Verify that the parent is not None and is set correctly.
        
        @param branch: Branch for which to check parent.
        @param expected_parent: Expected parent as a list of strings for each component:
            each element in the list is compared.
        """
        parent = branch.get_parent()
        self.assertIsNot(parent, None, "Parent not set")
        # Get the last 'n' path elements from the parent where 'n' is the length of
        # the expected_parent, so if ['repo', 'branch'] is passed, get the last two
        # components for comparison.
        actual_parent = osutils.splitpath(parent.rstrip(r'\/'))[-len(expected_parent):]
        self.assertEquals(expected_parent, actual_parent, "Parent set incorrectly")

    def test_switch_parent_lightweight(self):
        """Verify parent directory for lightweight checkout."""
        self.script_runner.run_script(self, '''
                $ bzr checkout --lightweight repo/trunk work_lw
                $ cd work_lw
                $ bzr switch --create-branch switched_lw
                2>Tree is up to date at revision 0.
                2>Switched to branch:...switched_lw...
                ''')
        b = branch.Branch.open_containing('work_lw')[0]
        self.assertParentCorrect(b, ['repo','trunk'])

    def test_switch_parent_heavyweight(self):
        """Verify parent directory for heavyweight checkout."""
        self.script_runner.run_script(self, '''
                $ bzr checkout repo/trunk work_hw
                $ cd work_hw
                $ bzr switch --create-branch switched_hw
                2>Tree is up to date at revision 0.
                2>Switched to branch:...switched_hw...
                ''')
        b = branch.Branch.open_containing('work_hw')[0]
        self.assertParentCorrect(b, ['repo','trunk'])
