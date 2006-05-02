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
        self.assertEqual('file:///d|/path/to/r%C3%A4ksm%C3%B6rg%C3%A5s',
            to_url(u'd:/path/to/r\xe4ksm\xf6rg\xe5s'))

    def test_win32_local_path_from_url(self):
        from_url = urlutils._win32_local_path_from_url
        self.assertEqual('C:/path/to/foo',
            from_url('file:///C|/path/to/foo'))
        self.assertEqual(u'd:/path/to/r\xe4ksm\xf6rg\xe5s',
            from_url('file:///d|/path/to/r%C3%A4ksm%C3%B6rg%C3%A5s'))
        self.assertEqual(u'd:/path/to/r\xe4ksm\xf6rg\xe5s',
            from_url('file:///d|/path/to/r%c3%a4ksm%c3%b6rg%c3%a5s'))

        self.assertRaises(InvalidURL, from_url, '/path/to/foo')
        # Not a valid _win32 url, no drive letter
        self.assertRaises(InvalidURL, from_url, 'file:///path/to/foo')

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

