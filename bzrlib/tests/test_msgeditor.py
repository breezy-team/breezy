# Copyright (C) 2005 by Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as published by
# the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Test commit message editor.
"""

import os
import sys

from bzrlib.branch import Branch
from bzrlib.msgeditor import make_commit_message_template
from bzrlib.tests import TestCaseInTempDir, TestSkipped


class MsgEditorTest(TestCaseInTempDir):

    def make_uncommitted_tree(self):
        """Build a branch with uncommitted unicode named changes in the cwd."""
        b = Branch.initialize('.')
        working_tree = b.working_tree()
        filename = u'hell\u00d8'
        try:
            self.build_tree_contents([(filename, 'contents of hello')])
        except UnicodeEncodeError:
            raise TestSkipped("can't build unicode working tree in "
                "filesystem encoding %s" % sys.getfilesystemencoding())
        working_tree.add(filename)
        return working_tree
    
    def test_commit_template(self):
        """Test building a commit message template"""
        working_tree = self.make_uncommitted_tree()
        template = make_commit_message_template(working_tree, None)
        self.assertEqualDiff(template,
u"""\
added:
  hell\u00d8
""")
