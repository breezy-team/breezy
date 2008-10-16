# Copyright (C) 2007 Canonical Ltd
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

"""Test that all Tree's implement path_content_summary."""

import os

from bzrlib.osutils import supports_executable
from bzrlib.tests import SymlinkFeature, TestSkipped, TestNotApplicable
from bzrlib.tests.tree_implementations import TestCaseWithTree


class TestPathContentSummary(TestCaseWithTree):

    def _convert_tree(self, tree):
        result = TestCaseWithTree._convert_tree(self, tree)
        result.lock_read()
        self.addCleanup(result.unlock)
        return result

    def test_symlink_content_summary(self):
        self.requireFeature(SymlinkFeature)
        tree = self.make_branch_and_tree('tree')
        os.symlink('target', 'tree/path')
        tree.add(['path'])
        summary = self._convert_tree(tree).path_content_summary('path')
        self.assertEqual(('symlink', None, None, 'target'), summary)

    def test_missing_content_summary(self):
        tree = self.make_branch_and_tree('tree')
        summary = self._convert_tree(tree).path_content_summary('path')
        self.assertEqual(('missing', None, None, None), summary)

    def test_file_content_summary_executable(self):
        if not supports_executable():
            raise TestNotApplicable()
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/path'])
        tree.add(['path'])
        current_mode = os.stat('tree/path').st_mode
        os.chmod('tree/path', current_mode | 0100)
        summary = self._convert_tree(tree).path_content_summary('path')
        self.assertEqual(4, len(summary))
        self.assertEqual('file', summary[0])
        # size must be known
        self.assertEqual(22, summary[1])
        # executable
        self.assertEqual(True, summary[2])
        # may have hash,
        self.assertSubset((summary[3],),
            (None, '0c352290ae1c26ca7f97d5b2906c4624784abd60'))

    def test_file_content_summary_non_exec(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/path'])
        tree.add(['path'])
        summary = self._convert_tree(tree).path_content_summary('path')
        self.assertEqual(4, len(summary))
        self.assertEqual('file', summary[0])
        # size must be known
        self.assertEqual(22, summary[1])
        # not executable
        if supports_executable:
            self.assertEqual(False, summary[2])
        else:
            self.assertEqual(None, summary[2])
        # may have hash,
        self.assertSubset((summary[3],),
            (None, '0c352290ae1c26ca7f97d5b2906c4624784abd60'))

    def test_dir_content_summary(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/path/'])
        tree.add(['path'])
        summary = self._convert_tree(tree).path_content_summary('path')
        self.assertEqual(('directory', None, None, None), summary)

    def test_tree_content_summary(self):
        tree = self.make_branch_and_tree('tree')
        subtree = self.make_branch_and_tree('tree/path')
        tree.add(['path'])
        if not tree.branch.repository._format.supports_tree_reference:
            raise TestSkipped("Tree references not supported.")
        summary = self._convert_tree(tree).path_content_summary('path')
        self.assertEqual(4, len(summary))
        self.assertEqual('tree-reference', summary[0])
