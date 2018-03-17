# Copyright (C) 2010-2018 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""Test the smart client."""

from __future__ import absolute_import

from ....errors import (
    BzrError,
    NotBranchError,
    )

from ....tests import TestCase

from ..remote import (
    split_git_url,
    parse_git_error,
    RemoteGitBranchFormat,
    )

class SplitUrlTests(TestCase):

    def test_simple(self):
        self.assertEquals(("foo", None, None, "/bar"),
            split_git_url("git://foo/bar"))

    def test_port(self):
        self.assertEquals(("foo", 343, None, "/bar"),
            split_git_url("git://foo:343/bar"))

    def test_username(self):
        self.assertEquals(("foo", None, "la", "/bar"),
            split_git_url("git://la@foo/bar"))

    def test_nopath(self):
        self.assertEquals(("foo", None, None, "/"),
            split_git_url("git://foo/"))

    def test_slashpath(self):
        self.assertEquals(("foo", None, None, "//bar"),
            split_git_url("git://foo//bar"))

    def test_homedir(self):
        self.assertEquals(("foo", None, None, "~bar"),
            split_git_url("git://foo/~bar"))


class ParseGitErrorTests(TestCase):

    def test_unknown(self):
        e = parse_git_error("url", "foo")
        self.assertIsInstance(e, BzrError)

    def test_notbrancherror(self):
        e = parse_git_error("url", "\n Could not find Repository foo/bar")
        self.assertIsInstance(e, NotBranchError)


class TestRemoteGitBranchFormat(TestCase):

    def setUp(self):
        super(TestRemoteGitBranchFormat, self).setUp()
        self.format = RemoteGitBranchFormat()

    def test_get_format_description(self):
        self.assertEquals("Remote Git Branch", self.format.get_format_description())

    def test_get_network_name(self):
        self.assertEquals("git", self.format.network_name())

    def test_supports_tags(self):
        self.assertTrue(self.format.supports_tags())
