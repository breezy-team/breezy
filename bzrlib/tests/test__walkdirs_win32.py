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

from bzrlib import tests


class _WalkdirsWin32Feature(tests.Feature):

    def _probe(self):
        try:
            import bzrlib._walkdirs_win32
        except ImportError:
            return False
        else:
            return True

    def feature_name(self):
        return 'bzrlib._walkdirs_win32'

WalkdirsWin32Feature = _WalkdirsWin32Feature()


class TestWin32Finder(tests.TestCaseInTempDir):

    _test_needs_features = [WalkdirsWin32Feature]

    def setUp(self):
        super(TestWin32Finder, self).setUp()
        from bzrlib._walkdirs_win32 import (
            _walkdirs_utf8_win32_find_file
            )
        self.walkdirs_utf8 = _walkdirs_utf8_win32_find_file

    def _remove_stat_from_dirblock(self, dirblock):
        return [info[:3] + info[4:] for info in dirblock]

    def assertWalkdirs(self, expected, top, prefix=''):
        finder = self.walkdirs_utf8(top, prefix=prefix)
        result = []
        for dirname, dirblock in finder:
            result.append((dirname, self._remove_stat_from_dirblock(dirblock)))
        self.assertEqual(expected, result)

    def test_empty_directory(self):
        self.assertWalkdirs([(('', u'.'), [])], u'.')

    def test_file_in_dir(self):
        self.build_tree(['foo'])
        self.assertWalkdirs([
            (('', u'.'), [('foo', 'foo', 'file', u'./foo')])
            ], u'.')

    def test_subdir(self):
        self.build_tree(['foo', 'bar/', 'bar/baz'])
        self.assertWalkdirs([
            (('', u'.'), [('bar', 'bar', 'directory', u'./bar'),
                          ('foo', 'foo', 'file', u'./foo'),
                         ]),
            (('bar', u'./bar'), [('bar/baz', 'baz', 'file', u'./bar/baz')]),
            ], '.')
        self.assertWalkdirs([
            (('xxx', u'.'), [('xxx/bar', 'bar', 'directory', u'./bar'),
                             ('xxx/foo', 'foo', 'file', u'./foo'),
                            ]),
            (('xxx/bar', u'./bar'), [('xxx/bar/baz', 'baz', 'file', u'./bar/baz')]),
            ], '.', prefix='xxx')
        self.assertWalkdirs([
            (('', u'bar'), [('baz', 'baz', 'file', u'bar/baz')]),
            ], 'bar')

    def test_skip_subdir(self): 
        self.build_tree(['a/', 'b/', 'c/', 'a/aa', 'b/bb', 'c/cc'])
        base_dirblock = [('a', 'a', 'directory', u'./a'),
                          ('b', 'b', 'directory', u'./b'),
                          ('c', 'c', 'directory', u'./c'),
                         ]
        self.assertWalkdirs([
            (('', u'.'), base_dirblock),
            (('a', u'./a'), [('a/aa', 'aa', 'file', u'./a/aa')]),
            (('b', u'./b'), [('b/bb', 'bb', 'file', u'./b/bb')]),
            (('c', u'./c'), [('c/cc', 'cc', 'file', u'./c/cc')]),
            ], '.')

        walker = self.walkdirs_utf8('.')
        dir_info, first_dirblock = walker.next()
        self.assertEqual(('', u'.'), dir_info)
        self.assertEqual(base_dirblock,
                         self._remove_stat_from_dirblock(first_dirblock))
        # Now, remove 'b' and it should be skipped on the next round
        del first_dirblock[1]
        dir_info, second_dirblock = walker.next()
        second_dirblock = self._remove_stat_from_dirblock(second_dirblock)
        self.assertEqual(('a', u'./a'), dir_info)
        self.assertEqual([('a/aa', 'aa', 'file', u'./a/aa')], second_dirblock)
        dir_info, third_dirblock = walker.next()
        third_dirblock = self._remove_stat_from_dirblock(third_dirblock)
        self.assertEqual(('c', u'./c'), dir_info)
        self.assertEqual([('c/cc', 'cc', 'file', u'./c/cc')], third_dirblock)

    def test_missing_dir(self):
        e = self.assertRaises(WindowsError, list,
                                self.walkdirs_utf8(u'no_such_dir'))
        self.assertEqual(errno.ENOENT, e.errno)
        self.assertEqual(3, e.winerror)
        self.assertEqual((3, u'no_such_dir/*'), e.args)
