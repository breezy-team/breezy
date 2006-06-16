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

"""Tests for the osutils wrapper."""

import errno
import os
import socket
import stat
import sys

import bzrlib
from bzrlib.errors import BzrBadParameterNotUnicode, InvalidURL
import bzrlib.osutils as osutils
from bzrlib.tests import TestCaseInTempDir, TestCase, TestSkipped


class TestOSUtils(TestCaseInTempDir):

    def test_fancy_rename(self):
        # This should work everywhere
        def rename(a, b):
            osutils.fancy_rename(a, b,
                    rename_func=os.rename,
                    unlink_func=os.unlink)

        open('a', 'wb').write('something in a\n')
        rename('a', 'b')
        self.failIfExists('a')
        self.failUnlessExists('b')
        self.check_file_contents('b', 'something in a\n')

        open('a', 'wb').write('new something in a\n')
        rename('b', 'a')

        self.check_file_contents('a', 'something in a\n')

    def test_rename(self):
        # Rename should be semi-atomic on all platforms
        open('a', 'wb').write('something in a\n')
        osutils.rename('a', 'b')
        self.failIfExists('a')
        self.failUnlessExists('b')
        self.check_file_contents('b', 'something in a\n')

        open('a', 'wb').write('new something in a\n')
        osutils.rename('b', 'a')

        self.check_file_contents('a', 'something in a\n')

    # TODO: test fancy_rename using a MemoryTransport

    def test_01_rand_chars_empty(self):
        result = osutils.rand_chars(0)
        self.assertEqual(result, '')

    def test_02_rand_chars_100(self):
        result = osutils.rand_chars(100)
        self.assertEqual(len(result), 100)
        self.assertEqual(type(result), str)
        self.assertContainsRe(result, r'^[a-z0-9]{100}$')


    def test_rmtree(self):
        # Check to remove tree with read-only files/dirs
        os.mkdir('dir')
        f = file('dir/file', 'w')
        f.write('spam')
        f.close()
        # would like to also try making the directory readonly, but at the
        # moment python shutil.rmtree doesn't handle that properly - it would
        # need to chmod the directory before removing things inside it - deferred
        # for now -- mbp 20060505
        # osutils.make_readonly('dir')
        osutils.make_readonly('dir/file')

        osutils.rmtree('dir')

        self.failIfExists('dir/file')
        self.failIfExists('dir')

    def test_file_kind(self):
        self.build_tree(['file', 'dir/'])
        self.assertEquals('file', osutils.file_kind('file'))
        self.assertEquals('directory', osutils.file_kind('dir/'))
        if osutils.has_symlinks():
            os.symlink('symlink', 'symlink')
            self.assertEquals('symlink', osutils.file_kind('symlink'))
        
        # TODO: jam 20060529 Test a block device
        try:
            os.lstat('/dev/null')
        except OSError, e:
            if e.errno not in (errno.ENOENT,):
                raise
        else:
            self.assertEquals('chardev', osutils.file_kind('/dev/null'))

        mkfifo = getattr(os, 'mkfifo', None)
        if mkfifo:
            mkfifo('fifo')
            try:
                self.assertEquals('fifo', osutils.file_kind('fifo'))
            finally:
                os.remove('fifo')

        AF_UNIX = getattr(socket, 'AF_UNIX', None)
        if AF_UNIX:
            s = socket.socket(AF_UNIX)
            s.bind('socket')
            try:
                self.assertEquals('socket', osutils.file_kind('socket'))
            finally:
                os.remove('socket')


class TestSafeUnicode(TestCase):

    def test_from_ascii_string(self):
        self.assertEqual(u'foobar', osutils.safe_unicode('foobar'))

    def test_from_unicode_string_ascii_contents(self):
        self.assertEqual(u'bargam', osutils.safe_unicode(u'bargam'))

    def test_from_unicode_string_unicode_contents(self):
        self.assertEqual(u'bargam\xae', osutils.safe_unicode(u'bargam\xae'))

    def test_from_utf8_string(self):
        self.assertEqual(u'foo\xae', osutils.safe_unicode('foo\xc2\xae'))

    def test_bad_utf8_string(self):
        self.assertRaises(BzrBadParameterNotUnicode,
                          osutils.safe_unicode,
                          '\xbb\xbb')


class TestWin32Funcs(TestCase):
    """Test that the _win32 versions of os utilities return appropriate paths."""

    def test_abspath(self):
        self.assertEqual('C:/foo', osutils._win32_abspath('C:\\foo'))
        self.assertEqual('C:/foo', osutils._win32_abspath('C:/foo'))

    def test_realpath(self):
        self.assertEqual('C:/foo', osutils._win32_realpath('C:\\foo'))
        self.assertEqual('C:/foo', osutils._win32_realpath('C:/foo'))

    def test_pathjoin(self):
        self.assertEqual('path/to/foo', osutils._win32_pathjoin('path', 'to', 'foo'))
        self.assertEqual('C:/foo', osutils._win32_pathjoin('path\\to', 'C:\\foo'))
        self.assertEqual('C:/foo', osutils._win32_pathjoin('path/to', 'C:/foo'))
        self.assertEqual('path/to/foo', osutils._win32_pathjoin('path/to/', 'foo'))
        self.assertEqual('/foo', osutils._win32_pathjoin('C:/path/to/', '/foo'))
        self.assertEqual('/foo', osutils._win32_pathjoin('C:\\path\\to\\', '\\foo'))

    def test_normpath(self):
        self.assertEqual('path/to/foo', osutils._win32_normpath(r'path\\from\..\to\.\foo'))
        self.assertEqual('path/to/foo', osutils._win32_normpath('path//from/../to/./foo'))

    def test_getcwd(self):
        self.assertEqual(os.getcwdu().replace('\\', '/'), osutils._win32_getcwd())


class TestWin32FuncsDirs(TestCaseInTempDir):
    """Test win32 functions that create files."""
    
    def test_getcwd(self):
        # Make sure getcwd can handle unicode filenames
        try:
            os.mkdir(u'B\xe5gfors')
        except UnicodeError:
            raise TestSkipped("Unable to create Unicode filename")

        os.chdir(u'B\xe5gfors')
        # TODO: jam 20060427 This will probably fail on Mac OSX because
        #       it will change the normalization of B\xe5gfors
        #       Consider using a different unicode character, or make
        #       osutils.getcwd() renormalize the path.
        self.assertTrue(osutils._win32_getcwd().endswith(u'/B\xe5gfors'))

    def test_mkdtemp(self):
        tmpdir = osutils._win32_mkdtemp(dir='.')
        self.assertFalse('\\' in tmpdir)

    def test_rename(self):
        a = open('a', 'wb')
        a.write('foo\n')
        a.close()
        b = open('b', 'wb')
        b.write('baz\n')
        b.close()

        osutils._win32_rename('b', 'a')
        self.failUnlessExists('a')
        self.failIfExists('b')
        self.assertFileEqual('baz\n', 'a')


class TestSplitLines(TestCase):

    def test_split_unicode(self):
        self.assertEqual([u'foo\n', u'bar\xae'],
                         osutils.split_lines(u'foo\nbar\xae'))
        self.assertEqual([u'foo\n', u'bar\xae\n'],
                         osutils.split_lines(u'foo\nbar\xae\n'))

    def test_split_with_carriage_returns(self):
        self.assertEqual(['foo\rbar\n'],
                         osutils.split_lines('foo\rbar\n'))


class TestWalkDirs(TestCaseInTempDir):

    def test_walkdirs(self):
        tree = [
            '.bzr',
            '0file',
            '1dir/',
            '1dir/0file',
            '1dir/1dir/',
            '2file'
            ]
        self.build_tree(tree)
        expected_dirblocks = [
                [
                    ('0file', '0file', 'file'),
                    ('1dir', '1dir', 'directory'),
                    ('2file', '2file', 'file'),
                ],
                [
                    ('1dir/0file', '0file', 'file'),
                    ('1dir/1dir', '1dir', 'directory'),
                ],
                [
                ],
            ]
        result = []
        found_bzrdir = False
        for dirblock in osutils.walkdirs('.'):
            if len(dirblock) and dirblock[0][1] == '.bzr':
                # this tests the filtering of selected paths
                found_bzrdir = True
                del dirblock[0]
            result.append(dirblock)

        self.assertTrue(found_bzrdir)
        self.assertEqual(expected_dirblocks,
            [[line[0:3] for line in block] for block in result])
        # you can search a subdir only, with a supplied prefix.
        result = []
        for dirblock in osutils.walkdirs('1dir', '1dir'):
            result.append(dirblock)
        self.assertEqual(expected_dirblocks[1:],
            [[line[0:3] for line in block] for block in result])

    def assertPathCompare(self, path_less, path_greater):
        """check that path_less and path_greater compare correctly."""
        self.assertEqual(0, osutils.compare_paths_prefix_order(
            path_less, path_less))
        self.assertEqual(0, osutils.compare_paths_prefix_order(
            path_greater, path_greater))
        self.assertEqual(-1, osutils.compare_paths_prefix_order(
            path_less, path_greater))
        self.assertEqual(1, osutils.compare_paths_prefix_order(
            path_greater, path_less))

    def test_compare_paths_prefix_order(self):
        # root before all else
        self.assertPathCompare("/", "/a")
        # alpha within a dir
        self.assertPathCompare("/a", "/b")
        self.assertPathCompare("/b", "/z")
        # high dirs before lower.
        self.assertPathCompare("/z", "/a/a")
        # except if the deeper dir should be output first
        self.assertPathCompare("/a/b/c", "/d/g")
        # lexical betwen dirs of the same height
        self.assertPathCompare("/a/z", "/z/z")
        self.assertPathCompare("/a/c/z", "/a/d/e")

        # this should also be consistent for no leading / paths
        # root before all else
        self.assertPathCompare("", "a")
        # alpha within a dir
        self.assertPathCompare("a", "b")
        self.assertPathCompare("b", "z")
        # high dirs before lower.
        self.assertPathCompare("z", "a/a")
        # except if the deeper dir should be output first
        self.assertPathCompare("a/b/c", "d/g")
        # lexical betwen dirs of the same height
        self.assertPathCompare("a/z", "z/z")
        self.assertPathCompare("a/c/z", "a/d/e")

    def test_path_prefix_sorting(self):
        """Doing a sort on path prefix should match our sample data."""
        original_paths = [
            'a',
            'a/b',
            'a/b/c',
            'b',
            'b/c',
            'd',
            'd/e',
            'd/e/f',
            'd/f',
            'd/g',
            'g',
            ]

        dir_sorted_paths = [
            'a',
            'b',
            'd',
            'g',
            'a/b',
            'a/b/c',
            'b/c',
            'd/e',
            'd/f',
            'd/g',
            'd/e/f',
            ]

        self.assertEqual(
            dir_sorted_paths,
            sorted(original_paths, key=osutils.path_prefix_key))
        # using the comparison routine shoudl work too:
        self.assertEqual(
            dir_sorted_paths,
            sorted(original_paths, cmp=osutils.compare_paths_prefix_order))
