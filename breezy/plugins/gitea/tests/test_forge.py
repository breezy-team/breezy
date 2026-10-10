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

import json
import os
from datetime import datetime

from dromedary import errors as transport_errors

from breezy import bedding
from breezy.forge import NoSuchProject, UnsupportedForge
from breezy.tests import TestCase, TestCaseInTempDir

from ..forge import (
    DEFAULT_PAGE_SIZE,
    Gitea,
    NotGiteaUrl,
    NotMergeRequestUrl,
    iter_tokens,
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


class FakeResponse:
    """A canned HTTP response."""

    def __init__(self, status, payload=None):
        self.status = status
        self.data = b"" if payload is None else json.dumps(payload).encode("utf-8")
        self.text = self.data.decode("utf-8")

    def getheaders(self):
        return {}


class FakeTransport:
    """A transport that answers API requests from a table of responses."""

    base = "https://gitea.example.com/"

    def __init__(self, responses):
        self.responses = responses
        self.requests = []

    def request(self, method, url, headers=None, fields=None, body=None):
        self.requests.append((method, url, headers["Authorization"]))
        return self.responses[(method, url[len(self.base + "api/v1/") :])]


def repo(full_name, fork):
    owner = full_name.split("/")[0]
    return {"full_name": full_name, "fork": fork, "owner": {"login": owner}}


USER = ("GET", "user")
ME = FakeResponse(200, {"login": "me"})


class IterMyForksTests(TestCase):
    def test_current_user(self):
        transport = FakeTransport(
            {
                USER: ME,
                ("GET", "user/repos?limit=50&page=1"): FakeResponse(
                    200,
                    [
                        repo("me/fork", True),
                        repo("me/own", False),
                        repo("other/fork", True),
                        repo("me/fork2", True),
                    ],
                ),
            }
        )
        gitea = Gitea(transport, "secret")
        self.assertEqual(["me/fork", "me/fork2"], list(gitea.iter_my_forks()))
        self.assertEqual(
            [
                ("GET", "https://gitea.example.com/api/v1/user", "token secret"),
                (
                    "GET",
                    "https://gitea.example.com/api/v1/user/repos?limit=50&page=1",
                    "token secret",
                ),
            ],
            transport.requests,
        )

    def test_owner(self):
        transport = FakeTransport(
            {
                ("GET", "users/other/repos?limit=50&page=1"): FakeResponse(
                    200, [repo("other/fork", True), repo("other/own", False)]
                ),
            }
        )
        gitea = Gitea(transport, "secret")
        self.assertEqual(["other/fork"], list(gitea.iter_my_forks(owner="other")))

    def test_owner_case(self):
        transport = FakeTransport(
            {
                ("GET", "users/Other/repos?limit=50&page=1"): FakeResponse(
                    200, [repo("other/fork", True)]
                ),
            }
        )
        gitea = Gitea(transport, "secret")
        self.assertEqual(["other/fork"], list(gitea.iter_my_forks(owner="Other")))

    def test_paged(self):
        first = [repo(f"me/fork{i}", True) for i in range(DEFAULT_PAGE_SIZE)]
        transport = FakeTransport(
            {
                USER: ME,
                ("GET", "user/repos?limit=50&page=1"): FakeResponse(200, first),
                ("GET", "user/repos?limit=50&page=2"): FakeResponse(
                    200, [repo("me/last", True)]
                ),
            }
        )
        gitea = Gitea(transport, "secret")
        self.assertEqual(
            [r["full_name"] for r in first] + ["me/last"],
            list(gitea.iter_my_forks()),
        )

    def test_no_repositories(self):
        transport = FakeTransport(
            {USER: ME, ("GET", "user/repos?limit=50&page=1"): FakeResponse(200, [])}
        )
        gitea = Gitea(transport, "secret")
        self.assertEqual([], list(gitea.iter_my_forks()))

    def test_forbidden(self):
        transport = FakeTransport(
            {
                USER: ME,
                ("GET", "user/repos?limit=50&page=1"): FakeResponse(
                    403, {"message": "token does not have the required scope"}
                ),
            }
        )
        gitea = Gitea(transport, "secret")
        self.assertRaises(
            transport_errors.PermissionDenied, list, gitea.iter_my_forks()
        )


class DeleteProjectTests(TestCase):
    def delete(self, status):
        transport = FakeTransport({("DELETE", "repos/me/fork"): FakeResponse(status)})
        Gitea(transport, "secret").delete_project("me/fork")
        return transport

    def test_deleted(self):
        transport = self.delete(204)
        self.assertEqual(
            [
                (
                    "DELETE",
                    "https://gitea.example.com/api/v1/repos/me/fork",
                    "token secret",
                )
            ],
            transport.requests,
        )

    def test_missing(self):
        e = self.assertRaises(NoSuchProject, self.delete, 404)
        self.assertEqual("me/fork", e.project)

    def test_forbidden(self):
        self.assertRaises(transport_errors.PermissionDenied, self.delete, 403)

    def test_unexpected_status(self):
        self.assertRaises(transport_errors.UnexpectedHttpStatus, self.delete, 500)


class GiteaConfigTestCase(TestCaseInTempDir):
    def write_config(self, name, contents):
        os.makedirs(bedding.config_dir(), exist_ok=True)
        with open(os.path.join(bedding.config_dir(), name), "w") as f:
            f.write(contents)


class ProbeFromHostnameTests(GiteaConfigTestCase):
    def setUp(self):
        super().setUp()
        self.write_config(
            "gitea.conf",
            "[example]\nurl = http://gitea.example.com:3000/\nprivate_token = sekrit\n",
        )

    def test_known_hostname(self):
        forge = Gitea.probe_from_hostname("gitea.example.com")
        self.assertEqual("gitea.example.com", forge.base_hostname)
        self.assertEqual("http://gitea.example.com:3000/", forge.base_url)
        self.assertEqual({"Authorization": "token sekrit"}, forge.headers)

    def test_unknown_hostname(self):
        self.assertRaises(UnsupportedForge, Gitea.probe_from_hostname, "codeberg.org")

    def test_hostname_case_is_ignored(self):
        forge = Gitea.probe_from_hostname("Gitea.Example.COM")
        self.assertEqual("http://gitea.example.com:3000/", forge.base_url)

    def test_first_matching_instance_wins(self):
        self.write_config(
            "gitea.conf",
            "[three]\nurl = http://gitea.example.com:3000/\nprivate_token = a\n"
            "[eight]\nurl = http://gitea.example.com:8080/\nprivate_token = b\n",
        )
        forge = Gitea.probe_from_hostname("gitea.example.com")
        self.assertEqual("http://gitea.example.com:3000/", forge.base_url)


class IterTokensTests(GiteaConfigTestCase):
    def test_entry_without_url_is_skipped(self):
        self.write_config(
            "authentication.conf",
            "[gitea]\nforge = gitea\nprivate_token = sekrit\n",
        )
        self.assertRaises(
            UnsupportedForge, Gitea.probe_from_hostname, "gitea.example.com"
        )
        self.assertEqual([], list(iter_tokens()))
