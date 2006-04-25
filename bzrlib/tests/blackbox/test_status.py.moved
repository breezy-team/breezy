# Copyright (C) 2005 by Canonical Ltd
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


"""\
Black-box tests for encoding of bzr status.

Status command usually prints output (possible unicode) to sys.stdout.
When status output is redirected to a file or pipe, or the encoding of sys.stdout
is not able to encode non-ascii filenames then status
used to fail because of UnicodeEncode error:
bzr: ERROR: exceptions.UnicodeEncodeError: 'ascii' codec can't encode characters: ordinal not in range(128)

In case when sys.stdout.encoding is None
bzr should use bzrlib.user_encoding for output.
bzr should also use `replace` error handling scheme, to allow
status to run even if the exact filenames cannot be displayed.
"""

from cStringIO import StringIO
import os
import sys

import bzrlib
from bzrlib.branch import Branch
from bzrlib.tests import TestCaseInTempDir, TestSkipped
from bzrlib.trace import mutter


class TestStatusEncodings(TestCaseInTempDir):
    
    def setUp(self):
        TestCaseInTempDir.setUp(self)
        self.user_encoding = bzrlib.user_encoding
        self.stdout = sys.stdout

    def tearDown(self):
        bzrlib.user_encoding = self.user_encoding
        sys.stdout = self.stdout
        TestCaseInTempDir.tearDown(self)

    def make_uncommitted_tree(self):
        """Build a branch with uncommitted unicode named changes in the cwd."""
        b = Branch.initialize(u'.')
        working_tree = b.working_tree()
        filename = u'hell\u00d8'
        try:
            self.build_tree_contents([(filename, 'contents of hello')])
        except UnicodeEncodeError:
            raise TestSkipped("can't build unicode working tree in "
                "filesystem encoding %s" % sys.getfilesystemencoding())
        working_tree.add(filename)
        return working_tree

    def test_stdout_ascii(self):
        sys.stdout = StringIO()
        bzrlib.user_encoding = 'ascii'
        working_tree = self.make_uncommitted_tree()
        stdout, stderr = self.run_bzr("status")

        self.assertEquals(stdout, """\
added:
  hell?
""")

    def test_stdout_latin1(self):
        sys.stdout = StringIO()
        bzrlib.user_encoding = 'latin-1'
        working_tree = self.make_uncommitted_tree()
        stdout, stderr = self.run_bzr('status')

        self.assertEquals(stdout, u"""\
added:
  hell\u00d8
""".encode('latin-1'))

