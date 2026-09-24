# Copyright (C) 2020 Jelmer Vernooij <jelmer@jelmer.uk>
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

from datetime import datetime

from breezy.tests import TestCase

from ..forge import (
    NotGitLabUrl,
    NotMergeRequestUrl,
    api_base_url,
    parse_gitlab_merge_request_url,
    parse_timestring,
)


class ApiBaseUrlTests(TestCase):
    def test_https_default_port(self):
        self.assertEqual(
            "https://gitlab.com/", api_base_url("https://gitlab.com/jelmer/x")
        )

    def test_http_keeps_scheme_and_port(self):
        self.assertEqual(
            "http://gitlab.example.com:8080/",
            api_base_url("http://gitlab.example.com:8080/jelmer/x"),
        )

    def test_https_keeps_non_default_port(self):
        self.assertEqual(
            "https://gitlab.example.com:8443/",
            api_base_url("https://gitlab.example.com:8443/jelmer/x"),
        )

    def test_explicit_default_port_dropped(self):
        self.assertEqual(
            "https://gitlab.example.com/",
            api_base_url("https://gitlab.example.com:443/jelmer/x"),
        )

    def test_ssh_falls_back_to_https(self):
        self.assertEqual(
            "https://gitlab.example.com/",
            api_base_url("git+ssh://git@gitlab.example.com:2222/jelmer/x"),
        )

    def test_ipv6_host_is_bracketed(self):
        self.assertEqual(
            "http://[2001:db8::1]:8080/",
            api_base_url("http://[2001:db8::1]:8080/jelmer/x"),
        )


class ParseGitLabMergeRequestUrlTests(TestCase):
    def test_invalid(self):
        self.assertRaises(
            NotMergeRequestUrl,
            parse_gitlab_merge_request_url,
            "https://salsa.debian.org/",
        )
        self.assertRaises(
            NotGitLabUrl, parse_gitlab_merge_request_url, "bzr://salsa.debian.org/"
        )
        self.assertRaises(
            NotGitLabUrl, parse_gitlab_merge_request_url, "https:///salsa.debian.org/"
        )
        self.assertRaises(
            NotMergeRequestUrl,
            parse_gitlab_merge_request_url,
            "https://salsa.debian.org/jelmer/salsa",
        )

    def test_old_style(self):
        self.assertEqual(
            ("salsa.debian.org", "jelmer/salsa", 4),
            parse_gitlab_merge_request_url(
                "https://salsa.debian.org/jelmer/salsa/merge_requests/4"
            ),
        )

    def test_new_style(self):
        self.assertEqual(
            ("salsa.debian.org", "jelmer/salsa", 4),
            parse_gitlab_merge_request_url(
                "https://salsa.debian.org/jelmer/salsa/-/merge_requests/4"
            ),
        )


class ParseTimestringTests(TestCase):
    def test_simple(self):
        self.assertEqual(
            datetime(2018, 9, 7, 11, 16, 17, 520000),
            parse_timestring("2018-09-07T11:16:17.520Z"),
        )
