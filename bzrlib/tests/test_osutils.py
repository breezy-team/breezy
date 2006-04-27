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

"""Tests for the osutils wrapper.
"""

import os
import sys

import bzrlib
from bzrlib.errors import BzrBadParameterNotUnicode, InvalidURL
import bzrlib.osutils as osutils
from bzrlib.tests import TestCaseInTempDir, TestCase


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


class TestUrlToPath(TestCase):
    
    def test_function_type(self):
        if sys.platform == 'win32':
            self.assertEqual(osutils._win32_local_path_to_url, osutils.local_path_to_url)
            self.assertEqual(osutils._win32_local_path_from_url, osutils.local_path_from_url)
        else:
            self.assertEqual(osutils._posix_local_path_to_url, osutils.local_path_to_url)
            self.assertEqual(osutils._posix_local_path_from_url, osutils.local_path_from_url)

    def test_posix_local_path_to_url(self):
        to_url = osutils._posix_local_path_to_url
        self.assertEqual('file:///path/to/foo',
            to_url('/path/to/foo'))
        self.assertEqual('file:///path/to/r%C3%A4ksm%C3%B6rg%C3%A5s',
            to_url(u'/path/to/r\xe4ksm\xf6rg\xe5s'))

    def test_posix_local_path_from_url(self):
        from_url = osutils._posix_local_path_from_url
        self.assertEqual('/path/to/foo',
            from_url('file:///path/to/foo'))
        self.assertEqual(u'/path/to/r\xe4ksm\xf6rg\xe5s',
            from_url('file:///path/to/r%C3%A4ksm%C3%B6rg%C3%A5s'))
        self.assertEqual(u'/path/to/r\xe4ksm\xf6rg\xe5s',
            from_url('file:///path/to/r%c3%a4ksm%c3%b6rg%c3%a5s'))

        self.assertRaises(InvalidURL, from_url, '/path/to/foo')

    def test_win32_local_path_to_url(self):
        to_url = osutils._win32_local_path_to_url
        self.assertEqual('file:///C|/path/to/foo',
            to_url('C:/path/to/foo'))
        self.assertEqual('file:///d|/path/to/r%C3%A4ksm%C3%B6rg%C3%A5s',
            to_url(u'd:/path/to/r\xe4ksm\xf6rg\xe5s'))

    def test_win32_local_path_from_url(self):
        from_url = osutils._win32_local_path_from_url
        self.assertEqual('C:/path/to/foo',
            from_url('file:///C|/path/to/foo'))
        self.assertEqual(u'd:/path/to/r\xe4ksm\xf6rg\xe5s',
            from_url('file:///d|/path/to/r%C3%A4ksm%C3%B6rg%C3%A5s'))
        self.assertEqual(u'd:/path/to/r\xe4ksm\xf6rg\xe5s',
            from_url('file:///d|/path/to/r%c3%a4ksm%c3%b6rg%c3%a5s'))

        self.assertRaises(InvalidURL, from_url, '/path/to/foo')
        # Not a valid _win32 url, no drive letter
        self.assertRaises(InvalidURL, from_url, 'file:///path/to/foo')

    def test_urlfordisplay(self):
        # Test that URLs are converted to nice unicode strings for display
        disp = osutils.urlfordisplay
        eq = self.assertEqual
        eq('http://foo', disp('http://foo'))
        if sys.platform == 'win32':
            eq('C:/foo/path', disp('file:///C|foo/path'))
        else:
            eq('/foo/path', disp('file:///foo/path'))

        eq('http://foo/%2Fbaz', disp('http://foo/%2Fbaz'))
        eq(u'http://host/r\xe4ksm\xf6rg\xe5s', disp('http://host/r%C3%A4ksm%C3%B6rg%C3%A5s'))

        # Make sure special escaped characters stay escaped
        eq(u'http://host/%3B%2F%3F%3A%40%26%3D%2B%24%2C', disp('http://host/%3B%2F%3F%3A%40%26%3D%2B%24%2C'))


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
