# Copyright (C) 2006, 2011 Canonical Ltd
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

"""Test that brz handles locales in a reasonable way"""

import sys
import unittest

from breezy import (
    tests,
    )


class TestLocale(tests.TestCaseWithTransport):

    def setUp(self):
        super(TestLocale, self).setUp()

        if sys.platform in ('win32',):
            raise tests.TestSkipped('Windows does not respond to the LANG'
                                    ' env variable')

        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/a'])
        tree.add('a')
        tree.commit(u'Unicode \xb5 commit', rev_id=b'r1',
                    committer=u'\u062c\u0648\u062c\u0648'
                              u' Meinel <juju@info.com>',
                    timestamp=1156451297.96, timezone=0)
        self.tree = tree

    def run_log_quiet_long(self, args, env_changes={}):
        cmd = ['--no-aliases', '--no-plugins', '-Oprogress_bar=none',
               'log', '-q', '--log-format=long']
        cmd.extend(args)
        return self.run_brz_subprocess(cmd, env_changes=env_changes)

    @unittest.skip("encoding when LANG=C is currently borked")
    def test_log_coerced_utf8(self):
        self.disable_missing_extensions_warning()
        out, err = self.run_log_quiet_long(
            ['tree'],
            # C is not necessarily the default locale, so set both LANG and
            # LC_ALL explicitly because LC_ALL is preferred on (some?) Linux
            # systems but only LANG is respected on Windows.
            env_changes={
                'LANG': 'C', 'LC_ALL': 'C', 'LC_CTYPE': None, 'LANGUAGE': None})
        self.assertEqual(b'', err)
        self.assertEqualDiff(b"""\
------------------------------------------------------------
revno: 1
committer: \xd8\xac\xd9\x88\xd8\xac\xd9\x88 Meinel <juju@info.com>
branch nick: tree
timestamp: Thu 2006-08-24 20:28:17 +0000
message:
  Unicode \xc2\xb5 commit
""", out)

    @unittest.skipIf(
        sys.version_info[:2] >= (3, 8),
        "python > 3.8 doesn't allow changing filesystem default encoding")
    def test_log_C(self):
        self.disable_missing_extensions_warning()
        out, err = self.run_log_quiet_long(
            ['tree'],
            # C is not necessarily the default locale, so set both LANG and
            # LC_ALL explicitly because LC_ALL is preferred on (some?) Linux
            # systems but only LANG is respected on Windows.
            env_changes={
                'LANG': 'C', 'LC_ALL': 'C', 'LC_CTYPE': None,
                'LANGUAGE': None, 'PYTHONCOERCECLOCALE': '0', 'PYTHONUTF8': '0'})
        self.assertEqual(b'', err)
        self.assertEqualDiff(b"""\
------------------------------------------------------------
revno: 1
committer: ???? Meinel <juju@info.com>
branch nick: tree
timestamp: Thu 2006-08-24 20:28:17 +0000
message:
  Unicode ? commit
""", out)

    @unittest.skipIf(
        sys.version_info[:2] >= (3, 8),
        "python > 3.8 doesn't allow changing filesystem default encoding")
    def test_log_BOGUS(self):
        out, err = self.run_log_quiet_long(
            ['tree'],
            env_changes={'LANG': 'BOGUS', 'LC_ALL': None, 'LC_CTYPE': None,
                         'LANGUAGE': None, 'PYTHONCOERCECLOCALE': '0',
                         'PYTHONUTF8': '0'})
        self.assertStartsWith(err, b'brz: WARNING: Error: unsupported locale setting')
        self.assertEqualDiff(b"""\
------------------------------------------------------------
revno: 1
committer: ???? Meinel <juju@info.com>
branch nick: tree
timestamp: Thu 2006-08-24 20:28:17 +0000
message:
  Unicode ? commit
""", out)


class TestMultibyteCodecs(tests.TestCaseWithTransport):
    """Tests for quirks of multibyte encodings and their python codecs"""

    def test_plugins_mbcs(self):
        """Ensure the plugins command works with cjkcodecs, see lp:754082"""
        self.disable_missing_extensions_warning()
        out, err = self.run_bzr(["plugins"], encoding="EUC-JP")
        # The output is tested in bt.test_plugins rather than here
        self.assertEqual("", err)
