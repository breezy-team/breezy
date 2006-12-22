# Copyright (C) 2005 Canonical Ltd
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

"""Tests for the urlutils wrapper."""

import os
import re
import sys

from bzrlib import osutils, urlutils
import bzrlib
from bzrlib.errors import InvalidURL, InvalidURLJoin
from bzrlib.tests import TestCaseInTempDir, TestCase, TestSkipped


class TestUrlToPath(TestCase):
    
    def test_basename(self):
        # bzrlib.urlutils.basename
        # Test bzrlib.urlutils.split()
        basename = urlutils.basename
        if sys.platform == 'win32':
            self.assertRaises(InvalidURL, basename, 'file:///path/to/foo')
            self.assertEqual('foo', basename('file:///C|/foo'))
            self.assertEqual('foo', basename('file:///C:/foo'))
            self.assertEqual('', basename('file:///C:/'))
        else:
            self.assertEqual('foo', basename('file:///foo'))
            self.assertEqual('', basename('file:///'))

        self.assertEqual('foo', basename('http://host/path/to/foo'))
        self.assertEqual('foo', basename('http://host/path/to/foo/'))
        self.assertEqual('',
            basename('http://host/path/to/foo/', exclude_trailing_slash=False))
        self.assertEqual('path', basename('http://host/path'))
        self.assertEqual('', basename('http://host/'))
        self.assertEqual('', basename('http://host'))
        self.assertEqual('path', basename('http:///nohost/path'))

        self.assertEqual('path', basename('random+scheme://user:pass@ahost:port/path'))
        self.assertEqual('path', basename('random+scheme://user:pass@ahost:port/path/'))
        self.assertEqual('', basename('random+scheme://user:pass@ahost:port/'))

        # relative paths
        self.assertEqual('foo', basename('path/to/foo'))
        self.assertEqual('foo', basename('path/to/foo/'))
        self.assertEqual('', basename('path/to/foo/',
            exclude_trailing_slash=False))
        self.assertEqual('foo', basename('path/../foo'))
        self.assertEqual('foo', basename('../path/foo'))

    def test_normalize_url_files(self):
        # Test that local paths are properly normalized
        normalize_url = urlutils.normalize_url

        def norm_file(expected, path):
            url = normalize_url(path)
            self.assertStartsWith(url, 'file:///')
            if sys.platform == 'win32':
                url = url[len('file:///C:'):]
            else:
                url = url[len('file://'):]

            self.assertEndsWith(url, expected)

        norm_file('path/to/foo', 'path/to/foo')
        norm_file('/path/to/foo', '/path/to/foo')
        norm_file('path/to/foo', '../path/to/foo')

        # Local paths are assumed to *not* be escaped at all
        try:
            u'uni/\xb5'.encode(bzrlib.user_encoding)
        except UnicodeError:
            # locale cannot handle unicode 
            pass
        else:
            norm_file('uni/%C2%B5', u'uni/\xb5')

        norm_file('uni/%25C2%25B5', u'uni/%C2%B5')
        norm_file('uni/%20b', u'uni/ b')
        # All the crazy characters get escaped in local paths => file:/// urls
        # The ' ' character must not be at the end, because on win32
        # it gets stripped off by ntpath.abspath
        norm_file('%27%20%3B/%3F%3A%40%26%3D%2B%24%2C%23', "' ;/?:@&=+$,#")

    def test_normalize_url_hybrid(self):
        # Anything with a scheme:// should be treated as a hybrid url
        # which changes what characters get escaped.
        normalize_url = urlutils.normalize_url

        eq = self.assertEqual
        eq('file:///foo/', normalize_url(u'file:///foo/'))
        eq('file:///foo/%20', normalize_url(u'file:///foo/ '))
        eq('file:///foo/%20', normalize_url(u'file:///foo/%20'))
        # Don't escape reserved characters
        eq('file:///ab_c.d-e/%f:?g&h=i+j;k,L#M$',
            normalize_url('file:///ab_c.d-e/%f:?g&h=i+j;k,L#M$'))
        eq('http://ab_c.d-e/%f:?g&h=i+j;k,L#M$',
            normalize_url('http://ab_c.d-e/%f:?g&h=i+j;k,L#M$'))

        # Escape unicode characters, but not already escaped chars
        eq('http://host/ab/%C2%B5/%C2%B5',
            normalize_url(u'http://host/ab/%C2%B5/\xb5'))

        # Unescape characters that don't need to be escaped
        eq('http://host/~bob%2525-._',
                normalize_url('http://host/%7Ebob%2525%2D%2E%5F'))
        eq('http://host/~bob%2525-._',
                normalize_url(u'http://host/%7Ebob%2525%2D%2E%5F'))

        # Normalize verifies URLs when they are not unicode
        # (indicating they did not come from the user)
        self.assertRaises(InvalidURL, normalize_url, 'http://host/\xb5')
        self.assertRaises(InvalidURL, normalize_url, 'http://host/ ')

    def test_url_scheme_re(self):
        # Test paths that may be URLs
        def test_one(url, scheme_and_path):
            """Assert that _url_scheme_re correctly matches

            :param scheme_and_path: The (scheme, path) that should be matched
                can be None, to indicate it should not match
            """
            m = urlutils._url_scheme_re.match(url)
            if scheme_and_path is None:
                self.assertEqual(None, m)
            else:
                self.assertEqual(scheme_and_path[0], m.group('scheme'))
                self.assertEqual(scheme_and_path[1], m.group('path'))

        # Local paths
        test_one('/path', None)
        test_one('C:/path', None)
        test_one('../path/to/foo', None)
        test_one(u'../path/to/fo\xe5', None)

        # Real URLS
        test_one('http://host/path/', ('http', 'host/path/'))
        test_one('sftp://host/path/to/foo', ('sftp', 'host/path/to/foo'))
        test_one('file:///usr/bin', ('file', '/usr/bin'))
        test_one('file:///C:/Windows', ('file', '/C:/Windows'))
        test_one('file:///C|/Windows', ('file', '/C|/Windows'))
        test_one(u'readonly+sftp://host/path/\xe5', ('readonly+sftp', u'host/path/\xe5'))

        # Weird stuff
        # Can't have slashes or colons in the scheme
        test_one('/path/to/://foo', None)
        test_one('path:path://foo', None)
        # Must have more than one character for scheme
        test_one('C://foo', None)
        test_one('ab://foo', ('ab', 'foo'))

    def test_dirname(self):
        # Test bzrlib.urlutils.dirname()
        dirname = urlutils.dirname
        if sys.platform == 'win32':
            self.assertRaises(InvalidURL, dirname, 'file:///path/to/foo')
            self.assertEqual('file:///C|/', dirname('file:///C|/foo'))
            self.assertEqual('file:///C|/', dirname('file:///C|/'))
        else:
            self.assertEqual('file:///', dirname('file:///foo'))
            self.assertEqual('file:///', dirname('file:///'))

        self.assertEqual('http://host/path/to', dirname('http://host/path/to/foo'))
        self.assertEqual('http://host/path/to', dirname('http://host/path/to/foo/'))
        self.assertEqual('http://host/path/to/foo',
            dirname('http://host/path/to/foo/', exclude_trailing_slash=False))
        self.assertEqual('http://host/', dirname('http://host/path'))
        self.assertEqual('http://host/', dirname('http://host/'))
        self.assertEqual('http://host', dirname('http://host'))
        self.assertEqual('http:///nohost', dirname('http:///nohost/path'))

        self.assertEqual('random+scheme://user:pass@ahost:port/',
            dirname('random+scheme://user:pass@ahost:port/path'))
        self.assertEqual('random+scheme://user:pass@ahost:port/',
            dirname('random+scheme://user:pass@ahost:port/path/'))
        self.assertEqual('random+scheme://user:pass@ahost:port/',
            dirname('random+scheme://user:pass@ahost:port/'))

        # relative paths
        self.assertEqual('path/to', dirname('path/to/foo'))
        self.assertEqual('path/to', dirname('path/to/foo/'))
        self.assertEqual('path/to/foo',
            dirname('path/to/foo/', exclude_trailing_slash=False))
        self.assertEqual('path/..', dirname('path/../foo'))
        self.assertEqual('../path', dirname('../path/foo'))

    def test_join(self):
        def test(expected, *args):
            joined = urlutils.join(*args)
            self.assertEqual(expected, joined)

        # Test a single element
        test('foo', 'foo')

        # Test relative path joining
        test('foo/bar', 'foo', 'bar')
        test('http://foo/bar', 'http://foo', 'bar')
        test('http://foo/bar', 'http://foo', '.', 'bar')
        test('http://foo/baz', 'http://foo', 'bar', '../baz')
        test('http://foo/bar/baz', 'http://foo', 'bar/baz')
        test('http://foo/baz', 'http://foo', 'bar/../baz')

        # Absolute paths
        test('http://bar', 'http://foo', 'http://bar')
        test('sftp://bzr/foo', 'http://foo', 'bar', 'sftp://bzr/foo')
        test('file:///bar', 'foo', 'file:///bar')

        # From a base path
        test('file:///foo', 'file:///', 'foo')
        test('file:///bar/foo', 'file:///bar/', 'foo')
        test('http://host/foo', 'http://host/', 'foo')
        test('http://host/', 'http://host', '')
        
        # Invalid joinings
        # Cannot go above root
        self.assertRaises(InvalidURLJoin, urlutils.join,
                'http://foo', '../baz')

    def test_function_type(self):
        if sys.platform == 'win32':
            self.assertEqual(urlutils._win32_local_path_to_url, urlutils.local_path_to_url)
            self.assertEqual(urlutils._win32_local_path_from_url, urlutils.local_path_from_url)
        else:
            self.assertEqual(urlutils._posix_local_path_to_url, urlutils.local_path_to_url)
            self.assertEqual(urlutils._posix_local_path_from_url, urlutils.local_path_from_url)

    def test_posix_local_path_to_url(self):
        to_url = urlutils._posix_local_path_to_url
        self.assertEqual('file:///path/to/foo',
            to_url('/path/to/foo'))

        try:
            result = to_url(u'/path/to/r\xe4ksm\xf6rg\xe5s')
        except UnicodeError:
            raise TestSkipped("local encoding cannot handle unicode")

        self.assertEqual('file:///path/to/r%C3%A4ksm%C3%B6rg%C3%A5s', result)

    def test_posix_local_path_from_url(self):
        from_url = urlutils._posix_local_path_from_url
        self.assertEqual('/path/to/foo',
            from_url('file:///path/to/foo'))
        self.assertEqual(u'/path/to/r\xe4ksm\xf6rg\xe5s',
            from_url('file:///path/to/r%C3%A4ksm%C3%B6rg%C3%A5s'))
        self.assertEqual(u'/path/to/r\xe4ksm\xf6rg\xe5s',
            from_url('file:///path/to/r%c3%a4ksm%c3%b6rg%c3%a5s'))

        self.assertRaises(InvalidURL, from_url, '/path/to/foo')

    def test_win32_local_path_to_url(self):
        to_url = urlutils._win32_local_path_to_url
        self.assertEqual('file:///C:/path/to/foo',
            to_url('C:/path/to/foo'))
        # BOGUS: on win32, ntpath.abspath will strip trailing
        #       whitespace, so this will always fail
        #       Though under linux, it fakes abspath support
        #       and thus will succeed
        # self.assertEqual('file:///C:/path/to/foo%20',
        #     to_url('C:/path/to/foo '))
        self.assertEqual('file:///C:/path/to/f%20oo',
            to_url('C:/path/to/f oo'))

        try:
            result = to_url(u'd:/path/to/r\xe4ksm\xf6rg\xe5s')
        except UnicodeError:
            raise TestSkipped("local encoding cannot handle unicode")

        self.assertEqual('file:///D:/path/to/r%C3%A4ksm%C3%B6rg%C3%A5s', result)

    def test_win32_unc_path_to_url(self):
        to_url = urlutils._win32_local_path_to_url
        self.assertEqual('file://HOST/path',
            to_url(r'\\HOST\path'))
        self.assertEqual('file://HOST/path',
            to_url('//HOST/path'))

        try:
            result = to_url(u'//HOST/path/to/r\xe4ksm\xf6rg\xe5s')
        except UnicodeError:
            raise TestSkipped("local encoding cannot handle unicode")

        self.assertEqual('file://HOST/path/to/r%C3%A4ksm%C3%B6rg%C3%A5s', result)


    def test_win32_local_path_from_url(self):
        from_url = urlutils._win32_local_path_from_url
        self.assertEqual('C:/path/to/foo',
            from_url('file:///C|/path/to/foo'))
        self.assertEqual(u'D:/path/to/r\xe4ksm\xf6rg\xe5s',
            from_url('file:///d|/path/to/r%C3%A4ksm%C3%B6rg%C3%A5s'))
        self.assertEqual(u'D:/path/to/r\xe4ksm\xf6rg\xe5s',
            from_url('file:///d:/path/to/r%c3%a4ksm%c3%b6rg%c3%a5s'))

        self.assertRaises(InvalidURL, from_url, '/path/to/foo')
        # Not a valid _win32 url, no drive letter
        self.assertRaises(InvalidURL, from_url, 'file:///path/to/foo')

    def test_win32_unc_path_from_url(self):
        from_url = urlutils._win32_local_path_from_url
        self.assertEqual('//HOST/path', from_url('file://HOST/path'))
        # despite IE allows 2, 4, 5 and 6 slashes in URL to another machine
        # we want to use only 2 slashes
        # Firefox understand only 5 slashes in URL, but it's ugly
        self.assertRaises(InvalidURL, from_url, 'file:////HOST/path')
        self.assertRaises(InvalidURL, from_url, 'file://///HOST/path')
        self.assertRaises(InvalidURL, from_url, 'file://////HOST/path')
        # check for file://C:/ instead of file:///C:/
        self.assertRaises(InvalidURL, from_url, 'file://C:/path')

    def test_win32_extract_drive_letter(self):
        extract = urlutils._win32_extract_drive_letter
        self.assertEqual(('file:///C:', '/foo'), extract('file://', '/C:/foo'))
        self.assertEqual(('file:///d|', '/path'), extract('file://', '/d|/path'))
        self.assertRaises(InvalidURL, extract, 'file://', '/path')

    def test_split(self):
        # Test bzrlib.urlutils.split()
        split = urlutils.split
        if sys.platform == 'win32':
            self.assertRaises(InvalidURL, split, 'file:///path/to/foo')
            self.assertEqual(('file:///C|/', 'foo'), split('file:///C|/foo'))
            self.assertEqual(('file:///C:/', ''), split('file:///C:/'))
        else:
            self.assertEqual(('file:///', 'foo'), split('file:///foo'))
            self.assertEqual(('file:///', ''), split('file:///'))

        self.assertEqual(('http://host/path/to', 'foo'), split('http://host/path/to/foo'))
        self.assertEqual(('http://host/path/to', 'foo'), split('http://host/path/to/foo/'))
        self.assertEqual(('http://host/path/to/foo', ''),
            split('http://host/path/to/foo/', exclude_trailing_slash=False))
        self.assertEqual(('http://host/', 'path'), split('http://host/path'))
        self.assertEqual(('http://host/', ''), split('http://host/'))
        self.assertEqual(('http://host', ''), split('http://host'))
        self.assertEqual(('http:///nohost', 'path'), split('http:///nohost/path'))

        self.assertEqual(('random+scheme://user:pass@ahost:port/', 'path'),
            split('random+scheme://user:pass@ahost:port/path'))
        self.assertEqual(('random+scheme://user:pass@ahost:port/', 'path'),
            split('random+scheme://user:pass@ahost:port/path/'))
        self.assertEqual(('random+scheme://user:pass@ahost:port/', ''),
            split('random+scheme://user:pass@ahost:port/'))

        # relative paths
        self.assertEqual(('path/to', 'foo'), split('path/to/foo'))
        self.assertEqual(('path/to', 'foo'), split('path/to/foo/'))
        self.assertEqual(('path/to/foo', ''),
            split('path/to/foo/', exclude_trailing_slash=False))
        self.assertEqual(('path/..', 'foo'), split('path/../foo'))
        self.assertEqual(('../path', 'foo'), split('../path/foo'))

    def test_win32_strip_local_trailing_slash(self):
        strip = urlutils._win32_strip_local_trailing_slash
        self.assertEqual('file://', strip('file://'))
        self.assertEqual('file:///', strip('file:///'))
        self.assertEqual('file:///C', strip('file:///C'))
        self.assertEqual('file:///C:', strip('file:///C:'))
        self.assertEqual('file:///d|', strip('file:///d|'))
        self.assertEqual('file:///C:/', strip('file:///C:/'))
        self.assertEqual('file:///C:/a', strip('file:///C:/a/'))

    def test_strip_trailing_slash(self):
        sts = urlutils.strip_trailing_slash
        if sys.platform == 'win32':
            self.assertEqual('file:///C|/', sts('file:///C|/'))
            self.assertEqual('file:///C:/foo', sts('file:///C:/foo'))
            self.assertEqual('file:///C|/foo', sts('file:///C|/foo/'))
        else:
            self.assertEqual('file:///', sts('file:///'))
            self.assertEqual('file:///foo', sts('file:///foo'))
            self.assertEqual('file:///foo', sts('file:///foo/'))

        self.assertEqual('http://host/', sts('http://host/'))
        self.assertEqual('http://host/foo', sts('http://host/foo'))
        self.assertEqual('http://host/foo', sts('http://host/foo/'))

        # No need to fail just because the slash is missing
        self.assertEqual('http://host', sts('http://host'))
        # TODO: jam 20060502 Should this raise InvalidURL?
        self.assertEqual('file://', sts('file://'))

        self.assertEqual('random+scheme://user:pass@ahost:port/path',
            sts('random+scheme://user:pass@ahost:port/path'))
        self.assertEqual('random+scheme://user:pass@ahost:port/path',
            sts('random+scheme://user:pass@ahost:port/path/'))
        self.assertEqual('random+scheme://user:pass@ahost:port/',
            sts('random+scheme://user:pass@ahost:port/'))

        # Make sure relative paths work too
        self.assertEqual('path/to/foo', sts('path/to/foo'))
        self.assertEqual('path/to/foo', sts('path/to/foo/'))
        self.assertEqual('../to/foo', sts('../to/foo/'))
        self.assertEqual('path/../foo', sts('path/../foo/'))

    def test_unescape_for_display_utf8(self):
        # Test that URLs are converted to nice unicode strings for display
        def test(expected, url, encoding='utf-8'):
            disp_url = urlutils.unescape_for_display(url, encoding=encoding)
            self.assertIsInstance(disp_url, unicode)
            self.assertEqual(expected, disp_url)

        test('http://foo', 'http://foo')
        if sys.platform == 'win32':
            test('C:/foo/path', 'file:///C|/foo/path')
            test('C:/foo/path', 'file:///C:/foo/path')
        else:
            test('/foo/path', 'file:///foo/path')

        test('http://foo/%2Fbaz', 'http://foo/%2Fbaz')
        test(u'http://host/r\xe4ksm\xf6rg\xe5s',
             'http://host/r%C3%A4ksm%C3%B6rg%C3%A5s')

        # Make sure special escaped characters stay escaped
        test(u'http://host/%3B%2F%3F%3A%40%26%3D%2B%24%2C%23',
             'http://host/%3B%2F%3F%3A%40%26%3D%2B%24%2C%23')

        # Can we handle sections that don't have utf-8 encoding?
        test(u'http://host/%EE%EE%EE/r\xe4ksm\xf6rg\xe5s',
             'http://host/%EE%EE%EE/r%C3%A4ksm%C3%B6rg%C3%A5s')

        # Test encoding into output that can handle some characters
        test(u'http://host/%EE%EE%EE/r\xe4ksm\xf6rg\xe5s',
             'http://host/%EE%EE%EE/r%C3%A4ksm%C3%B6rg%C3%A5s',
             encoding='iso-8859-1')

        # This one can be encoded into utf8
        test(u'http://host/\u062c\u0648\u062c\u0648',
             'http://host/%d8%ac%d9%88%d8%ac%d9%88',
             encoding='utf-8')

        # This can't be put into 8859-1 and so stays as escapes
        test(u'http://host/%d8%ac%d9%88%d8%ac%d9%88',
             'http://host/%d8%ac%d9%88%d8%ac%d9%88',
             encoding='iso-8859-1')

    def test_escape(self):
        self.assertEqual('%25', urlutils.escape('%'))
        self.assertEqual('%C3%A5', urlutils.escape(u'\xe5'))

    def test_unescape(self):
        self.assertEqual('%', urlutils.unescape('%25'))
        self.assertEqual(u'\xe5', urlutils.unescape('%C3%A5'))

        self.assertRaises(InvalidURL, urlutils.unescape, u'\xe5')
        self.assertRaises(InvalidURL, urlutils.unescape, '\xe5')
        self.assertRaises(InvalidURL, urlutils.unescape, '%E5')

    def test_escape_unescape(self):
        self.assertEqual(u'\xe5', urlutils.unescape(urlutils.escape(u'\xe5')))
        self.assertEqual('%', urlutils.unescape(urlutils.escape('%')))

    def test_relative_url(self):
        def test(expected, base, other):
            result = urlutils.relative_url(base, other)
            self.assertEqual(expected, result)
            
        test('a', 'http://host/', 'http://host/a')
        test('http://entirely/different', 'sftp://host/branch',
                    'http://entirely/different')
        test('../person/feature', 'http://host/branch/mainline',
                    'http://host/branch/person/feature')
        test('..', 'http://host/branch', 'http://host/')
        test('http://host2/branch', 'http://host1/branch', 'http://host2/branch')
        test('.', 'http://host1/branch', 'http://host1/branch')
        test('../../../branch/2b', 'file:///home/jelmer/foo/bar/2b',
                    'file:///home/jelmer/branch/2b')
        test('../../branch/2b', 'sftp://host/home/jelmer/bar/2b',
                    'sftp://host/home/jelmer/branch/2b')
        test('../../branch/feature/%2b', 'http://host/home/jelmer/bar/%2b',
                    'http://host/home/jelmer/branch/feature/%2b')
        test('../../branch/feature/2b', 'http://host/home/jelmer/bar/2b/', 
                    'http://host/home/jelmer/branch/feature/2b')
        # relative_url should preserve a trailing slash
        test('../../branch/feature/2b/', 'http://host/home/jelmer/bar/2b/',
                    'http://host/home/jelmer/branch/feature/2b/')
        test('../../branch/feature/2b/', 'http://host/home/jelmer/bar/2b',
                    'http://host/home/jelmer/branch/feature/2b/')

        # TODO: treat http://host as http://host/
        #       relative_url is typically called from a branch.base or
        #       transport.base which always ends with a /
        #test('a', 'http://host', 'http://host/a')
        test('http://host/a', 'http://host', 'http://host/a')
        #test('.', 'http://host', 'http://host/')
        test('http://host/', 'http://host', 'http://host/')
        #test('.', 'http://host/', 'http://host')
        test('http://host', 'http://host/', 'http://host')


class TestCwdToURL(TestCaseInTempDir):
    """Test that local_path_to_url works base on the cwd"""

    def test_dot(self):
        # This test will fail if getcwd is not ascii
        os.mkdir('mytest')
        os.chdir('mytest')

        url = urlutils.local_path_to_url('.')
        self.assertEndsWith(url, '/mytest')

    def test_non_ascii(self):
        try:
            os.mkdir(u'dod\xe9')
        except UnicodeError:
            raise TestSkipped('cannot create unicode directory')

        os.chdir(u'dod\xe9')

        # On Mac OSX this directory is actually: 
        #   u'/dode\u0301' => '/dode\xcc\x81
        # but we should normalize it back to 
        #   u'/dod\xe9' => '/dod\xc3\xa9'
        url = urlutils.local_path_to_url('.')
        self.assertEndsWith(url, '/dod%C3%A9')
