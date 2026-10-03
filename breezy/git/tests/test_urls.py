# Copyright (C) 2018 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""Tests for url handling."""

from ...tests import TestCase
from ..urls import (
    git_url_to_bzr_url,
    join_ref_segment_parameter,
    ref_from_segment_parameters,
)


class TestConvertURL(TestCase):
    def test_simple(self):
        self.assertEqual(git_url_to_bzr_url("foo:bar/path"), "git+ssh://foo/bar/path")
        self.assertEqual(
            git_url_to_bzr_url("user@foo:bar/path"), ("git+ssh://user@foo/bar/path")
        )

    def test_regular(self):
        self.assertEqual(
            git_url_to_bzr_url("git+ssh://user@foo/bar/path"),
            ("git+ssh://user@foo/bar/path"),
        )

    def test_just_ssh(self):
        self.assertEqual(
            git_url_to_bzr_url("ssh://user@foo/bar/path"),
            ("git+ssh://user@foo/bar/path"),
        )

    def test_path(self):
        self.assertEqual(git_url_to_bzr_url("/bar/path"), ("/bar/path"))

    def test_with_ref(self):
        self.assertEqual(
            git_url_to_bzr_url("foo:bar/path", ref=b"HEAD"), "git+ssh://foo/bar/path"
        )
        self.assertEqual(
            git_url_to_bzr_url("foo:bar/path", ref=b"refs/heads/blah"),
            "git+ssh://foo/bar/path,branch=blah",
        )
        self.assertEqual(
            git_url_to_bzr_url("foo:bar/path", ref=b"refs/tags/blah"),
            "git+ssh://foo/bar/path,ref=refs%2Ftags%2Fblah",
        )
        self.assertEqual(
            git_url_to_bzr_url("foo:bar/path", ref=b"refs/heads/caf\xe9"),
            "git+ssh://foo/bar/path,ref=refs%2Fheads%2Fcaf%E9",
        )

    def test_with_branch(self):
        self.assertEqual(
            git_url_to_bzr_url("foo:bar/path", branch=""), "git+ssh://foo/bar/path"
        )
        self.assertEqual(
            git_url_to_bzr_url("foo:bar/path", branch="foo/blah"),
            "git+ssh://foo/bar/path,branch=foo%2Fblah",
        )
        self.assertEqual(
            git_url_to_bzr_url("foo:bar/path", branch="blah"),
            "git+ssh://foo/bar/path,branch=blah",
        )


class TestRefSegmentParameter(TestCase):
    def test_join(self):
        self.assertEqual(
            "git+ssh://foo/bar/path,ref=refs%2Ftags%2Fblah",
            join_ref_segment_parameter("git+ssh://foo/bar/path", b"refs/tags/blah"),
        )

    def test_join_existing(self):
        self.assertEqual(
            "git+ssh://foo/bar/path,branch=foo%2Fbar,ref=refs%2Ftags%2Fblah",
            join_ref_segment_parameter(
                "git+ssh://foo/bar/path,ref=HEAD,branch=foo%2Fbar", b"refs/tags/blah"
            ),
        )

    def test_missing(self):
        self.assertIsNone(ref_from_segment_parameters("git+ssh://foo/bar/path"))
        self.assertIsNone(
            ref_from_segment_parameters("git+ssh://foo/bar/path,branch=blah")
        )

    def test_roundtrip(self):
        for ref in [b"HEAD", b"refs/tags/blah", b"refs/heads/caf\xc3\xa9"]:
            url = join_ref_segment_parameter("git+ssh://foo/bar/path", ref)
            self.assertEqual(ref, ref_from_segment_parameters(url))

    def test_roundtrip_non_utf8(self):
        url = join_ref_segment_parameter(
            "git+ssh://foo/bar/path", b"refs/heads/caf\xe9"
        )
        self.assertEqual("git+ssh://foo/bar/path,ref=refs%2Fheads%2Fcaf%E9", url)
        self.assertEqual(b"refs/heads/caf\xe9", ref_from_segment_parameters(url))
