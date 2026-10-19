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

from ....config import AuthenticationConfig
from ....tests import TestCase, TestCaseInTempDir
from ..forge import parse_timestring


class ParseTimestringTests(TestCase):
    def test_simple(self):
        self.assertEqual(
            datetime(2011, 1, 26, 19, 1, 12), parse_timestring("2011-01-26T19:01:12Z")
        )


class GitHubLoginTests(TestCaseInTempDir):
    def test_stores_token(self):
        self.run_bzr("github-login", stdin="mytoken\n")
        self.assertEqual(
            {
                "scheme": "https",
                "url": "https://api.github.com",
                "host": "github.com",
                "token": "mytoken",
                "private_token": "mytoken",
            },
            dict(AuthenticationConfig()._get_config()["Github"]),
        )
