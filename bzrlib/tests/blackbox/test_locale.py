# Copyright (C) 2006 Canonical Ltd
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

"""Test that bzr handles locales in a reasonable way"""

import os
import sys

from bzrlib.tests import TestCaseWithTransport, TestSkipped


class TestLocale(TestCaseWithTransport):

    def setUp(self):
        super(TestLocale, self).setUp()

        if sys.platform in ('win32',):
            raise TestSkipped('Windows does not respond to the LANG'
                              ' env variable')

        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/a'])
        tree.add('a')
        tree.commit(u'Unicode \xb5 commit', rev_id='r1',
                    committer=u'\u062c\u0648\u062c\u0648'
                              u' Meinel <juju@info.com>',
                    timestamp=1156451297.96, timezone=0)
        self.tree = tree

    def test_log_C(self):
        out, err = self.run_bzr_subprocess(
            '--no-aliases --no-plugins log -q --log-format=long tree',
               env_changes={'LANG':'C', 'BZR_PROGRESS_BAR':'none',
                            'LC_ALL':None, 'LC_CTYPE':None, 'LANGUAGE':None})
        self.assertEqual('', err)
        self.assertEqualDiff("""\
------------------------------------------------------------
revno: 1
committer: ???? Meinel <juju@info.com>
branch nick: tree
timestamp: Thu 2006-08-24 20:28:17 +0000
message:
  Unicode ? commit
""", out)

    def test_log_BOGUS(self):
        out, err = self.run_bzr_subprocess(
            '--no-aliases --no-plugins log -q --log-format=long tree',
               env_changes={'LANG':'BOGUS', 'BZR_PROGRESS_BAR':'none',
                            'LC_ALL':None, 'LC_CTYPE':None, 'LANGUAGE':None})
        self.assertStartsWith(err, 'bzr: warning: unsupported locale setting')
        self.assertEqualDiff("""\
------------------------------------------------------------
revno: 1
committer: ???? Meinel <juju@info.com>
branch nick: tree
timestamp: Thu 2006-08-24 20:28:17 +0000
message:
  Unicode ? commit
""", out)
