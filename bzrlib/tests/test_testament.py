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

from bzrlib.tests import TestCaseWithTransport
from bzrlib.testament import Testament, StrictTestament, StrictTestament2
from bzrlib.transform import TreeTransform
from bzrlib.osutils import has_symlinks


class TestamentSetup(TestCaseWithTransport):

    def setUp(self):
        super(TestamentSetup, self).setUp()
        self.wt = self.make_branch_and_tree('.')
        b = self.b = self.wt.branch
        b.nick = "test branch"
        self.wt.commit(message='initial null commit',
                 committer='test@user',
                 timestamp=1129025423, # 'Tue Oct 11 20:10:23 2005'
                 timezone=0,
                 rev_id='test@user-1')
        self.build_tree_contents([('hello', 'contents of hello file'),
                             ('src/', ),
                             ('src/foo.c', 'int main()\n{\n}\n')])
        self.wt.add(['hello', 'src', 'src/foo.c'],
                             ['hello-id', 'src-id', 'foo.c-id'])
        tt = TreeTransform(self.wt)
        trans_id = tt.trans_id_tree_path('hello')
        tt.set_executability(True, trans_id)
        tt.apply()
        self.wt.commit(message='add files and directories',
                 timestamp=1129025483,
                 timezone=36000,
                 rev_id='test@user-2',
                 committer='test@user')


class TestamentTests(TestamentSetup):

    def testament_class(self):
        return Testament

    def expected(self, key):
        return texts[self.testament_class()][key]

    def from_revision(self, repository, revision_id):
        return self.testament_class().from_revision(repository, revision_id)

    def test_null_testament(self):
        """Testament for a revision with no contents."""
        t = self.from_revision(self.b.repository, 'test@user-1')
        ass = self.assertTrue
        eq = self.assertEqual
        ass(isinstance(t, Testament))
        eq(t.revision_id, 'test@user-1')
        eq(t.committer, 'test@user')
        eq(t.timestamp, 1129025423)
        eq(t.timezone, 0)

    def test_testment_text_form(self):
        """Conversion of testament to canonical text form."""
        t = self.from_revision(self.b.repository, 'test@user-1')
        text_form = t.as_text()
        self.log('testament text form:\n' + text_form)
        self.assertEqualDiff(text_form, self.expected('rev_1'))
        short_text_form = t.as_short_text()
        self.assertEqualDiff(short_text_form, self.expected('rev_1_short'))

    def test_testament_with_contents(self):
        """Testament containing a file and a directory."""
        t = self.from_revision(self.b.repository, 'test@user-2')
        text_form = t.as_text()
        self.log('testament text form:\n' + text_form)
        self.assertEqualDiff(text_form, self.expected('rev_2'))
        actual_short = t.as_short_text()
        self.assertEqualDiff(actual_short, self.expected('rev_2_short'))

    def test_testament_symlinks(self):
        """Testament containing symlink (where possible)"""
        if not has_symlinks():
            return
        os.symlink('wibble/linktarget', 'link')
        self.wt.add(['link'], ['link-id'])
        self.wt.commit(message='add symlink',
                 timestamp=1129025493,
                 timezone=36000,
                 rev_id='test@user-3',
                 committer='test@user')
        t = self.from_revision(self.b.repository, 'test@user-3')
        self.assertEqualDiff(t.as_text(), self.expected('rev_3'))

    def test_testament_revprops(self):
        """Testament to revision with extra properties"""
        props = dict(flavor='sour cherry\ncream cheese',
                     size='medium',
                     empty='',
                    )
        self.wt.commit(message='revision with properties',
                      timestamp=1129025493,
                      timezone=36000,
                      rev_id='test@user-3',
                      committer='test@user',
                      revprops=props)
        t = self.from_revision(self.b.repository, 'test@user-3')
        self.assertEqualDiff(t.as_text(), self.expected('rev_props'))

    def test_testament_unicode_commit_message(self):
        self.wt.commit(
            message=u'non-ascii commit \N{COPYRIGHT SIGN} me',
            timestamp=1129025493,
            timezone=36000,
            rev_id='test@user-3',
            committer='Erik B\xe5gfors <test@user>',
            revprops={'uni':u'\xb5'}
            )
        t = self.from_revision(self.b.repository, 'test@user-3')
        self.assertEqualDiff(
            self.expected('sample_unicode').encode('utf-8'), t.as_text())

    def test___init__(self):
        revision = self.b.repository.get_revision('test@user-2')
        inventory = self.b.repository.get_inventory('test@user-2')
        testament_1 = self.testament_class()(revision, inventory).as_short_text()
        testament_2 = self.from_revision(self.b.repository, 
                                              'test@user-2').as_short_text()
        self.assertEqual(testament_1, testament_2)
                    

class TestamentTestsStrict(TestamentTests):
    
    def testament_class(self):
        return StrictTestament


class TestamentTestsStrict2(TestamentTests):
    
    def testament_class(self):
        return StrictTestament2


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

REV_1_STRICT_TESTAMENT = """\
bazaar-ng testament version 2.1
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

REV_1_STRICT_TESTAMENT2 = """\
bazaar-ng testament version 3 strict
revision-id: test@user-1
committer: test@user
timestamp: 1129025423
timezone: 0
parents:
message:
  initial null commit
inventory:
  directory . TREE_ROOT test@user-1 no
properties:
  branch-nick:
    test branch
"""

REV_1_SHORT = """\
bazaar-ng testament short form 1
revision-id: test@user-1
sha1: %s
""" % sha(REV_1_TESTAMENT).hexdigest()


REV_1_SHORT_STRICT = """\
bazaar-ng testament short form 2.1
revision-id: test@user-1
sha1: %s
""" % sha(REV_1_STRICT_TESTAMENT).hexdigest()


REV_1_SHORT_STRICT2 = """\
bazaar-ng testament short form 3 strict
revision-id: test@user-1
sha1: %s
""" % sha(REV_1_STRICT_TESTAMENT2).hexdigest()


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


REV_2_STRICT_TESTAMENT = """\
bazaar-ng testament version 2.1
revision-id: test@user-2
committer: test@user
timestamp: 1129025483
timezone: 36000
parents:
  test@user-1
message:
  add files and directories
inventory:
  file hello hello-id 34dd0ac19a24bf80c4d33b5c8960196e8d8d1f73 test@user-2 yes
  directory src src-id test@user-2 no
  file src/foo.c foo.c-id a2a049c20f908ae31b231d98779eb63c66448f24 test@user-2 no
properties:
  branch-nick:
    test branch
"""


REV_2_STRICT_TESTAMENT2 = """\
bazaar-ng testament version 3 strict
revision-id: test@user-2
committer: test@user
timestamp: 1129025483
timezone: 36000
parents:
  test@user-1
message:
  add files and directories
inventory:
  directory . TREE_ROOT test@user-2 no
  file hello hello-id 34dd0ac19a24bf80c4d33b5c8960196e8d8d1f73 test@user-2 yes
  directory src src-id test@user-2 no
  file src/foo.c foo.c-id a2a049c20f908ae31b231d98779eb63c66448f24 test@user-2 no
properties:
  branch-nick:
    test branch
"""

REV_2_SHORT = """\
bazaar-ng testament short form 1
revision-id: test@user-2
sha1: %s
""" % sha(REV_2_TESTAMENT).hexdigest()


REV_2_SHORT_STRICT = """\
bazaar-ng testament short form 2.1
revision-id: test@user-2
sha1: %s
""" % sha(REV_2_STRICT_TESTAMENT).hexdigest()


REV_2_SHORT_STRICT2 = """\
bazaar-ng testament short form 3 strict
revision-id: test@user-2
sha1: %s
""" % sha(REV_2_STRICT_TESTAMENT2).hexdigest()


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
  empty:
  flavor:
    sour cherry
    cream cheese
  size:
    medium
"""


REV_PROPS_TESTAMENT_STRICT = """\
bazaar-ng testament version 2.1
revision-id: test@user-3
committer: test@user
timestamp: 1129025493
timezone: 36000
parents:
  test@user-2
message:
  revision with properties
inventory:
  file hello hello-id 34dd0ac19a24bf80c4d33b5c8960196e8d8d1f73 test@user-2 yes
  directory src src-id test@user-2 no
  file src/foo.c foo.c-id a2a049c20f908ae31b231d98779eb63c66448f24 test@user-2 no
properties:
  branch-nick:
    test branch
  empty:
  flavor:
    sour cherry
    cream cheese
  size:
    medium
"""


REV_PROPS_TESTAMENT_STRICT2 = """\
bazaar-ng testament version 3 strict
revision-id: test@user-3
committer: test@user
timestamp: 1129025493
timezone: 36000
parents:
  test@user-2
message:
  revision with properties
inventory:
  directory . TREE_ROOT test@user-3 no
  file hello hello-id 34dd0ac19a24bf80c4d33b5c8960196e8d8d1f73 test@user-2 yes
  directory src src-id test@user-2 no
  file src/foo.c foo.c-id a2a049c20f908ae31b231d98779eb63c66448f24 test@user-2 no
properties:
  branch-nick:
    test branch
  empty:
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


REV_3_TESTAMENT_STRICT = """\
bazaar-ng testament version 2.1
revision-id: test@user-3
committer: test@user
timestamp: 1129025493
timezone: 36000
parents:
  test@user-2
message:
  add symlink
inventory:
  file hello hello-id 34dd0ac19a24bf80c4d33b5c8960196e8d8d1f73 test@user-2 yes
  symlink link link-id wibble/linktarget test@user-3 no
  directory src src-id test@user-2 no
  file src/foo.c foo.c-id a2a049c20f908ae31b231d98779eb63c66448f24 test@user-2 no
properties:
  branch-nick:
    test branch
"""


REV_3_TESTAMENT_STRICT2 = """\
bazaar-ng testament version 3 strict
revision-id: test@user-3
committer: test@user
timestamp: 1129025493
timezone: 36000
parents:
  test@user-2
message:
  add symlink
inventory:
  directory . TREE_ROOT test@user-3 no
  file hello hello-id 34dd0ac19a24bf80c4d33b5c8960196e8d8d1f73 test@user-2 yes
  symlink link link-id wibble/linktarget test@user-3 no
  directory src src-id test@user-2 no
  file src/foo.c foo.c-id a2a049c20f908ae31b231d98779eb63c66448f24 test@user-2 no
properties:
  branch-nick:
    test branch
"""

SAMPLE_UNICODE_TESTAMENT = u"""\
bazaar-ng testament version 1
revision-id: test@user-3
committer: Erik B\xe5gfors <test@user>
timestamp: 1129025493
timezone: 36000
parents:
  test@user-2
message:
  non-ascii commit \N{COPYRIGHT SIGN} me
inventory:
  file hello hello-id 34dd0ac19a24bf80c4d33b5c8960196e8d8d1f73
  directory src src-id
  file src/foo.c foo.c-id a2a049c20f908ae31b231d98779eb63c66448f24
properties:
  branch-nick:
    test branch
  uni:
    \xb5
"""


SAMPLE_UNICODE_TESTAMENT_STRICT = u"""\
bazaar-ng testament version 2.1
revision-id: test@user-3
committer: Erik B\xe5gfors <test@user>
timestamp: 1129025493
timezone: 36000
parents:
  test@user-2
message:
  non-ascii commit \N{COPYRIGHT SIGN} me
inventory:
  file hello hello-id 34dd0ac19a24bf80c4d33b5c8960196e8d8d1f73 test@user-2 yes
  directory src src-id test@user-2 no
  file src/foo.c foo.c-id a2a049c20f908ae31b231d98779eb63c66448f24 test@user-2 no
properties:
  branch-nick:
    test branch
  uni:
    \xb5
"""


SAMPLE_UNICODE_TESTAMENT_STRICT2 = u"""\
bazaar-ng testament version 3 strict
revision-id: test@user-3
committer: Erik B\xe5gfors <test@user>
timestamp: 1129025493
timezone: 36000
parents:
  test@user-2
message:
  non-ascii commit \N{COPYRIGHT SIGN} me
inventory:
  directory . TREE_ROOT test@user-3 no
  file hello hello-id 34dd0ac19a24bf80c4d33b5c8960196e8d8d1f73 test@user-2 yes
  directory src src-id test@user-2 no
  file src/foo.c foo.c-id a2a049c20f908ae31b231d98779eb63c66448f24 test@user-2 no
properties:
  branch-nick:
    test branch
  uni:
    \xb5
"""


texts = {
    Testament: { 'rev_1': REV_1_TESTAMENT,
                 'rev_1_short': REV_1_SHORT,
                 'rev_2': REV_2_TESTAMENT,
                 'rev_2_short': REV_2_SHORT,
                 'rev_3': REV_3_TESTAMENT,
                 'rev_props': REV_PROPS_TESTAMENT,
                 'sample_unicode': SAMPLE_UNICODE_TESTAMENT,
    },
    StrictTestament: {'rev_1': REV_1_STRICT_TESTAMENT,
                      'rev_1_short': REV_1_SHORT_STRICT,
                      'rev_2': REV_2_STRICT_TESTAMENT,
                      'rev_2_short': REV_2_SHORT_STRICT,
                      'rev_3': REV_3_TESTAMENT_STRICT,
                      'rev_props': REV_PROPS_TESTAMENT_STRICT,
                      'sample_unicode': SAMPLE_UNICODE_TESTAMENT_STRICT,
    },
    StrictTestament2: {'rev_1': REV_1_STRICT_TESTAMENT2,
                      'rev_1_short': REV_1_SHORT_STRICT2,
                      'rev_2': REV_2_STRICT_TESTAMENT2,
                      'rev_2_short': REV_2_SHORT_STRICT2,
                      'rev_3': REV_3_TESTAMENT_STRICT2,
                      'rev_props': REV_PROPS_TESTAMENT_STRICT2,
                      'sample_unicode': SAMPLE_UNICODE_TESTAMENT_STRICT2,
    },
}
