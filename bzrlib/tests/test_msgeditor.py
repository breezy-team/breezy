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
from bzrlib.config import ensure_config_dir_exists, config_filename
from bzrlib.msgeditor import make_commit_message_template, _get_editor
from bzrlib.tests import TestCaseWithTransport, TestSkipped


class MsgEditorTest(TestCaseWithTransport):

    def make_uncommitted_tree(self):
        """Build a branch with uncommitted unicode named changes in the cwd."""
        working_tree = self.make_branch_and_tree('.')
        b = working_tree.branch
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

    def test__get_editor(self):
        # Test that _get_editor can return a decent list of items
        bzr_editor = os.environ.get('BZR_EDITOR')
        editor = os.environ.get('EDITOR')
        try:
            os.environ['BZR_EDITOR'] = 'bzr_editor'
            os.environ['EDITOR'] = 'editor'

            ensure_config_dir_exists()
            f = open(config_filename(), 'wb')
            f.write('editor = config_editor\n')
            f.close()

            editors = list(_get_editor())

            self.assertEqual(['bzr_editor', 'config_editor', 'editor'],
                editors[:3])

            if sys.platform == 'win32':
                self.assertEqual(['wordpad.exe', 'notepad.exe'], editors[3:])
            else:
                self.assertEqual(['vi', 'pico', 'nano', 'joe'], editors[3:])

        finally:
            # Restore the environment
            if bzr_editor is None:
                del os.environ['BZR_EDITOR']
            else:
                os.environ['BZR_EDITOR'] = bzr_editor
            if editor is None:
                del os.environ['EDITOR']
            else:
                os.environ['EDITOR'] = editor

