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

"""Tests for handling of ignore files"""

from cStringIO import StringIO

from bzrlib import config, errors, ignores
from bzrlib.tests import TestCase, TestCaseInTempDir


class TestParseIgnoreFile(TestCase):

    def test_parse_fancy(self):
        ignored = ignores.parse_ignore_file(StringIO(
                './rootdir\n'
                'randomfile*\n'
                'path/from/ro?t\n'
                'unicode\xc2\xb5\n' # u'\xb5'.encode('utf8')
                'dos\r\n'
                '\n' # empty line
                '#comment\n'
                ' xx \n' # whitespace
                ))
        self.assertEqual(['./rootdir', 'randomfile*'
                          , 'path/from/ro?t'
                          , u'unicode\xb5'
                          , 'dos'
                          , ' xx '], ignored)
    def test_parse_empty(self):
        ignored = ignores.parse_ignore_file(StringIO(''))
        self.assertEqual([], ignored)


class TestUserIgnores(TestCaseInTempDir):
    
    def test_create_if_missing(self):
        # $HOME should be set to '.'
        ignore_path = config.user_ignore_config_filename()
        self.failIfExists(ignore_path)
        user_ignores = ignores.get_user_ignores()
        self.assertEqual(ignores.USER_DEFAULTS, user_ignores)

        self.failUnlessExists(ignore_path)
        f = open(ignore_path, 'rb')
        try:
            entries = ignores.parse_ignore_file(f)
        finally:
            f.close()
        self.assertEqual(ignores.USER_DEFAULTS, user_ignores)

    def test_use_existing(self):
        patterns = ['*.o', '*.py[co]', u'\xe5*']
        ignores.set_user_ignores(patterns)

        user_ignores = ignores.get_user_ignores()
        self.assertEqual(patterns, user_ignores)

    def test_use_empty(self):
        ignores.set_user_ignores([])
        ignore_path = config.user_ignore_config_filename()
        self.check_file_contents(ignore_path, '')

        self.assertEqual([], ignores.get_user_ignores())

    def test_set(self):
        patterns = ['*.py[co]', '*.py[oc]']
        ignores.set_user_ignores(patterns)

        self.assertEqual(patterns, ignores.get_user_ignores())

        patterns = ['vim', '*.swp']
        ignores.set_user_ignores(patterns)
        self.assertEqual(patterns, ignores.get_user_ignores())

    def test_add(self):
        """Test that adding will not duplicate ignores"""
        # Create an empty file
        ignores.set_user_ignores([])

        patterns = ['foo', './bar', u'b\xe5z']
        added = ignores.add_unique_user_ignores(patterns)
        self.assertEqual(patterns, added)
        self.assertEqual(patterns, ignores.get_user_ignores())

    def test_add_unique(self):
        """Test that adding will not duplicate ignores"""
        ignores.set_user_ignores(['foo', './bar', u'b\xe5z'])

        added = ignores.add_unique_user_ignores(['xxx', './bar', 'xxx'])
        self.assertEqual(['xxx'], added)
        self.assertEqual(['foo', './bar', u'b\xe5z', 'xxx'],
                         ignores.get_user_ignores())
