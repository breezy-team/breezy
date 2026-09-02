# Copyright (C) 2026 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""Tests for Gitea."""

import json
from datetime import datetime, timezone

from breezy.tests import TestCase

from ..forge import (
    Gitea,
    GiteaMergeProposal,
    NotGiteaUrl,
    NotMergeRequestUrl,
    ValidationFailed,
    parse_gitea_pr_url,
    parse_gitea_url,
    parse_timestring,
)


class FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self.text = json.dumps(body)

    def getheaders(self):
        return {}


class MergeRefreshesStateTests(TestCase):
    def test_is_merged_true_after_merge(self):
        base_pr = {
            "number": 7,
            "state": "open",
            "merged": False,
            "base": {"repo": {"full_name": "owner/repo"}},
        }
        gt = Gitea.__new__(Gitea)

        def fake_request(method, path, body=None):
            if method == "POST":
                return FakeResponse(200, {})
            if method == "GET":
                return FakeResponse(200, {**base_pr, "merged": True, "state": "closed"})
            raise AssertionError(f"unexpected {method} {path}")

        gt._api_request = fake_request
        proposal = GiteaMergeProposal(gt, dict(base_pr))
        self.assertFalse(proposal.is_merged())
        proposal.merge()
        self.assertTrue(proposal.is_merged())


class CreatePullDuplicateTests(TestCase):
    def test_409_raises_validation_failed(self):
        gt = Gitea.__new__(Gitea)
        response_body = {"message": "pull request already exists for these targets"}
        gt._api_request = lambda method, path, body=None: FakeResponse(
            409, response_body
        )
        self.assertRaises(
            ValidationFailed,
            gt._create_pull,
            "owner",
            "repo",
            title="dup",
            head="feature",
            base="main",
        )


class ParseGiteaUrlTests(TestCase):
    def test_invalid(self):
        self.assertRaises(NotGiteaUrl, parse_gitea_url, "bzr://gitea.example.com/")
        self.assertRaises(NotGiteaUrl, parse_gitea_url, "https:///owner/repo")
        self.assertRaises(
            NotGiteaUrl, parse_gitea_url, "https://gitea.example.com/owner"
        )

    def test_simple(self):
        self.assertEqual(
            ("gitea.example.com", "owner", "repo"),
            parse_gitea_url("https://gitea.example.com/owner/repo"),
        )

    def test_strips_git_suffix(self):
        self.assertEqual(
            ("gitea.example.com", "owner", "repo"),
            parse_gitea_url("https://gitea.example.com/owner/repo.git"),
        )

    def test_ssh(self):
        self.assertEqual(
            ("gitea.example.com", "owner", "repo"),
            parse_gitea_url("git+ssh://gitea.example.com/owner/repo"),
        )


class ParseGiteaPrUrlTests(TestCase):
    def test_invalid(self):
        self.assertRaises(NotGiteaUrl, parse_gitea_pr_url, "bzr://gitea.example.com/")
        self.assertRaises(
            NotMergeRequestUrl,
            parse_gitea_pr_url,
            "https://gitea.example.com/owner/repo",
        )
        self.assertRaises(
            NotMergeRequestUrl,
            parse_gitea_pr_url,
            "https://gitea.example.com/owner/repo/issues/4",
        )

    def test_simple(self):
        self.assertEqual(
            ("gitea.example.com", "owner", "repo", 4),
            parse_gitea_pr_url("https://gitea.example.com/owner/repo/pulls/4"),
        )


class ParseTimestringTests(TestCase):
    def test_zulu(self):
        self.assertEqual(
            datetime(2026, 1, 15, 10, 30, 45), parse_timestring("2026-01-15T10:30:45Z")
        )

    def test_offset(self):
        self.assertEqual(
            datetime(2026, 1, 15, 10, 30, 45, tzinfo=timezone.utc),
            parse_timestring("2026-01-15T10:30:45+00:00"),
        )
