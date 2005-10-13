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

"""Test testaments for gpg signing."""

import difflib
import os
import sys

from bzrlib.selftest import TestCaseInTempDir
from bzrlib.selftest.treeshape import build_tree_contents
from bzrlib.branch import Branch
from bzrlib.testament import Testament
from bzrlib.trace import mutter

class TestamentTests(TestCaseInTempDir):
    def setUp(self):
        super(TestamentTests, self).setUp()
        b = self.b = Branch.initialize('.')
        b.commit(message='initial null commit',
                 committer='test@user',
                 timestamp=1129025423, # 'Tue Oct 11 20:10:23 2005'
                 timezone=0,
                 rev_id='test@user-1')
        build_tree_contents([('hello', 'contents of hello file'),
                             ('src/', ),
                             ('src/foo.c', 'int main()\n{\n}')])
        b.add(['hello', 'src', 'src/foo.c'])
        b.commit(message='add files and directories',
                 timestamp=1129025483,
                 timezone=36000,
                 rev_id='test@user-2',
                 committer='test@user')

    def test_null_testament(self):
        """Testament for a revision with no contents."""
        t = Testament.from_revision(self.b, 'test@user-1')
        ass = self.assertTrue
        eq = self.assertEqual
        ass(isinstance(t, Testament))
        eq(t.revision_id, 'test@user-1')
        eq(t.committer, 'test@user')
        eq(t.timestamp, 1129025423)
        eq(t.timezone, 0)

    def test_testment_text_form(self):
        """Conversion of testament to canonical text form."""
        t = Testament.from_revision(self.b, 'test@user-1')
        text_form = t.to_text_form_1()
        self.log('testament text form:\n' + text_form)
        expect = """\
bazaar-ng testament version 1
revision-id: test@user-1
committer: test@user
timestamp: 1129025423.0
timezone: 0
entries: 0
parents:
message:
  initial null commit
inventory:
"""
        self.assertEqual(text_form, expect)

    def test_testament_with_contents(self):
        """Testament containing a file and a directory."""
        t = Testament.from_revision(self.b, 'test@user-2')
        text_form = t.to_text_form_1()
        self.log('testament text form:\n' + text_form)
        expect = """\
bazaar-ng testament version 1
revision-id: test@user-2
committer: test@user
timestamp: 1129025483.0
timezone: 36000
entries: 3
parents:
  test@user-1
message:
  add files and directories
inventory:
  file hello
  directory src
  file src/foo.c
"""
        self.assertEqualDiff(text_form, expect)
        actual_short = t.as_short_text()
        self.assertEqualDiff(actual_short, """\
bazaar-ng testament short form 1
revision test@user-2
sha1 e64f0a98937f8b0d2602ea5f521938752b90a430
""")
