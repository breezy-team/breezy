# Copyright (C) 2022 Jelmer Vernooij
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

"""Tests for GitHub."""

from datetime import datetime

from ....errors import UnexpectedHttpStatus
from ....tests import TestCase
from ..forge import GitHub, parse_timestring


class ParseTimestringTests(TestCase):
    def test_simple(self):
        self.assertEqual(
            datetime(2011, 1, 26, 19, 1, 12), parse_timestring("2011-01-26T19:01:12Z")
        )


class FakeResponse:
    def __init__(self, status):
        self.status = status

    def getheaders(self):
        return []


class FakeTransport:
    base = "https://api.github.com/"

    def __init__(self, status):
        self.status = status

    def request(self, method, url, headers=None, body=None, retries=0):
        return FakeResponse(self.status)


class UnexpectedStatusTests(TestCase):
    def test_full_url(self):
        gh = GitHub(FakeTransport(403))
        e = self.assertRaises(UnexpectedHttpStatus, gh._get_repo, "owner", "repo")
        self.assertEqual("https://api.github.com/repos/owner/repo", e.path)
        self.assertEqual(403, e.code)
