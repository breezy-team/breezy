# Copyright (C) 2008 Canonical Ltd
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

"""Tests for the win32 walkdir extension."""

import errno

from bzrlib import (
    osutils,
    tests,
    )


class _Win32ReadDirFeature(tests.Feature):

    def _probe(self):
        try:
            import bzrlib._walkdirs_win32
        except ImportError:
            return False
        else:
            return True

    def feature_name(self):
        return 'bzrlib._Win32ReadDir'

Win32ReadDirFeature = _Win32ReadDirFeature()


class TestWin32Finder(tests.TestCaseInTempDir):

    _test_needs_features = [Win32ReadDirFeature]

    def setUp(self):
        super(TestWin32Finder, self).setUp()
        from bzrlib._walkdirs_win32 import (
            Win32ReadDir,
            )
        self.reader = Win32ReadDir()

    def _remove_stat_from_dirblock(self, dirblock):
        return [info[:3] + info[4:] for info in dirblock]

    def assertWalkdirs(self, expected, top, prefix=''):
        old_selected_dir_reader = osutils._selected_dir_reader
        try:
            osutils._selected_dir_reader = self.reader
            finder = osutils._walkdirs_utf8(top, prefix=prefix)
            result = []
            for dirname, dirblock in finder:
                dirblock = self._remove_stat_from_dirblock(dirblock)
                result.append((dirname, dirblock))
            self.assertEqual(expected, result)
        finally:
            osutils._selected_dir_reader = old_selected_dir_reader

    def assertReadDir(self, expected, prefix, top_unicode):
        result = self._remove_stat_from_dirblock(
            self.reader.read_dir(prefix, top_unicode))
        self.assertEqual(expected, result)

    def test_top_prefix_to_starting_dir(self):
        # preparing an iteration should create a unicode native path.
        self.assertEqual(('prefix', None, None, None, u'\x12'),
            self.reader.top_prefix_to_starting_dir(u'\x12'.encode('utf8'),
                                                   'prefix'))

    def test_empty_directory(self):
        self.assertReadDir([], 'prefix', u'.')
        self.assertWalkdirs([(('', u'.'), [])], u'.')

    def test_file(self):
        self.build_tree(['foo'])
        self.assertReadDir([('foo', 'foo', 'file', u'./foo')],
            '', u'.')

    def test_dir(self):
        self.build_tree(['bar/'])
        self.assertReadDir([('bar', 'bar', 'directory', u'./bar')],
            '', u'.')

    def test_prefix(self):
        self.build_tree(['bar/', 'baf'])
        self.assertReadDir([
            ('xxx/baf', 'baf', 'file', u'./baf'),
            ('xxx/bar', 'bar', 'directory', u'./bar'),
            ],
            'xxx', u'.')

    def test_missing_dir(self):
        e = self.assertRaises(WindowsError,
            self.reader.read_dir, 'prefix', u'no_such_dir')
        self.assertEqual(errno.ENOENT, e.errno)
        self.assertEqual(3, e.winerror)
        self.assertEqual((3, u'no_such_dir/*'), e.args)
