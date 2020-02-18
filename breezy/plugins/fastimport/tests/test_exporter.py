# Copyright (C) 2010 Canonical Ltd
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
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Test the exporter."""

import os
import tempfile
import gzip

from .... import tests

from ..exporter import (
    _get_output_stream,
    check_ref_format,
    sanitize_ref_name_for_git
    )

from . import (
    FastimportFeature,
    )


class TestOutputStream(tests.TestCase):

    _test_needs_features = [FastimportFeature]

    def test_get_output_stream_stdout(self):
        # - returns standard out
        self.assertIsNot(None, _get_output_stream("-"))

    def test_get_source_gz(self):
        fd, filename = tempfile.mkstemp(suffix=".gz")
        os.close(fd)
        with _get_output_stream(filename) as stream:
            stream.write(b"bla")
        # files ending in .gz are automatically decompressed.
        with gzip.GzipFile(filename) as f:
            self.assertEquals(b"bla", f.read())

    def test_get_source_file(self):
        # other files are opened as regular files.
        fd, filename = tempfile.mkstemp()
        os.close(fd)
        with _get_output_stream(filename) as stream:
            stream.write(b"foo")
        with open(filename, 'r') as f:
            self.assertEquals("foo", f.read())


# from dulwich.tests.test_repository:
class CheckRefFormatTests(tests.TestCase):
    """Tests for the check_ref_format function.

    These are the same tests as in the git test suite.
    """

    def test_valid(self):
        self.assertTrue(check_ref_format(b'heads/foo'))
        self.assertTrue(check_ref_format(b'foo/bar/baz'))
        self.assertTrue(check_ref_format(b'refs///heads/foo'))
        self.assertTrue(check_ref_format(b'foo./bar'))
        self.assertTrue(check_ref_format(b'heads/foo@bar'))
        self.assertTrue(check_ref_format(b'heads/fix.lock.error'))

    def test_invalid(self):
        self.assertFalse(check_ref_format(b'foo'))
        self.assertFalse(check_ref_format(b'foo/.bar'))
        self.assertFalse(check_ref_format(b'heads/foo/'))
        self.assertFalse(check_ref_format(b'heads/foo.'))
        self.assertFalse(check_ref_format(b'./foo'))
        self.assertFalse(check_ref_format(b'.refs/foo'))
        self.assertFalse(check_ref_format(b'heads/foo..bar'))
        self.assertFalse(check_ref_format(b'heads/foo?bar'))
        self.assertFalse(check_ref_format(b'heads/foo.lock'))
        self.assertFalse(check_ref_format(b'heads/v@{ation'))
        self.assertFalse(check_ref_format(b'heads/foo\\bar'))
        self.assertFalse(check_ref_format(b'heads/foo\bar'))
        self.assertFalse(check_ref_format(b'heads/foo bar'))
        self.assertFalse(check_ref_format(b'heads/foo\020bar'))
        self.assertFalse(check_ref_format(b'heads/foo\177bar'))


class CheckRefnameRewriting(tests.TestCase):
    """Tests for sanitize_ref_name_for_git function"""

    def test_passthrough_valid(self):
        self.assertEqual(sanitize_ref_name_for_git(b'heads/foo'), b'heads/foo')
        self.assertEqual(sanitize_ref_name_for_git(
            b'foo/bar/baz'), b'foo/bar/baz')
        self.assertEqual(sanitize_ref_name_for_git(
            b'refs///heads/foo'), b'refs///heads/foo')
        self.assertEqual(sanitize_ref_name_for_git(b'foo./bar'), b'foo./bar')
        self.assertEqual(sanitize_ref_name_for_git(
            b'heads/foo@bar'), b'heads/foo@bar')
        self.assertEqual(sanitize_ref_name_for_git(
            b'heads/fix.lock.error'), b'heads/fix.lock.error')

    def test_rewrite_invalid(self):
        self.assertTrue(check_ref_format(
            sanitize_ref_name_for_git(b'foo./bar')))
        self.assertTrue(check_ref_format(
            sanitize_ref_name_for_git(b'heads/foo/')))
        self.assertTrue(check_ref_format(
            sanitize_ref_name_for_git(b'heads/foo.')))
        self.assertTrue(check_ref_format(sanitize_ref_name_for_git(b'./foo')))
        self.assertTrue(check_ref_format(
            sanitize_ref_name_for_git(b'.refs/foo')))
        self.assertTrue(check_ref_format(
            sanitize_ref_name_for_git(b'heads/foo..bar')))
        self.assertTrue(check_ref_format(
            sanitize_ref_name_for_git(b'heads/foo?bar')))
        self.assertTrue(check_ref_format(
            sanitize_ref_name_for_git(b'heads/foo.lock')))
        self.assertTrue(check_ref_format(
            sanitize_ref_name_for_git(b'heads/v@{ation')))
        self.assertTrue(check_ref_format(
            sanitize_ref_name_for_git(b'heads/foo\bar')))
        self.assertTrue(check_ref_format(
            sanitize_ref_name_for_git(b'heads/foo\\bar')))
        self.assertTrue(check_ref_format(
            sanitize_ref_name_for_git(b'heads/foo bar')))
        self.assertTrue(check_ref_format(
            sanitize_ref_name_for_git(b'heads/foo\020bar')))
        self.assertTrue(check_ref_format(
            sanitize_ref_name_for_git(b'heads/foo\177bar')))
