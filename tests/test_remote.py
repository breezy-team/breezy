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
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Test the smart client."""

from ....errors import (
    BzrError,
    NotBranchError,
    )

from ....tests import TestCase

from ..remote import (
    split_git_url,
    parse_git_error,
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
