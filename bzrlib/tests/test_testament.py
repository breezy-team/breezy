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

# TODO: Testaments with x-bits

import os
from sha import sha
import sys

from bzrlib.tests import TestCaseWithTransport
from bzrlib.branch import Branch
from bzrlib.testament import Testament
from bzrlib.trace import mutter
from bzrlib.osutils import has_symlinks


class TestamentTests(TestCaseWithTransport):

    def setUp(self):
        super(TestamentTests, self).setUp()
        wt = self.make_branch_and_tree('.')
        b = self.b = wt.branch
        b.nick = "test branch"
        wt.commit(message='initial null commit',
                 committer='test@user',
                 timestamp=1129025423, # 'Tue Oct 11 20:10:23 2005'
                 timezone=0,
                 rev_id='test@user-1')
        self.build_tree_contents([('hello', 'contents of hello file'),
                             ('src/', ),
                             ('src/foo.c', 'int main()\n{\n}\n')])
        wt.add(['hello', 'src', 'src/foo.c'],
                             ['hello-id', 'src-id', 'foo.c-id'])
        wt.commit(message='add files and directories',
                 timestamp=1129025483,
                 timezone=36000,
                 rev_id='test@user-2',
                 committer='test@user')

    def test_null_testament(self):
        """Testament for a revision with no contents."""
        t = Testament.from_revision(self.b.repository, 'test@user-1')
        ass = self.assertTrue
        eq = self.assertEqual
        ass(isinstance(t, Testament))
        eq(t.revision_id, 'test@user-1')
        eq(t.committer, 'test@user')
        eq(t.timestamp, 1129025423)
        eq(t.timezone, 0)

    def test_testment_text_form(self):
        """Conversion of testament to canonical text form."""
        t = Testament.from_revision(self.b.repository, 'test@user-1')
        text_form = t.as_text()
        self.log('testament text form:\n' + text_form)
        self.assertEqual(text_form, REV_1_TESTAMENT)

    def test_testament_with_contents(self):
        """Testament containing a file and a directory."""
        t = Testament.from_revision(self.b.repository, 'test@user-2')
        text_form = t.as_text()
        self.log('testament text form:\n' + text_form)
        self.assertEqualDiff(text_form, REV_2_TESTAMENT)
        actual_short = t.as_short_text()
        self.assertEqualDiff(actual_short, REV_2_SHORT)

    def test_testament_command(self):
        """Testament containing a file and a directory."""
        out, err = self.run_bzr_captured(['testament', '--long'])
        self.assertEqualDiff(err, '')
        self.assertEqualDiff(out, REV_2_TESTAMENT)

    def test_testament_command_2(self):
        """Command getting short testament of previous version."""
        out, err = self.run_bzr_captured(['testament', '-r1'])
        self.assertEqualDiff(err, '')
        self.assertEqualDiff(out, REV_1_SHORT)

    def test_testament_symlinks(self):
        """Testament containing symlink (where possible)"""
        if not has_symlinks():
            return
        os.symlink('wibble/linktarget', 'link')
        self.b.working_tree().add(['link'], ['link-id'])
        self.b.working_tree().commit(message='add symlink',
                 timestamp=1129025493,
                 timezone=36000,
                 rev_id='test@user-3',
                 committer='test@user')
        t = Testament.from_revision(self.b.repository, 'test@user-3')
        self.assertEqualDiff(t.as_text(), REV_3_TESTAMENT)

    def test_testament_revprops(self):
        """Testament to revision with extra properties"""
        props = dict(flavor='sour cherry\ncream cheese',
                     size='medium')
        self.b.working_tree().commit(message='revision with properties',
                      timestamp=1129025493,
                      timezone=36000,
                      rev_id='test@user-3',
                      committer='test@user',
                      revprops=props)
        t = Testament.from_revision(self.b.repository, 'test@user-3')
        self.assertEqualDiff(t.as_text(), REV_PROPS_TESTAMENT)

    def test___init__(self):
        revision = self.b.repository.get_revision('test@user-2')
        inventory = self.b.repository.get_inventory('test@user-2')
        testament_1 = Testament(revision, inventory).as_short_text()
        testament_2 = Testament.from_revision(self.b.repository, 
                                              'test@user-2').as_short_text()
        self.assertEqual(testament_1, testament_2)
                    

REV_1_TESTAMENT = """\
bazaar-ng testament version 1
revision-id: test@user-1
committer: test@user
timestamp: 1129025423
timezone: 0
parents:
message:
  initial null commit
inventory:
properties:
  branch-nick:
    test branch
"""

REV_1_SHORT = """\
bazaar-ng testament short form 1
revision-id: test@user-1
sha1: %s
""" % sha(REV_1_TESTAMENT).hexdigest()


REV_2_TESTAMENT = """\
bazaar-ng testament version 1
revision-id: test@user-2
committer: test@user
timestamp: 1129025483
timezone: 36000
parents:
  test@user-1
message:
  add files and directories
inventory:
  file hello hello-id 34dd0ac19a24bf80c4d33b5c8960196e8d8d1f73
  directory src src-id
  file src/foo.c foo.c-id a2a049c20f908ae31b231d98779eb63c66448f24
properties:
  branch-nick:
    test branch
"""


REV_2_SHORT = """\
bazaar-ng testament short form 1
revision-id: test@user-2
sha1: %s
""" % sha(REV_2_TESTAMENT).hexdigest()


REV_PROPS_TESTAMENT = """\
bazaar-ng testament version 1
revision-id: test@user-3
committer: test@user
timestamp: 1129025493
timezone: 36000
parents:
  test@user-2
message:
  revision with properties
inventory:
  file hello hello-id 34dd0ac19a24bf80c4d33b5c8960196e8d8d1f73
  directory src src-id
  file src/foo.c foo.c-id a2a049c20f908ae31b231d98779eb63c66448f24
properties:
  branch-nick:
    test branch
  flavor:
    sour cherry
    cream cheese
  size:
    medium
"""


REV_3_TESTAMENT = """\
bazaar-ng testament version 1
revision-id: test@user-3
committer: test@user
timestamp: 1129025493
timezone: 36000
parents:
  test@user-2
message:
  add symlink
inventory:
  file hello hello-id 34dd0ac19a24bf80c4d33b5c8960196e8d8d1f73
  symlink link link-id wibble/linktarget
  directory src src-id
  file src/foo.c foo.c-id a2a049c20f908ae31b231d98779eb63c66448f24
properties:
  branch-nick:
    test branch
"""
