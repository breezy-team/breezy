# Copyright (C) 2006-2012, 2015, 2016 Canonical Ltd
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

"""Tests for the urlutils wrapper."""

import os
import sys

from .. import osutils, urlutils
from ..errors import PathNotChild
from . import TestCase, TestCaseInTempDir, TestSkipped, features


class TestUrlToPath(TestCase):
    def test_basename(self):
        # breezy.urlutils.basename
        # Test breezy.urlutils.split()
        basename = urlutils.basename
        if sys.platform == "win32":
            self.assertRaises(urlutils.InvalidURL, basename, "file:///path/to/foo")
            self.assertEqual("foo", basename("file:///C|/foo"))
            self.assertEqual("foo", basename("file:///C:/foo"))
            self.assertEqual("", basename("file:///C:/"))
        else:
            self.assertEqual("foo", basename("file:///foo"))
            self.assertEqual("", basename("file:///"))

        self.assertEqual("foo", basename("http://host/path/to/foo"))
        self.assertEqual("foo", basename("http://host/path/to/foo/"))
        self.assertEqual(
            "", basename("http://host/path/to/foo/", exclude_trailing_slash=False)
        )
        self.assertEqual("path", basename("http://host/path"))
        self.assertEqual("", basename("http://host/"))
        self.assertEqual("", basename("http://host"))
        self.assertEqual("path", basename("http:///nohost/path"))

        self.assertEqual("path", basename("random+scheme://user:pass@ahost:port/path"))
        self.assertEqual("path", basename("random+scheme://user:pass@ahost:port/path/"))
        self.assertEqual("", basename("random+scheme://user:pass@ahost:port/"))

        # relative paths
        self.assertEqual("foo", basename("path/to/foo"))
        self.assertEqual("foo", basename("path/to/foo/"))
        self.assertEqual("", basename("path/to/foo/", exclude_trailing_slash=False))
        self.assertEqual("foo", basename("path/../foo"))
        self.assertEqual("foo", basename("../path/foo"))

    def test_normalize_url_files(self):
        # Test that local paths are properly normalized
        normalize_url = urlutils.normalize_url

        def norm_file(expected, path):
            url = normalize_url(path)
            self.assertStartsWith(url, "file:///")
            if sys.platform == "win32":
                url = url[len("file:///C:") :]
            else:
                url = url[len("file://") :]

            self.assertEndsWith(url, expected)

        norm_file("path/to/foo", "path/to/foo")
        norm_file("/path/to/foo", "/path/to/foo")
        norm_file("path/to/foo", "../path/to/foo")

        # Local paths are assumed to *not* be escaped at all
        try:
            "uni/\xb5".encode(osutils.get_user_encoding())
        except UnicodeError:
            # locale cannot handle unicode
            pass
        else:
            norm_file("uni/%C2%B5", "uni/\xb5")

        norm_file("uni/%25C2%25B5", "uni/%C2%B5")
        norm_file("uni/%20b", "uni/ b")
        # All the crazy characters get escaped in local paths => file:/// urls
        # The ' ' character must not be at the end, because on win32
        # it gets stripped off by ntpath.abspath
        norm_file("%27%20%3B/%3F%3A%40%26%3D%2B%24%2C%23", "' ;/?:@&=+$,#")

    def test_normalize_url_hybrid(self):
        # Anything with a scheme:// should be treated as a hybrid url
        # which changes what characters get escaped.
        normalize_url = urlutils.normalize_url

        eq = self.assertEqual
        eq("file:///foo/", normalize_url("file:///foo/"))
        eq("file:///foo/%20", normalize_url("file:///foo/ "))
        eq("file:///foo/%20", normalize_url("file:///foo/%20"))
        # Don't escape reserved characters
        eq(
            "file:///ab_c.d-e/%f:?g&h=i+j;k,L#M$",
            normalize_url("file:///ab_c.d-e/%f:?g&h=i+j;k,L#M$"),
        )
        eq(
            "http://ab_c.d-e/%f:?g&h=i+j;k,L#M$",
            normalize_url("http://ab_c.d-e/%f:?g&h=i+j;k,L#M$"),
        )

        # Escape unicode characters, but not already escaped chars
        eq("http://host/ab/%C2%B5/%C2%B5", normalize_url("http://host/ab/%C2%B5/\xb5"))

        # Unescape characters that don't need to be escaped
        eq(
            "http://host/~bob%2525-._",
            normalize_url("http://host/%7Ebob%2525%2D%2E%5F"),
        )
        eq(
            "http://host/~bob%2525-._",
            normalize_url("http://host/%7Ebob%2525%2D%2E%5F"),
        )

    def test_url_scheme_re(self):
        # Test paths that may be URLs
        def test_one(url, scheme_and_path):
            """Assert that _url_scheme_re correctly matches.

            :param scheme_and_path: The (scheme, path) that should be matched
                can be None, to indicate it should not match
            """
            m = urlutils._url_scheme_re.match(url)
            if scheme_and_path is None:
                self.assertEqual(None, m)
            else:
                self.assertEqual(scheme_and_path[0], m.group("scheme"))
                self.assertEqual(scheme_and_path[1], m.group("path"))

        # Local paths
        test_one("/path", None)
        test_one("C:/path", None)
        test_one("../path/to/foo", None)
        test_one("../path/to/fo\xe5", None)

        # Real URLS
        test_one("http://host/path/", ("http", "host/path/"))
        test_one("sftp://host/path/to/foo", ("sftp", "host/path/to/foo"))
        test_one("file:///usr/bin", ("file", "/usr/bin"))
        test_one("file:///C:/Windows", ("file", "/C:/Windows"))
        test_one("file:///C|/Windows", ("file", "/C|/Windows"))
        test_one("readonly+sftp://host/path/\xe5", ("readonly+sftp", "host/path/\xe5"))

        # Weird stuff
        # Can't have slashes or colons in the scheme
        test_one("/path/to/://foo", None)
        test_one("scheme:stuff://foo", ("scheme", "stuff://foo"))
        # Must have more than one character for scheme
        test_one("C://foo", None)
        test_one("ab://foo", ("ab", "foo"))

    def test_dirname(self):
        # Test breezy.urlutils.dirname()
        dirname = urlutils.dirname
        if sys.platform == "win32":
            self.assertRaises(urlutils.InvalidURL, dirname, "file:///path/to/foo")
            self.assertEqual("file:///C|/", dirname("file:///C|/foo"))
            self.assertEqual("file:///C|/", dirname("file:///C|/"))
        else:
            self.assertEqual("file:///", dirname("file:///foo"))
            self.assertEqual("file:///", dirname("file:///"))

        self.assertEqual("http://host/path/to", dirname("http://host/path/to/foo"))
        self.assertEqual("http://host/path/to", dirname("http://host/path/to/foo/"))
        self.assertEqual(
            "http://host/path/to/foo",
            dirname("http://host/path/to/foo/", exclude_trailing_slash=False),
        )
        self.assertEqual("http://host/", dirname("http://host/path"))
        self.assertEqual("http://host/", dirname("http://host/"))
        self.assertEqual("http://host", dirname("http://host"))
        self.assertEqual("http:///nohost", dirname("http:///nohost/path"))

        self.assertEqual(
            "random+scheme://user:pass@ahost:port/",
            dirname("random+scheme://user:pass@ahost:port/path"),
        )
        self.assertEqual(
            "random+scheme://user:pass@ahost:port/",
            dirname("random+scheme://user:pass@ahost:port/path/"),
        )
        self.assertEqual(
            "random+scheme://user:pass@ahost:port/",
            dirname("random+scheme://user:pass@ahost:port/"),
        )

        # relative paths
        self.assertEqual("path/to", dirname("path/to/foo"))
        self.assertEqual("path/to", dirname("path/to/foo/"))
        self.assertEqual(
            "path/to/foo", dirname("path/to/foo/", exclude_trailing_slash=False)
        )
        self.assertEqual("path/..", dirname("path/../foo"))
        self.assertEqual("../path", dirname("../path/foo"))

    def test_is_url(self):
        self.assertTrue(urlutils.is_url("http://foo/bar"))
        self.assertTrue(urlutils.is_url("bzr+ssh://foo/bar"))
        self.assertTrue(urlutils.is_url("lp:foo/bar"))
        self.assertTrue(urlutils.is_url("file:///foo/bar"))
        self.assertFalse(urlutils.is_url(""))
        self.assertFalse(urlutils.is_url("foo"))
        self.assertFalse(urlutils.is_url("foo/bar"))
        self.assertFalse(urlutils.is_url("/foo"))
        self.assertFalse(urlutils.is_url("/foo/bar"))
        self.assertFalse(urlutils.is_url("C:/"))
        self.assertFalse(urlutils.is_url("C:/foo"))
        self.assertFalse(urlutils.is_url("C:/foo/bar"))

    def test_join(self):
        def test(expected, *args):
            joined = urlutils.join(*args)
            self.assertEqual(expected, joined)

        # Test relative path joining
        test("foo", "foo")  # relative fragment with nothing is preserved.
        test("foo/bar", "foo", "bar")
        test("http://foo/bar", "http://foo", "bar")
        test("http://foo/bar", "http://foo", ".", "bar")
        test("http://foo/baz", "http://foo", "bar", "../baz")
        test("http://foo/bar/baz", "http://foo", "bar/baz")
        test("http://foo/baz", "http://foo", "bar/../baz")
        test("http://foo/baz", "http://foo/bar/", "../baz")
        test("lp:foo/bar", "lp:foo", "bar")
        test("lp:foo/bar/baz", "lp:foo", "bar/baz")

        # Absolute paths
        test("http://foo", "http://foo")  # abs url with nothing is preserved.
        test("http://bar", "http://foo", "http://bar")
        test("sftp://bzr/foo", "http://foo", "bar", "sftp://bzr/foo")
        test("file:///bar", "foo", "file:///bar")
        test("http://bar/", "http://foo", "http://bar/")
        test("http://bar/a", "http://foo", "http://bar/a")
        test("http://bar/a/", "http://foo", "http://bar/a/")
        test("lp:bar", "http://foo", "lp:bar")
        test("lp:bar", "lp:foo", "lp:bar")
        test("file:///stuff", "lp:foo", "file:///stuff")

        # From a base path
        test("file:///foo", "file:///", "foo")
        test("file:///bar/foo", "file:///bar/", "foo")
        test("http://host/foo", "http://host/", "foo")
        test("http://host/", "http://host", "")

        # Invalid joinings
        # Cannot go above root
        # Implicitly at root:
        self.assertRaises(
            urlutils.InvalidURLJoin, urlutils.join, "http://foo", "../baz"
        )
        self.assertRaises(urlutils.InvalidURLJoin, urlutils.join, "http://foo", "/..")
        # Joining from a path explicitly under the root.
        self.assertRaises(
            urlutils.InvalidURLJoin, urlutils.join, "http://foo/a", "../../b"
        )

    def test_joinpath(self):
        def test(expected, *args):
            joined = urlutils.joinpath(*args)
            self.assertEqual(expected, joined)

        # Test a single element
        test("foo", "foo")

        # Test relative path joining
        test("foo/bar", "foo", "bar")
        test("foo/bar", "foo", ".", "bar")
        test("foo/baz", "foo", "bar", "../baz")
        test("foo/bar/baz", "foo", "bar/baz")
        test("foo/baz", "foo", "bar/../baz")

        # Test joining to an absolute path
        test("/foo", "/foo")
        test("/foo", "/foo", ".")
        test("/foo/bar", "/foo", "bar")
        test("/", "/foo", "..")

        # Test joining with an absolute path
        test("/bar", "foo", "/bar")

        # Test joining to a path with a trailing slash
        test("foo/bar", "foo/", "bar")

        # Invalid joinings
        # Cannot go above root
        self.assertRaises(urlutils.InvalidURLJoin, urlutils.joinpath, "/", "../baz")
        self.assertRaises(urlutils.InvalidURLJoin, urlutils.joinpath, "/", "..")
        self.assertRaises(urlutils.InvalidURLJoin, urlutils.joinpath, "/", "/..")

    def test_join_segment_parameters_raw(self):
        join_segment_parameters_raw = urlutils.join_segment_parameters_raw
        self.assertEqual("/somedir/path", join_segment_parameters_raw("/somedir/path"))
        self.assertEqual(
            "/somedir/path,rawdata",
            join_segment_parameters_raw("/somedir/path", "rawdata"),
        )
        self.assertRaises(
            urlutils.InvalidURLJoin,
            join_segment_parameters_raw,
            "/somedir/path",
            "rawdata1,rawdata2,rawdata3",
        )
        self.assertEqual(
            "/somedir/path,bla,bar",
            join_segment_parameters_raw("/somedir/path", "bla", "bar"),
        )
        self.assertEqual(
            "/somedir,exist=some/path,bla,bar",
            join_segment_parameters_raw("/somedir,exist=some/path", "bla", "bar"),
        )
        self.assertRaises(TypeError, join_segment_parameters_raw, "/somepath", 42)

    def test_join_segment_parameters(self):
        join_segment_parameters = urlutils.join_segment_parameters
        self.assertEqual("/somedir/path", join_segment_parameters("/somedir/path", {}))
        self.assertEqual(
            "/somedir/path,key1=val1",
            join_segment_parameters("/somedir/path", {"key1": "val1"}),
        )
        self.assertRaises(
            urlutils.InvalidURLJoin,
            join_segment_parameters,
            "/somedir/path",
            {"branch": "brr,brr,brr"},
        )
        self.assertRaises(
            urlutils.InvalidURLJoin,
            join_segment_parameters,
            "/somedir/path",
            {"key1=val1": "val2"},
        )
        self.assertEqual(
            "/somedir/path,key1=val1,key2=val2",
            join_segment_parameters("/somedir/path", {"key1": "val1", "key2": "val2"}),
        )
        self.assertEqual(
            "/somedir/path,key1=val1,key2=val2",
            join_segment_parameters("/somedir/path,key1=val1", {"key2": "val2"}),
        )
        self.assertEqual(
            "/somedir/path,key1=val2",
            join_segment_parameters("/somedir/path,key1=val1", {"key1": "val2"}),
        )
        self.assertEqual(
            "/somedir,exist=some/path,key1=val1",
            join_segment_parameters("/somedir,exist=some/path", {"key1": "val1"}),
        )
        self.assertEqual(
            "/,key1=val1,key2=val2",
            join_segment_parameters("/,key1=val1", {"key2": "val2"}),
        )
        self.assertRaises(
            TypeError, join_segment_parameters, "/,key1=val1", {"foo": 42}
        )

    def test_function_type(self):
        if sys.platform == "win32":
            self.assertEqual(
                urlutils._win32_local_path_to_url, urlutils.local_path_to_url
            )
            self.assertEqual(
                urlutils._win32_local_path_from_url, urlutils.local_path_from_url
            )
        else:
            self.assertEqual(
                urlutils._posix_local_path_to_url, urlutils.local_path_to_url
            )
            self.assertEqual(
                urlutils._posix_local_path_from_url, urlutils.local_path_from_url
            )

    def test_posix_local_path_to_url(self):
        to_url = urlutils._posix_local_path_to_url
        self.assertEqual("file:///path/to/foo", to_url("/path/to/foo"))

        self.assertEqual("file:///path/to/foo%2Cbar", to_url("/path/to/foo,bar"))

        try:
            result = to_url("/path/to/r\xe4ksm\xf6rg\xe5s")
        except UnicodeError:
            raise TestSkipped("local encoding cannot handle unicode")

        self.assertEqual("file:///path/to/r%C3%A4ksm%C3%B6rg%C3%A5s", result)
        self.assertTrue(isinstance(result, str))

    def test_posix_local_path_from_url(self):
        from_url = urlutils._posix_local_path_from_url
        self.assertEqual("/path/to/foo", from_url("file:///path/to/foo"))
        self.assertEqual("/path/to/foo", from_url("file:///path/to/foo,branch=foo"))
        self.assertEqual(
            "/path/to/r\xe4ksm\xf6rg\xe5s",
            from_url("file:///path/to/r%C3%A4ksm%C3%B6rg%C3%A5s"),
        )
        self.assertEqual(
            "/path/to/r\xe4ksm\xf6rg\xe5s",
            from_url("file:///path/to/r%c3%a4ksm%c3%b6rg%c3%a5s"),
        )
        self.assertEqual(
            "/path/to/r\xe4ksm\xf6rg\xe5s",
            from_url("file://localhost/path/to/r%c3%a4ksm%c3%b6rg%c3%a5s"),
        )

        self.assertRaises(urlutils.InvalidURL, from_url, "/path/to/foo")
        self.assertRaises(
            urlutils.InvalidURL,
            from_url,
            "file://remotehost/path/to/r%c3%a4ksm%c3%b6rg%c3%a5s",
        )

    def test_win32_local_path_to_url(self):
        to_url = urlutils._win32_local_path_to_url
        self.assertEqual("file:///C:/path/to/foo", to_url("C:/path/to/foo"))
        # BOGUS: on win32, ntpath.abspath will strip trailing
        #       whitespace, so this will always fail
        #       Though under linux, it fakes abspath support
        #       and thus will succeed
        # self.assertEqual('file:///C:/path/to/foo%20',
        #     to_url('C:/path/to/foo '))
        self.assertEqual("file:///C:/path/to/f%20oo", to_url("C:/path/to/f oo"))

        self.assertEqual("file:///", to_url("/"))

        self.assertEqual("file:///C:/path/to/foo%2Cbar", to_url("C:/path/to/foo,bar"))
        try:
            result = to_url("d:/path/to/r\xe4ksm\xf6rg\xe5s")
        except UnicodeError:
            raise TestSkipped("local encoding cannot handle unicode")

        self.assertEqual("file:///D:/path/to/r%C3%A4ksm%C3%B6rg%C3%A5s", result)
        self.assertIsInstance(result, str)

    def test_win32_unc_path_to_url(self):
        self.requireFeature(features.win32_feature)
        to_url = urlutils._win32_local_path_to_url
        self.assertEqual("file://HOST/path", to_url(r"\\HOST\path"))
        self.assertEqual("file://HOST/path", to_url("//HOST/path"))

        try:
            result = to_url("//HOST/path/to/r\xe4ksm\xf6rg\xe5s")
        except UnicodeError:
            raise TestSkipped("local encoding cannot handle unicode")

        self.assertEqual("file://HOST/path/to/r%C3%A4ksm%C3%B6rg%C3%A5s", result)
        self.assertFalse(isinstance(result, str))

    def test_win32_local_path_from_url(self):
        from_url = urlutils._win32_local_path_from_url
        self.assertEqual("C:/path/to/foo", from_url("file:///C|/path/to/foo"))
        self.assertEqual(
            "D:/path/to/r\xe4ksm\xf6rg\xe5s",
            from_url("file:///d|/path/to/r%C3%A4ksm%C3%B6rg%C3%A5s"),
        )
        self.assertEqual(
            "D:/path/to/r\xe4ksm\xf6rg\xe5s",
            from_url("file:///d:/path/to/r%c3%a4ksm%c3%b6rg%c3%a5s"),
        )
        self.assertEqual("/", from_url("file:///"))
        self.assertEqual(
            "C:/path/to/foo", from_url("file:///C|/path/to/foo,branch=foo")
        )

        self.assertRaises(urlutils.InvalidURL, from_url, "file:///C:")
        self.assertRaises(urlutils.InvalidURL, from_url, "file:///c")
        self.assertRaises(urlutils.InvalidURL, from_url, "/path/to/foo")
        # Not a valid _win32 url, no drive letter
        self.assertRaises(urlutils.InvalidURL, from_url, "file:///path/to/foo")

    def test_win32_unc_path_from_url(self):
        from_url = urlutils._win32_local_path_from_url
        self.assertEqual("//HOST/path", from_url("file://HOST/path"))
        self.assertEqual("//HOST/path", from_url("file://HOST/path,branch=foo"))
        # despite IE allows 2, 4, 5 and 6 slashes in URL to another machine
        # we want to use only 2 slashes
        # Firefox understand only 5 slashes in URL, but it's ugly
        self.assertRaises(urlutils.InvalidURL, from_url, "file:////HOST/path")
        self.assertRaises(urlutils.InvalidURL, from_url, "file://///HOST/path")
        self.assertRaises(urlutils.InvalidURL, from_url, "file://////HOST/path")
        # check for file://C:/ instead of file:///C:/
        self.assertRaises(urlutils.InvalidURL, from_url, "file://C:/path")

    def test_win32_extract_drive_letter(self):
        extract = urlutils._win32_extract_drive_letter
        self.assertEqual(("file:///C:", "/foo"), extract("file://", "/C:/foo"))
        self.assertEqual(("file:///d|", "/path"), extract("file://", "/d|/path"))
        self.assertRaises(urlutils.InvalidURL, extract, "file://", "/path")
        # Root drives without slash treated as invalid, see bug #841322
        self.assertEqual(("file:///C:", "/"), extract("file://", "/C:/"))
        self.assertRaises(urlutils.InvalidURL, extract, "file://", "/C:")
        # Invalid without drive separator or following forward slash
        self.assertRaises(urlutils.InvalidURL, extract, "file://", "/C")
        self.assertRaises(urlutils.InvalidURL, extract, "file://", "/C:ool")

    def test_split(self):
        # Test breezy.urlutils.split()
        split = urlutils.split
        if sys.platform == "win32":
            self.assertRaises(urlutils.InvalidURL, split, "file:///path/to/foo")
            self.assertEqual(("file:///C|/", "foo"), split("file:///C|/foo"))
            self.assertEqual(("file:///C:/", ""), split("file:///C:/"))
        else:
            self.assertEqual(("file:///", "foo"), split("file:///foo"))
            self.assertEqual(("file:///", ""), split("file:///"))

        self.assertEqual(
            ("http://host/path/to", "foo"), split("http://host/path/to/foo")
        )
        self.assertEqual(
            ("http://host/path/to", "foo"), split("http://host/path/to/foo/")
        )
        self.assertEqual(
            ("http://host/path/to/foo", ""),
            split("http://host/path/to/foo/", exclude_trailing_slash=False),
        )
        self.assertEqual(("http://host/", "path"), split("http://host/path"))
        self.assertEqual(("http://host/", ""), split("http://host/"))
        self.assertEqual(("http://host", ""), split("http://host"))
        self.assertEqual(("http:///nohost", "path"), split("http:///nohost/path"))

        self.assertEqual(
            ("random+scheme://user:pass@ahost:port/", "path"),
            split("random+scheme://user:pass@ahost:port/path"),
        )
        self.assertEqual(
            ("random+scheme://user:pass@ahost:port/", "path"),
            split("random+scheme://user:pass@ahost:port/path/"),
        )
        self.assertEqual(
            ("random+scheme://user:pass@ahost:port/", ""),
            split("random+scheme://user:pass@ahost:port/"),
        )

        # relative paths
        self.assertEqual(("path/to", "foo"), split("path/to/foo"))
        self.assertEqual(("path/to", "foo"), split("path/to/foo/"))
        self.assertEqual(
            ("path/to/foo", ""), split("path/to/foo/", exclude_trailing_slash=False)
        )
        self.assertEqual(("path/..", "foo"), split("path/../foo"))
        self.assertEqual(("../path", "foo"), split("../path/foo"))

    def test_strip_segment_parameters(self):
        strip_segment_parameters = urlutils.strip_segment_parameters
        # Check relative references with absolute paths
        self.assertEqual("/some/path", strip_segment_parameters("/some/path"))
        self.assertEqual("/some/path", strip_segment_parameters("/some/path,tip"))
        self.assertEqual(
            "/some,dir/path", strip_segment_parameters("/some,dir/path,tip")
        )
        self.assertEqual(
            "/somedir/path", strip_segment_parameters("/somedir/path,heads%2Ftip")
        )
        self.assertEqual(
            "/somedir/path", strip_segment_parameters("/somedir/path,heads%2Ftip,bar")
        )
        # Check relative references with relative paths
        self.assertEqual("", strip_segment_parameters(",key1=val1"))
        self.assertEqual("foo/", strip_segment_parameters("foo/,key1=val1"))
        self.assertEqual("foo", strip_segment_parameters("foo,key1=val1"))
        self.assertEqual(
            "foo/base,la=bla/other/elements",
            strip_segment_parameters("foo/base,la=bla/other/elements"),
        )
        self.assertEqual(
            "foo/base,la=bla/other/elements",
            strip_segment_parameters("foo/base,la=bla/other/elements,a=b"),
        )
        # TODO: Check full URLs as well as relative references

    def test_split_segment_parameters_raw(self):
        split_segment_parameters_raw = urlutils.split_segment_parameters_raw
        # Check relative references with absolute paths
        self.assertEqual(("/some/path", []), split_segment_parameters_raw("/some/path"))
        self.assertEqual(
            ("/some/path", ["tip"]), split_segment_parameters_raw("/some/path,tip")
        )
        self.assertEqual(
            ("/some,dir/path", ["tip"]),
            split_segment_parameters_raw("/some,dir/path,tip"),
        )
        self.assertEqual(
            ("/somedir/path", ["heads%2Ftip"]),
            split_segment_parameters_raw("/somedir/path,heads%2Ftip"),
        )
        self.assertEqual(
            ("/somedir/path", ["heads%2Ftip", "bar"]),
            split_segment_parameters_raw("/somedir/path,heads%2Ftip,bar"),
        )
        # Check relative references with relative paths
        self.assertEqual(
            ("", ["key1=val1"]), split_segment_parameters_raw(",key1=val1")
        )
        self.assertEqual(
            ("foo/", ["key1=val1"]), split_segment_parameters_raw("foo/,key1=val1")
        )
        self.assertEqual(
            ("foo", ["key1=val1"]), split_segment_parameters_raw("foo,key1=val1")
        )
        self.assertEqual(
            ("foo/base,la=bla/other/elements", []),
            split_segment_parameters_raw("foo/base,la=bla/other/elements"),
        )
        self.assertEqual(
            ("foo/base,la=bla/other/elements", ["a=b"]),
            split_segment_parameters_raw("foo/base,la=bla/other/elements,a=b"),
        )
        # TODO: Check full URLs as well as relative references

    def test_split_segment_parameters(self):
        split_segment_parameters = urlutils.split_segment_parameters
        # Check relative references with absolute paths
        self.assertEqual(("/some/path", {}), split_segment_parameters("/some/path"))
        self.assertEqual(
            ("/some/path", {"branch": "tip"}),
            split_segment_parameters("/some/path,branch=tip"),
        )
        self.assertEqual(
            ("/some,dir/path", {"branch": "tip"}),
            split_segment_parameters("/some,dir/path,branch=tip"),
        )
        self.assertEqual(
            ("/somedir/path", {"ref": "heads%2Ftip"}),
            split_segment_parameters("/somedir/path,ref=heads%2Ftip"),
        )
        self.assertEqual(
            ("/somedir/path", {"ref": "heads%2Ftip", "key1": "val1"}),
            split_segment_parameters("/somedir/path,ref=heads%2Ftip,key1=val1"),
        )
        self.assertEqual(
            ("/somedir/path", {"ref": "heads%2F=tip"}),
            split_segment_parameters("/somedir/path,ref=heads%2F=tip"),
        )
        # Check relative references with relative paths
        self.assertEqual(("", {"key1": "val1"}), split_segment_parameters(",key1=val1"))
        self.assertEqual(
            ("foo/", {"key1": "val1"}), split_segment_parameters("foo/,key1=val1")
        )
        self.assertEqual(
            ("foo/base,key1=val1/other/elements", {}),
            split_segment_parameters("foo/base,key1=val1/other/elements"),
        )
        self.assertEqual(
            ("foo/base,key1=val1/other/elements", {"key2": "val2"}),
            split_segment_parameters("foo/base,key1=val1/other/elements,key2=val2"),
        )
        self.assertRaises(
            urlutils.InvalidURL, split_segment_parameters, "foo/base,key1"
        )
        # TODO: Check full URLs as well as relative references

    def test_win32_strip_local_trailing_slash(self):
        strip = urlutils._win32_strip_local_trailing_slash
        self.assertEqual("file://", strip("file://"))
        self.assertEqual("file:///", strip("file:///"))
        self.assertEqual("file:///C", strip("file:///C"))
        self.assertEqual("file:///C:", strip("file:///C:"))
        self.assertEqual("file:///d|", strip("file:///d|"))
        self.assertEqual("file:///C:/", strip("file:///C:/"))
        self.assertEqual("file:///C:/a", strip("file:///C:/a/"))

    def test_strip_trailing_slash(self):
        sts = urlutils.strip_trailing_slash
        if sys.platform == "win32":
            self.assertEqual("file:///C|/", sts("file:///C|/"))
            self.assertEqual("file:///C:/foo", sts("file:///C:/foo"))
            self.assertEqual("file:///C|/foo", sts("file:///C|/foo/"))
        else:
            self.assertEqual("file:///", sts("file:///"))
            self.assertEqual("file:///foo", sts("file:///foo"))
            self.assertEqual("file:///foo", sts("file:///foo/"))

        self.assertEqual("http://host/", sts("http://host/"))
        self.assertEqual("http://host/foo", sts("http://host/foo"))
        self.assertEqual("http://host/foo", sts("http://host/foo/"))

        # No need to fail just because the slash is missing
        self.assertEqual("http://host", sts("http://host"))
        # TODO: jam 20060502 Should this raise InvalidURL?
        self.assertEqual("file://", sts("file://"))

        self.assertEqual(
            "random+scheme://user:pass@ahost:port/path",
            sts("random+scheme://user:pass@ahost:port/path"),
        )
        self.assertEqual(
            "random+scheme://user:pass@ahost:port/path",
            sts("random+scheme://user:pass@ahost:port/path/"),
        )
        self.assertEqual(
            "random+scheme://user:pass@ahost:port/",
            sts("random+scheme://user:pass@ahost:port/"),
        )

        # Make sure relative paths work too
        self.assertEqual("path/to/foo", sts("path/to/foo"))
        self.assertEqual("path/to/foo", sts("path/to/foo/"))
        self.assertEqual("../to/foo", sts("../to/foo/"))
        self.assertEqual("path/../foo", sts("path/../foo/"))

    def test_unescape_for_display_utf8(self):
        # Test that URLs are converted to nice unicode strings for display
        def test(expected, url, encoding="utf-8"):
            disp_url = urlutils.unescape_for_display(url, encoding=encoding)
            self.assertIsInstance(disp_url, str)
            self.assertEqual(expected, disp_url)

        test("http://foo", "http://foo")
        if sys.platform == "win32":
            test("C:/foo/path", "file:///C|/foo/path")
            test("C:/foo/path", "file:///C:/foo/path")
        else:
            test("/foo/path", "file:///foo/path")

        test("http://foo/%2Fbaz", "http://foo/%2Fbaz")
        test("http://host/r\xe4ksm\xf6rg\xe5s", "http://host/r%C3%A4ksm%C3%B6rg%C3%A5s")

        # Make sure special escaped characters stay escaped
        test(
            "http://host/%3B%2F%3F%3A%40%26%3D%2B%24%2C%23",
            "http://host/%3B%2F%3F%3A%40%26%3D%2B%24%2C%23",
        )

        # Can we handle sections that don't have utf-8 encoding?
        test(
            "http://host/%EE%EE%EE/r\xe4ksm\xf6rg\xe5s",
            "http://host/%EE%EE%EE/r%C3%A4ksm%C3%B6rg%C3%A5s",
        )

        # Test encoding into output that can handle some characters
        test(
            "http://host/%EE%EE%EE/r\xe4ksm\xf6rg\xe5s",
            "http://host/%EE%EE%EE/r%C3%A4ksm%C3%B6rg%C3%A5s",
            encoding="iso-8859-1",
        )

        # This one can be encoded into utf8
        test(
            "http://host/\u062c\u0648\u062c\u0648",
            "http://host/%d8%ac%d9%88%d8%ac%d9%88",
            encoding="utf-8",
        )

        # This can't be put into 8859-1 and so stays as escapes
        test(
            "http://host/%d8%ac%d9%88%d8%ac%d9%88",
            "http://host/%d8%ac%d9%88%d8%ac%d9%88",
            encoding="iso-8859-1",
        )

    def test_escape(self):
        self.assertEqual("%25", urlutils.escape("%"))
        self.assertEqual("%C3%A5", urlutils.escape("\xe5"))
        self.assertIsInstance(urlutils.escape("\xe5"), str)

    def test_escape_tildes(self):
        self.assertEqual("~foo", urlutils.escape("~foo"))

    def test_unescape(self):
        self.assertEqual("%", urlutils.unescape("%25"))
        self.assertEqual("\xe5", urlutils.unescape("%C3%A5"))

        self.assertEqual("\xe5", urlutils.unescape("%C3%A5"))

    def test_escape_unescape(self):
        self.assertEqual("\xe5", urlutils.unescape(urlutils.escape("\xe5")))
        self.assertEqual("%", urlutils.unescape(urlutils.escape("%")))

    def test_relative_url(self):
        def test(expected, base, other):
            result = urlutils.relative_url(base, other)
            self.assertEqual(expected, result)

        test("a", "http://host/", "http://host/a")
        test(
            "http://entirely/different",
            "sftp://host/branch",
            "http://entirely/different",
        )
        test(
            "../person/feature",
            "http://host/branch/mainline",
            "http://host/branch/person/feature",
        )
        test("..", "http://host/branch", "http://host/")
        test("http://host2/branch", "http://host1/branch", "http://host2/branch")
        test(".", "http://host1/branch", "http://host1/branch")
        test(
            "../../../branch/2b",
            "file:///home/jelmer/foo/bar/2b",
            "file:///home/jelmer/branch/2b",
        )
        test(
            "../../branch/2b",
            "sftp://host/home/jelmer/bar/2b",
            "sftp://host/home/jelmer/branch/2b",
        )
        test(
            "../../branch/feature/%2b",
            "http://host/home/jelmer/bar/%2b",
            "http://host/home/jelmer/branch/feature/%2b",
        )
        test(
            "../../branch/feature/2b",
            "http://host/home/jelmer/bar/2b/",
            "http://host/home/jelmer/branch/feature/2b",
        )
        # relative_url should preserve a trailing slash
        test(
            "../../branch/feature/2b/",
            "http://host/home/jelmer/bar/2b/",
            "http://host/home/jelmer/branch/feature/2b/",
        )
        test(
            "../../branch/feature/2b/",
            "http://host/home/jelmer/bar/2b",
            "http://host/home/jelmer/branch/feature/2b/",
        )

        # TODO: treat http://host as http://host/
        #       relative_url is typically called from a branch.base or
        #       transport.base which always ends with a /
        # test('a', 'http://host', 'http://host/a')
        test("http://host/a", "http://host", "http://host/a")
        # test('.', 'http://host', 'http://host/')
        test("http://host/", "http://host", "http://host/")
        # test('.', 'http://host/', 'http://host')
        test("http://host", "http://host/", "http://host")

        # On Windows file:///C:/path/to and file:///D:/other/path
        # should not use relative url over the non-existent '/' directory.
        if sys.platform == "win32":
            # on the same drive
            test("../../other/path", "file:///C:/path/to", "file:///C:/other/path")
            # ~next two tests is failed, i.e. urlutils.relative_url expects
            # ~to see normalized file URLs?
            # ~test('../../other/path',
            # ~    'file:///C:/path/to', 'file:///c:/other/path')
            # ~test('../../other/path',
            # ~    'file:///C:/path/to', 'file:///C|/other/path')

            # check UNC paths too
            test(
                "../../other/path",
                "file://HOST/base/path/to",
                "file://HOST/base/other/path",
            )
            # on different drives
            test("file:///D:/other/path", "file:///C:/path/to", "file:///D:/other/path")
            # TODO: strictly saying in UNC path //HOST/base is full analog
            # of drive letter for hard disk, and this situation is also
            # should be exception from rules. [bialix 20071221]


class TestCwdToURL(TestCaseInTempDir):
    """Test that local_path_to_url works based on the cwd."""

    def test_dot(self):
        # This test will fail if getcwd is not ascii
        os.mkdir("mytest")
        os.chdir("mytest")

        url = urlutils.local_path_to_url(".")
        self.assertEndsWith(url, "/mytest")

    def test_non_ascii(self):
        try:
            os.mkdir("dod\xe9")
        except UnicodeError:
            raise TestSkipped("cannot create unicode directory")

        os.chdir("dod\xe9")

        # On Mac OSX this directory is actually:
        #   u'/dode\u0301' => '/dode\xcc\x81
        # but we should normalize it back to
        #   u'/dod\xe9' => '/dod\xc3\xa9'
        url = urlutils.local_path_to_url(".")
        self.assertEndsWith(url, "/dod%C3%A9")


class TestDeriveToLocation(TestCase):
    """Test that the mapping of FROM_LOCATION to TO_LOCATION works."""

    def test_to_locations_derived_from_paths(self):
        derive = urlutils.derive_to_location
        self.assertEqual("bar", derive("bar"))
        self.assertEqual("bar", derive("../bar"))
        self.assertEqual("bar", derive("/foo/bar"))
        self.assertEqual("bar", derive("c:/foo/bar"))
        self.assertEqual("bar", derive("c:bar"))

    def test_to_locations_derived_from_urls(self):
        derive = urlutils.derive_to_location
        self.assertEqual("bar", derive("http://foo/bar"))
        self.assertEqual("bar", derive("bzr+ssh://foo/bar"))
        self.assertEqual("foo-bar", derive("lp:foo-bar"))


class TestRebaseURL(TestCase):
    """Test the behavior of rebase_url."""

    def test_non_relative(self):
        result = urlutils.rebase_url("file://foo", "file://foo", "file://foo/bar")
        self.assertEqual("file://foo", result)
        result = urlutils.rebase_url("/foo", "file://foo", "file://foo/bar")
        self.assertEqual("/foo", result)

    def test_different_ports(self):
        e = self.assertRaises(
            urlutils.InvalidRebaseURLs,
            urlutils.rebase_url,
            "foo",
            "http://bar:80",
            "http://bar:81",
        )
        self.assertEqual(
            str(e),
            "URLs differ by more than path: 'http://bar:80' and 'http://bar:81'",
        )

    def test_different_hosts(self):
        e = self.assertRaises(
            urlutils.InvalidRebaseURLs,
            urlutils.rebase_url,
            "foo",
            "http://bar",
            "http://baz",
        )
        self.assertEqual(
            str(e), "URLs differ by more than path: 'http://bar' and 'http://baz'"
        )

    def test_different_protocol(self):
        e = self.assertRaises(
            urlutils.InvalidRebaseURLs,
            urlutils.rebase_url,
            "foo",
            "http://bar",
            "ftp://bar",
        )
        self.assertEqual(
            str(e), "URLs differ by more than path: 'http://bar' and 'ftp://bar'"
        )

    def test_rebase_success(self):
        self.assertEqual(
            "../bar", urlutils.rebase_url("bar", "http://baz/", "http://baz/qux")
        )
        self.assertEqual(
            "qux/bar", urlutils.rebase_url("bar", "http://baz/qux", "http://baz/")
        )
        self.assertEqual(
            ".", urlutils.rebase_url("foo", "http://bar/", "http://bar/foo/")
        )
        self.assertEqual(
            "qux/bar",
            urlutils.rebase_url("../bar", "http://baz/qux/foo", "http://baz/"),
        )

    def test_determine_relative_path(self):
        self.assertEqual(
            "../../baz/bar", urlutils.determine_relative_path("/qux/quxx", "/baz/bar")
        )
        self.assertEqual("..", urlutils.determine_relative_path("/bar/baz", "/bar"))
        self.assertEqual("baz", urlutils.determine_relative_path("/bar", "/bar/baz"))
        self.assertEqual(".", urlutils.determine_relative_path("/bar", "/bar"))


class TestParseURL(TestCase):
    def test_parse_simple(self):
        parsed = urlutils.parse_url("http://example.com:80/one")
        self.assertEqual(("http", None, None, "example.com", 80, "/one"), parsed)

    def test_ipv6(self):
        parsed = urlutils.parse_url("http://[1:2:3::40]/one")
        self.assertEqual(("http", None, None, "1:2:3::40", None, "/one"), parsed)

    def test_ipv6_port(self):
        parsed = urlutils.parse_url("http://[1:2:3::40]:80/one")
        self.assertEqual(("http", None, None, "1:2:3::40", 80, "/one"), parsed)


class TestURL(TestCase):
    def test_parse_simple(self):
        parsed = urlutils.URL.from_string("http://example.com:80/one")
        self.assertEqual("http", parsed.scheme)
        self.assertIs(None, parsed.user)
        self.assertIs(None, parsed.password)
        self.assertEqual("example.com", parsed.host)
        self.assertEqual(80, parsed.port)
        self.assertEqual("/one", parsed.path)

    def test_ipv6(self):
        parsed = urlutils.URL.from_string("http://[1:2:3::40]/one")
        self.assertEqual("http", parsed.scheme)
        self.assertIs(None, parsed.port)
        self.assertIs(None, parsed.user)
        self.assertIs(None, parsed.password)
        self.assertEqual("1:2:3::40", parsed.host)
        self.assertEqual("/one", parsed.path)

    def test_ipv6_port(self):
        parsed = urlutils.URL.from_string("http://[1:2:3::40]:80/one")
        self.assertEqual("http", parsed.scheme)
        self.assertEqual("1:2:3::40", parsed.host)
        self.assertIs(None, parsed.user)
        self.assertIs(None, parsed.password)
        self.assertEqual(80, parsed.port)
        self.assertEqual("/one", parsed.path)

    def test_quoted(self):
        parsed = urlutils.URL.from_string(
            "http://ro%62ey:h%40t@ex%41mple.com:2222/path"
        )
        self.assertEqual(parsed.quoted_host, "ex%41mple.com")
        self.assertEqual(parsed.host, "exAmple.com")
        self.assertEqual(parsed.port, 2222)
        self.assertEqual(parsed.quoted_user, "ro%62ey")
        self.assertEqual(parsed.user, "robey")
        self.assertEqual(parsed.quoted_password, "h%40t")
        self.assertEqual(parsed.password, "h@t")
        self.assertEqual(parsed.path, "/path")

    def test_eq(self):
        parsed1 = urlutils.URL.from_string("http://[1:2:3::40]:80/one")
        parsed2 = urlutils.URL.from_string("http://[1:2:3::40]:80/one")
        self.assertEqual(parsed1, parsed2)
        self.assertEqual(parsed1, parsed1)
        parsed2.path = "/two"
        self.assertNotEqual(parsed1, parsed2)

    def test_repr(self):
        parsed = urlutils.URL.from_string("http://[1:2:3::40]:80/one")
        self.assertEqual(
            "<URL('http', None, None, '1:2:3::40', 80, '/one')>", repr(parsed)
        )

    def test_str(self):
        parsed = urlutils.URL.from_string("http://[1:2:3::40]:80/one")
        self.assertEqual("http://[1:2:3::40]:80/one", str(parsed))

    def test__combine_paths(self):
        combine = urlutils.URL._combine_paths
        self.assertEqual(
            "/home/sarah/project/foo", combine("/home/sarah", "project/foo")
        )
        self.assertEqual("/etc", combine("/home/sarah", "../../etc"))
        self.assertEqual("/etc", combine("/home/sarah", "../../../etc"))
        self.assertEqual("/etc", combine("/home/sarah", "/etc"))

    def test_clone(self):
        url = urlutils.URL.from_string("http://[1:2:3::40]:80/one")
        url1 = url.clone("two")
        self.assertEqual("/one/two", url1.path)
        url2 = url.clone("/two")
        self.assertEqual("/two", url2.path)
        url3 = url.clone()
        self.assertIsNot(url, url3)
        self.assertEqual(url, url3)

    def test_parse_empty_port(self):
        parsed = urlutils.URL.from_string("http://example.com:/one")
        self.assertEqual("http", parsed.scheme)
        self.assertIs(None, parsed.user)
        self.assertIs(None, parsed.password)
        self.assertEqual("example.com", parsed.host)
        self.assertIs(None, parsed.port)
        self.assertEqual("/one", parsed.path)


class TestFileRelpath(TestCase):
    # GZ 2011-11-18: A way to override all path handling functions to one
    #                platform or another for testing would be nice.

    def _with_posix_paths(self):
        self.overrideAttr(
            urlutils, "local_path_from_url", urlutils._posix_local_path_from_url
        )
        self.overrideAttr(urlutils, "MIN_ABS_FILEURL_LENGTH", len("file:///"))
        self.overrideAttr(osutils, "normpath", osutils._posix_normpath)
        self.overrideAttr(osutils, "abspath", osutils.posixpath.abspath)
        self.overrideAttr(osutils, "normpath", osutils._posix_normpath)
        self.overrideAttr(osutils, "pathjoin", osutils.posixpath.join)
        self.overrideAttr(osutils, "split", osutils.posixpath.split)
        self.overrideAttr(osutils, "MIN_ABS_PATHLENGTH", 1)

    def _with_win32_paths(self):
        self.overrideAttr(
            urlutils, "local_path_from_url", urlutils._win32_local_path_from_url
        )
        self.overrideAttr(
            urlutils, "MIN_ABS_FILEURL_LENGTH", urlutils.WIN32_MIN_ABS_FILEURL_LENGTH
        )
        self.overrideAttr(osutils, "abspath", osutils._win32_abspath)
        self.overrideAttr(osutils, "normpath", osutils._win32_normpath)
        self.overrideAttr(osutils, "pathjoin", osutils._win32_pathjoin)
        self.overrideAttr(osutils, "split", osutils.ntpath.split)
        self.overrideAttr(osutils, "MIN_ABS_PATHLENGTH", 3)

    def test_same_url_posix(self):
        self._with_posix_paths()
        self.assertEqual("", urlutils.file_relpath("file:///a", "file:///a"))
        self.assertEqual("", urlutils.file_relpath("file:///a", "file:///a/"))
        self.assertEqual("", urlutils.file_relpath("file:///a/", "file:///a"))

    def test_same_url_win32(self):
        self._with_win32_paths()
        self.assertEqual("", urlutils.file_relpath("file:///A:/", "file:///A:/"))
        self.assertEqual("", urlutils.file_relpath("file:///A|/", "file:///A:/"))
        self.assertEqual("", urlutils.file_relpath("file:///A:/b/", "file:///A:/b/"))
        self.assertEqual("", urlutils.file_relpath("file:///A:/b", "file:///A:/b/"))
        self.assertEqual("", urlutils.file_relpath("file:///A:/b/", "file:///A:/b"))

    def test_child_posix(self):
        self._with_posix_paths()
        self.assertEqual("b", urlutils.file_relpath("file:///a", "file:///a/b"))
        self.assertEqual("b", urlutils.file_relpath("file:///a/", "file:///a/b"))
        self.assertEqual("b/c", urlutils.file_relpath("file:///a", "file:///a/b/c"))

    def test_child_win32(self):
        self._with_win32_paths()
        self.assertEqual("b", urlutils.file_relpath("file:///A:/", "file:///A:/b"))
        self.assertEqual("b", urlutils.file_relpath("file:///A|/", "file:///A:/b"))
        self.assertEqual("c", urlutils.file_relpath("file:///A:/b", "file:///A:/b/c"))
        self.assertEqual("c", urlutils.file_relpath("file:///A:/b/", "file:///A:/b/c"))
        self.assertEqual(
            "c/d", urlutils.file_relpath("file:///A:/b", "file:///A:/b/c/d")
        )

    def test_sibling_posix(self):
        self._with_posix_paths()
        self.assertRaises(
            PathNotChild, urlutils.file_relpath, "file:///a/b", "file:///a/c"
        )
        self.assertRaises(
            PathNotChild, urlutils.file_relpath, "file:///a/b/", "file:///a/c"
        )
        self.assertRaises(
            PathNotChild, urlutils.file_relpath, "file:///a/b/", "file:///a/c/"
        )

    def test_sibling_win32(self):
        self._with_win32_paths()
        self.assertRaises(
            PathNotChild, urlutils.file_relpath, "file:///A:/b", "file:///A:/c"
        )
        self.assertRaises(
            PathNotChild, urlutils.file_relpath, "file:///A:/b/", "file:///A:/c"
        )
        self.assertRaises(
            PathNotChild, urlutils.file_relpath, "file:///A:/b/", "file:///A:/c/"
        )

    def test_parent_posix(self):
        self._with_posix_paths()
        self.assertRaises(
            PathNotChild, urlutils.file_relpath, "file:///a/b", "file:///a"
        )
        self.assertRaises(
            PathNotChild, urlutils.file_relpath, "file:///a/b", "file:///a/"
        )

    def test_parent_win32(self):
        self._with_win32_paths()
        self.assertRaises(
            PathNotChild, urlutils.file_relpath, "file:///A:/b", "file:///A:/"
        )
        self.assertRaises(
            PathNotChild, urlutils.file_relpath, "file:///A:/b/c", "file:///A:/b"
        )


class QuoteTests(TestCase):
    def test_quote(self):
        self.assertEqual("abc%20def", urlutils.quote("abc def"))
        self.assertEqual("abc%2Fdef", urlutils.quote("abc/def", safe=""))
        self.assertEqual("abc/def", urlutils.quote("abc/def", safe="/"))

    def test_quote_tildes(self):
        self.assertEqual("~foo", urlutils.quote("~foo"))
        self.assertEqual("~foo", urlutils.quote("~foo", safe="/~"))

    def test_unquote(self):
        self.assertEqual("%", urlutils.unquote("%25"))
        self.assertEqual("\xe5", urlutils.unquote("%C3%A5"))
        self.assertEqual("\xe5", urlutils.unquote("\xe5"))

    def test_unquote_to_bytes(self):
        self.assertEqual(b"%", urlutils.unquote_to_bytes("%25"))
        self.assertEqual(b"\xc3\xa5", urlutils.unquote_to_bytes("%C3%A5"))
