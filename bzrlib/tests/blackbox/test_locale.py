# Copyright (C) 2006 by Canonical Ltd
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

"""Test that bzr handles locales in a reasonable way"""

import os
import sys

from bzrlib.tests import TestCaseWithTransport


class TestLocale(TestCaseWithTransport):

    def setUp(self):
        super(TestLocale, self).setUp()

        if sys.platform in ('win32',):
            raise TestSkipped('Windows does not respond to the LANG'
                              ' env variable')
        orig_progress = os.environ.get('BZR_PROGRESS_BAR')
        orig_lang = os.environ.get('LANG')

        def restore():
            if orig_lang is None:
                del os.environ['LANG']
            else:
                os.environ['LANG'] = orig_lang
            if orig_progress is None:
                del os.environ['BZR_PROGRESS_BAR']
            else:
                os.environ['BZR_PROGRESS_BAR'] = orig_progress

        self.addCleanup(restore)
        # Don't confuse things with progress bars
        os.environ['BZR_PROGRESS_BAR'] = 'none'

        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/a'])
        tree.add('a')
        tree.commit(u'Unicode \xb5 commit', rev_id='r1',
                    committer=u'\u062c\u0648\u062c\u0648'
                              u' Meinel <juju@info.com>',
                    timestamp=1156451297.96, timezone=0)
        self.tree = tree

    def test_log_C(self):
        os.environ['LANG'] = 'C'
        out, err = self.run_bzr_subprocess('--no-aliases', '--no-plugins',
                                           '-q', 'log', '--log-format=long',
                                           'tree')
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
        os.environ['LANG'] = 'BOGUS'
        out, err = self.run_bzr_subprocess('--no-aliases', '--no-plugins',
                                           '-q', 'log', '--log-format=long',
                                           'tree')
        # XXX: This depends on the exact formatting of a locale.Error
        # as the first part of the string. It may be a little tempermental
        self.assertEqualDiff("""\
bzr: warning: unsupported locale setting
  Could not what text encoding to use.
  This error usually means your Python interpreter
  doesn't support the locale set by $LANG (BOGUS)
  Continuing with ascii encoding.
""", err)
        self.assertEqualDiff("""\
------------------------------------------------------------
revno: 1
committer: ???? Meinel <juju@info.com>
branch nick: tree
timestamp: Thu 2006-08-24 20:28:17 +0000
message:
  Unicode ? commit
""", out)
