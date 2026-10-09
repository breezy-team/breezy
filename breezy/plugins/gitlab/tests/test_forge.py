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

from dromedary.errors import RedirectRequested

from breezy.forge import NoSuchProject
from breezy.tests import TestCase

from ..forge import (
    GitLab,
    NotGitLabUrl,
    NotMergeRequestUrl,
    parse_gitlab_merge_request_url,
    parse_timestring,
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


class FakeResponse:
    def __init__(self, status, data=b""):
        self.status = status
        self.data = data

    def getheaders(self):
        return {}


class FakeTransport:
    """Transport answering requests from a table of canned responses."""

    base = "https://gitlab.example.com/"

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def request(self, method, url, headers=None, fields=None, body=None):
        self.calls.append((method, url))
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response


class GetProjectTests(TestCase):
    def test_found(self):
        transport = FakeTransport(
            {
                "https://gitlab.example.com/api/v4/projects/foo%2Fbar": (
                    FakeResponse(200, b'{"path_with_namespace": "foo/bar"}')
                ),
            }
        )
        gl = GitLab(transport, "token")
        self.assertEqual(
            {"path_with_namespace": "foo/bar"},
            gl._get_project("foo/bar"),
        )

    def test_missing_without_redirect(self):
        transport = FakeTransport(
            {
                "https://gitlab.example.com/api/v4/projects/foo%2Fbar": (
                    FakeResponse(404)
                ),
                "https://gitlab.example.com/foo/bar": FakeResponse(200),
            }
        )
        gl = GitLab(transport, "token")
        e = self.assertRaises(NoSuchProject, gl._get_project, "foo/bar")
        self.assertEqual("foo/bar", e.project)
        self.assertEqual("Project does not exist: foo/bar.", str(e))

    def test_redirect_followed(self):
        transport = FakeTransport(
            {
                "https://gitlab.example.com/api/v4/projects/foo%2Fold": (
                    FakeResponse(404)
                ),
                "https://gitlab.example.com/foo/old": RedirectRequested(
                    "https://gitlab.example.com/foo/old",
                    "https://gitlab.example.com/foo/new",
                    is_permanent=True,
                ),
                "https://gitlab.example.com/api/v4/projects/foo%2Fnew": (
                    FakeResponse(200, b'{"path_with_namespace": "foo/new"}')
                ),
            }
        )
        gl = GitLab(transport, "token")
        self.assertEqual(
            {"path_with_namespace": "foo/new"}, gl._get_project("foo/old")
        )
        self.assertEqual(
            [
                ("GET", "https://gitlab.example.com/api/v4/projects/foo%2Fold"),
                ("GET", "https://gitlab.example.com/foo/old"),
                ("GET", "https://gitlab.example.com/api/v4/projects/foo%2Fnew"),
            ],
            transport.calls,
        )
