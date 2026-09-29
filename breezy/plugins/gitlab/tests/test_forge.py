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

import json
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

from dromedary import errors as transport_errors

from breezy.forge import UnsupportedForge
from breezy.tests import TestCase, TestCaseInTempDir

from ..forge import (
    GitLab,
    GitLabLoginMissing,
    NotGitLabUrl,
    NotMergeRequestUrl,
    parse_gitlab_merge_request_url,
    parse_timestring,
    store_gitlab_token,
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


class ForgeServer:
    """A loopback HTTP server that answers API requests from a table."""

    def __init__(self, responses):
        requests = self.requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(("GET", self.path, self.headers.get("Private-Token")))
                status, payload = responses.get(self.path, (404, {}))
                data = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("X-Gitlab-Feature-Category", "projects")
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, format, *args):
                pass

        self._httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, args=(0.01,))
        self.url = f"http://127.0.0.1:{self._httpd.server_port}/"

    def start(self):
        self._thread.start()

    def stop(self):
        self._httpd.shutdown()
        self._thread.join()
        self._httpd.server_close()


class RecordingTransport:
    """A transport for any URL that records each request and answers 404."""

    def __init__(self):
        self.requests = []

    def _reuse_for(self, other_base):
        self.base = other_base
        return self

    def request(self, method, url, **kwargs):
        self.requests.append((method, url))
        raise transport_errors.UnexpectedHttpStatus(url, 404)


class ProbeFromUrlTests(TestCaseInTempDir):
    def serve(self, responses):
        server = ForgeServer(responses)
        server.start()
        self.addCleanup(server.stop)
        return server

    def test_scheme_and_port_preserved(self):
        server = self.serve({"/api/v4/user": (200, {"username": "jelmer"})})
        store_gitlab_token("local", server.url, "sekrit")
        forge = GitLab.probe_from_url(server.url + "jelmer/example")
        self.assertEqual(server.url, forge.base_url)
        self.assertEqual([("GET", "/api/v4/user", "sekrit")], server.requests)

    def test_ssh_url_probed_over_https(self):
        transport = RecordingTransport()
        self.assertRaises(
            UnsupportedForge,
            GitLab.probe_from_url,
            "git+ssh://git@gitlab.example.com:2222/jelmer/example",
            possible_transports=[transport],
        )
        self.assertEqual(
            [("GET", "https://gitlab.example.com/api/v4/projects/jelmer%2Fexample")],
            transport.requests,
        )

    def test_api_request_uses_the_same_base(self):
        server = self.serve({})
        self.assertRaises(
            UnsupportedForge, GitLab.probe_from_url, server.url + "jelmer/example"
        )
        self.assertEqual(
            [("GET", "/api/v4/projects/jelmer%2Fexample", None)], server.requests
        )

    def test_login_missing_names_the_same_base(self):
        server = self.serve({"/api/v4/projects/jelmer%2Fexample": (401, {})})
        e = self.assertRaises(
            GitLabLoginMissing, GitLab.probe_from_url, server.url + "jelmer/example"
        )
        self.assertEqual(server.url, e.forge)
