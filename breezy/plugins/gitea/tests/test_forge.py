# Copyright (C) 2021 Jelmer Vernooij <jelmer@jelmer.uk>
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

from datetime import datetime

from breezy.tests import TestCase

from ..forge import (
    NotGiteaUrl,
    NotMergeRequestUrl,
    api_base_url,
    parse_gitea_merge_request_url,
    parse_gitea_url,
    parse_timestring,
)


class ParseGiteaUrlTests(TestCase):
    def test_simple(self):
        self.assertEqual(
            ("codeberg.org", "jelmer/example"),
            parse_gitea_url("https://codeberg.org/jelmer/example"),
        )

    def test_strip_git_suffix(self):
        self.assertEqual(
            ("codeberg.org", "jelmer/example"),
            parse_gitea_url("https://codeberg.org/jelmer/example.git"),
        )

    def test_invalid_scheme(self):
        self.assertRaises(NotGiteaUrl, parse_gitea_url, "bzr://codeberg.org/jelmer/x")

    def test_missing_host(self):
        self.assertRaises(NotGiteaUrl, parse_gitea_url, "https:///jelmer/x")


class ApiBaseUrlTests(TestCase):
    def test_https_default_port(self):
        self.assertEqual(
            "https://codeberg.org/",
            api_base_url("https://codeberg.org/jelmer/example"),
        )

    def test_http_keeps_scheme_and_port(self):
        self.assertEqual(
            "http://gitea.example.com:3000/",
            api_base_url("http://gitea.example.com:3000/jelmer/example"),
        )

    def test_https_keeps_non_default_port(self):
        self.assertEqual(
            "https://gitea.example.com:8443/",
            api_base_url("https://gitea.example.com:8443/jelmer/example"),
        )

    def test_explicit_default_port_dropped(self):
        # Otherwise the stored token, saved against the port-less URL, no
        # longer matches and probing fails where it used to succeed.
        self.assertEqual(
            "https://gitea.example.com/",
            api_base_url("https://gitea.example.com:443/jelmer/example"),
        )
        self.assertEqual(
            "http://gitea.example.com/",
            api_base_url("http://gitea.example.com:80/jelmer/example"),
        )

    def test_ssh_falls_back_to_https(self):
        # A git+ssh URL's port is an SSH port, not a web one.
        self.assertEqual(
            "https://gitea.example.com/",
            api_base_url("git+ssh://git@gitea.example.com:2222/jelmer/example"),
        )

    def test_credentials_are_dropped(self):
        self.assertEqual(
            "http://gitea.example.com:3000/",
            api_base_url("http://user:pw@gitea.example.com:3000/jelmer/example"),
        )

    def test_ipv6_host_is_bracketed(self):
        self.assertEqual(
            "http://[2001:db8::1]:3000/",
            api_base_url("http://[2001:db8::1]:3000/jelmer/example"),
        )


class ParseGiteaMergeRequestUrlTests(TestCase):
    def test_simple(self):
        self.assertEqual(
            ("codeberg.org", "jelmer/example", 4),
            parse_gitea_merge_request_url(
                "https://codeberg.org/jelmer/example/pulls/4"
            ),
        )

    def test_not_a_pull(self):
        self.assertRaises(
            NotMergeRequestUrl,
            parse_gitea_merge_request_url,
            "https://codeberg.org/jelmer/example",
        )

    def test_issue_is_not_a_pull(self):
        self.assertRaises(
            NotMergeRequestUrl,
            parse_gitea_merge_request_url,
            "https://codeberg.org/jelmer/example/issues/4",
        )

    def test_invalid_scheme(self):
        self.assertRaises(
            NotGiteaUrl,
            parse_gitea_merge_request_url,
            "bzr://codeberg.org/jelmer/example/pulls/4",
        )


class ParseTimestringTests(TestCase):
    def test_offset(self):
        self.assertEqual(
            datetime(2018, 9, 7, 11, 16, 17),
            parse_timestring("2018-09-07T11:16:17+02:00"),
        )

    def test_zulu(self):
        self.assertEqual(
            datetime(2018, 9, 7, 11, 16, 17),
            parse_timestring("2018-09-07T11:16:17Z"),
        )
