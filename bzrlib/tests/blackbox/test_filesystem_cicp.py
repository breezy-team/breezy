# Copyright (C) 2008 Canonical Ltd
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
#

"""Tests variations of case-insensitive and case-preserving file-systems."""

import os

from bzrlib.tests.blackbox import ExternalBase
from bzrlib.tests import CaseInsCasePresFilenameFeature

class TestIncorrectUserCase(ExternalBase):
    """Tests for when the filename as the 'correct' case on disk, but the user
    has specified a version of the filename that differs in only by case.
    """

    _test_needs_features = [CaseInsCasePresFilenameFeature]

    def _make_mixed_case_tree(self):
        """Make a working tree with mixed-case filenames."""
        wt = self.make_branch_and_tree('.')
        # create a file on disk with the mixed-case parent and base name
        self.build_tree(['CamelCaseParent/', 'lowercaseparent/'])
        self.build_tree_contents([('CamelCaseParent/CamelCase', 'camel case'),
                                  ('lowercaseparent/lowercase', 'lower case'),
                                 ])
        return wt

    def test_add_simple(self):
        """Test add always uses the case of the filename reported by the os."""
        wt = self.make_branch_and_tree('.')
        # create a file on disk with the mixed-case name
        self.build_tree(['CamelCase'])

        self.check_output('added CamelCase\n', 'add camelcase')

    def test_add_subdir(self):
        """test_add_simple but with subdirectories tested too."""
        wt = self.make_branch_and_tree('.')
        # create a file on disk with the mixed-case parent and base name
        self.build_tree(['CamelCaseParent/', 'CamelCaseParent/CamelCase'])

        self.check_output('added CamelCaseParent\nadded CamelCaseParent/CamelCase\n',
                          'add camelcaseparent/camelcase')

    def test_add_implied(self):
        """test add with no args sees the correct names."""
        wt = self.make_branch_and_tree('.')
        # create a file on disk with the mixed-case parent and base name
        self.build_tree(['CamelCaseParent/', 'CamelCaseParent/CamelCase'])

        self.check_output('added CamelCaseParent\nadded CamelCaseParent/CamelCase\n',
                          'add')

    def test_status(self):
        wt = self._make_mixed_case_tree()
        self.run_bzr('add')

        self.check_output('added:\n  CamelCaseParent/CamelCase\n  lowercaseparent/lowercase\n',
                          'status camelcaseparent/camelcase LOWERCASEPARENT/LOWERCASE')

    def test_ci(self):
        wt = self._make_mixed_case_tree()
        self.run_bzr('add')

        got = self.run_bzr('ci -m message camelcaseparent LOWERCASEPARENT')[1]
        for expected in ['CamelCaseParent', 'lowercaseparent',
                         'CamelCaseParent/CamelCase', 'lowercaseparent/lowercase']:
            self.assertContainsRe(got, 'added ' + expected + '\n')

    def test_rm(self):
        wt = self._make_mixed_case_tree()
        self.run_bzr('add')
        self.run_bzr('ci -m message')

        got = self.run_bzr('rm camelcaseparent LOWERCASEPARENT')[1]
        for expected in ['lowercaseparent/lowercase', 'CamelCaseParent/CamelCase']:
            self.assertContainsRe(got, 'deleted ' + expected + '\n')
