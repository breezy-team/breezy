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

from breezy.config import GlobalStack
from breezy.errors import RedirectRequested, UnexpectedHttpStatus
from breezy.forge import NoSuchProject
from breezy.plugins.gitlab.forge import (
    GitLab,
    NotGitLabUrl,
    NotMergeRequestUrl,
    _https_url,
    get_credentials_by_url,
    parse_gitlab_merge_request_url,
    parse_timestring,
    store_gitlab_token,
)
from breezy.tests import TestCase, TestCaseInTempDir, features, http_server
from breezy.transport import get_transport


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

    def test_missing_numeric_id(self):
        # GitLab takes a numeric id too; breezy passes one in _get_project_name.
        transport = FakeTransport(
            {
                "https://gitlab.example.com/api/v4/projects/123": FakeResponse(404),
            }
        )
        gl = GitLab(transport, "token")
        e = self.assertRaises(NoSuchProject, gl._get_project, 123)
        self.assertEqual("123", e.project)
        self.assertEqual("Project does not exist: 123.", str(e))
        self.assertEqual(
            [("GET", "https://gitlab.example.com/api/v4/projects/123")],
            transport.calls,
        )

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
        self.assertEqual({"path_with_namespace": "foo/new"}, gl._get_project("foo/old"))
        self.assertEqual(
            [
                ("GET", "https://gitlab.example.com/api/v4/projects/foo%2Fold"),
                ("GET", "https://gitlab.example.com/foo/old"),
                ("GET", "https://gitlab.example.com/api/v4/projects/foo%2Fnew"),
            ],
            transport.calls,
        )


class DeleteProjectTests(TestCase):
    def test_missing_numeric_id(self):
        transport = FakeTransport(
            {
                "https://gitlab.example.com/api/v4/projects/123": FakeResponse(404),
            }
        )
        gl = GitLab(transport, "token")
        e = self.assertRaises(NoSuchProject, gl.delete_project, 123)
        self.assertEqual("123", e.project)


class UnexpectedStatusTests(TestCase):
    def _start_server(self, statuses):
        class RequestHandler(http_server.TestingHTTPRequestHandler):
            def do_GET(self):
                self.send_error(statuses[self.path])

        server = http_server.HttpServer(RequestHandler)
        self.start_server(server)
        return server.get_url()

    def test_full_url(self):
        url = self._start_server({"/api/v4/projects/foo%2Fbar": 403})
        gl = GitLab(get_transport(url), "token")
        e = self.assertRaises(UnexpectedHttpStatus, gl._get_project, "foo/bar")
        self.assertEqual(url + "api/v4/projects/foo%2Fbar", e.path)
        self.assertEqual(403, e.code)

    def test_full_url_on_redirect_check(self):
        url = self._start_server({"/api/v4/projects/foo%2Fbar": 404, "/foo/bar": 403})
        gl = GitLab(get_transport(url), "token")
        e = self.assertRaises(UnexpectedHttpStatus, gl._get_project, "foo/bar")
        self.assertEqual(url + "foo/bar", e.path)
        self.assertEqual(403, e.code)


class HttpsUrlTests(TestCaseInTempDir):
    def test_hostname(self):
        self.assertEqual("https://gitlab.com/", _https_url("gitlab.com"))

    def test_ipv4(self):
        self.assertEqual("https://127.0.0.1/", _https_url("127.0.0.1"))

    def test_host_port(self):
        self.assertEqual("https://127.0.0.1:8443/", _https_url("127.0.0.1:8443"))

    def test_ipv6(self):
        self.assertEqual("https://[::1]/", _https_url("::1"))

    def test_ipv6_port(self):
        self.assertEqual("https://[::1]:8443/", _https_url("::1", 8443))

    def test_ipv6_bracketed(self):
        self.assertEqual("https://[::1]/", _https_url("[::1]"))

    def test_ipv6_stored_login(self):
        store_gitlab_token("local", "https://[::1]", "token")
        credentials = get_credentials_by_url(_https_url("::1"))
        self.assertEqual("token", credentials["private_token"])


class ProbeFromUrlTests(TestCaseInTempDir):
    _test_needs_features = [features.HTTPSServerFeature]

    def test_https_port(self):
        from breezy.tests import https_server, ssl_certs

        class RequestHandler(http_server.TestingHTTPRequestHandler):
            def do_GET(self):
                body = b'{"username": "test"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = https_server.HTTPSServer(RequestHandler)
        self.start_server(server)
        url = server.get_url()
        GlobalStack().set("ssl.ca_certs", ssl_certs.build_path("ca.crt"))
        store_gitlab_token("local", url, "token")
        gl = GitLab.probe_from_url(url + "foo/bar.git")
        self.assertEqual(url, gl.base_url)
