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

"""Tests for the urlutils wrapper."""

import os
import sys

import bzrlib
from bzrlib.errors import InvalidURL
import bzrlib.urlutils as urlutils
from bzrlib.tests import TestCaseInTempDir, TestCase


class TestUrlToPath(TestCase):
    
    def test_basename(self):
        # bzrlib.urlutils.basename
        # Test bzrlib.urlutils.split()
        basename = urlutils.basename
        if sys.platform == 'win32':
            self.assertRaises(InvalidURL, basename, 'file:///path/to/foo')
            self.assertEqual('foo', basename('file:///C|/foo'))
            self.assertEqual('', basename('file:///C|/'))
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

    def test_normalize_url(self):
        pass

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
        self.assertEqual('file:///path/to/r%C3%A4ksm%C3%B6rg%C3%A5s',
            to_url(u'/path/to/r\xe4ksm\xf6rg\xe5s'))

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
        self.assertEqual('file:///C|/path/to/foo',
            to_url('C:/path/to/foo'))
        self.assertEqual('file:///D|/path/to/r%C3%A4ksm%C3%B6rg%C3%A5s',
            to_url(u'd:/path/to/r\xe4ksm\xf6rg\xe5s'))

    def test_win32_local_path_from_url(self):
        from_url = urlutils._win32_local_path_from_url
        self.assertEqual('C:/path/to/foo',
            from_url('file:///C|/path/to/foo'))
        self.assertEqual(u'D:/path/to/r\xe4ksm\xf6rg\xe5s',
            from_url('file:///d|/path/to/r%C3%A4ksm%C3%B6rg%C3%A5s'))
        self.assertEqual(u'D:/path/to/r\xe4ksm\xf6rg\xe5s',
            from_url('file:///d|/path/to/r%c3%a4ksm%c3%b6rg%c3%a5s'))

        self.assertRaises(InvalidURL, from_url, '/path/to/foo')
        # Not a valid _win32 url, no drive letter
        self.assertRaises(InvalidURL, from_url, 'file:///path/to/foo')

    def test_split(self):
        # Test bzrlib.urlutils.split()
        split = urlutils.split
        if sys.platform == 'win32':
            self.assertRaises(InvalidURL, split, 'file:///path/to/foo')
            self.assertEqual(('file:///C|/', 'foo'), split('file:///C|/foo'))
            self.assertEqual(('file:///C|/', ''), split('file:///C|/'))
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

    def test_strip_trailing_slash(self):
        sts = urlutils.strip_trailing_slash
        if sys.platform == 'win32':
            self.assertEqual('file:///C|/', sts('file:///C|/'))
            self.assertEqual('file:///C|/foo', sts('file:///C|/foo'))
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

    def test_unescape_for_display(self):
        # Test that URLs are converted to nice unicode strings for display
        disp = urlutils.unescape_for_display
        eq = self.assertEqual
        eq('http://foo', disp('http://foo'))
        if sys.platform == 'win32':
            eq('C:/foo/path', disp('file:///C|foo/path'))
        else:
            eq('/foo/path', disp('file:///foo/path'))

        eq('http://foo/%2Fbaz', disp('http://foo/%2Fbaz'))
        eq(u'http://host/r\xe4ksm\xf6rg\xe5s', disp('http://host/r%C3%A4ksm%C3%B6rg%C3%A5s'))

        # Make sure special escaped characters stay escaped
        eq(u'http://host/%3B%2F%3F%3A%40%26%3D%2B%24%2C%23',
            disp('http://host/%3B%2F%3F%3A%40%26%3D%2B%24%2C%23'))

        # Can we handle sections that don't have utf-8 encoding?
        eq(u'http://host/%EE%EE%EE/r\xe4ksm\xf6rg\xe5s',
            disp('http://host/%EE%EE%EE/r%C3%A4ksm%C3%B6rg%C3%A5s'))

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

