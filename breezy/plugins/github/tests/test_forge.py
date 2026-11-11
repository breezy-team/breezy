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

import json
from datetime import datetime

from ....tests import TestCase
from ..forge import GitHub, GitHubMergeProposal, _LazyDict, parse_timestring


class ParseTimestringTests(TestCase):
    def test_simple(self):
        self.assertEqual(
            datetime(2011, 1, 26, 19, 1, 12), parse_timestring("2011-01-26T19:01:12Z")
        )


class GetAuthorTests(TestCase):
    def test_author(self):
        mp = GitHubMergeProposal(None, {"user": {"login": "jelmer"}})
        self.assertEqual("jelmer", mp.get_author())

    def test_no_user(self):
        mp = GitHubMergeProposal(None, {"user": None})
        self.assertIsNone(mp.get_author())


class FakeResponse:
    """A canned HTTP response."""

    def __init__(self, status, payload=None):
        self.status = status
        self.text = "" if payload is None else json.dumps(payload)

    def getheaders(self):
        return {}


class FakeTransport:
    """A transport answering requests from a table of canned responses."""

    base = "https://api.github.com/"

    def __init__(self, responses):
        self.responses = responses
        self.requests = []

    def request(self, method, url, headers=None, body=None, retries=None):
        self.requests.append((method, url, body))
        return self.responses[(method, url)]


class MetadataTests(TestCase):
    def test_draft(self):
        mp = GitHubMergeProposal(None, {"draft": True})
        self.assertTrue(mp.is_work_in_progress())

    def test_not_draft(self):
        mp = GitHubMergeProposal(None, {"draft": False})
        self.assertFalse(mp.is_work_in_progress())

    def test_timestamps(self):
        mp = GitHubMergeProposal(
            None,
            {
                "created_at": "2026-01-01T10:00:00Z",
                "updated_at": "2026-01-02T11:30:00Z",
            },
        )
        self.assertEqual(datetime(2026, 1, 1, 10, 0, 0), mp.get_created_at())
        self.assertEqual(datetime(2026, 1, 2, 11, 30, 0), mp.get_updated_at())

    def test_search_result(self):
        # Search results only include a summary of the pull request, so the
        # rest is retrieved when needed.
        url = "https://api.github.com/repos/foo/bar/pulls/1"
        search = "https://api.github.com/search/issues?q=is%3Apr%20is%3Aopen%20author%3Ajelmer;per_page=100;page={}"
        transport = FakeTransport(
            {
                ("GET", search.format(1)): FakeResponse(
                    200, {"items": [{"pull_request": {"url": url}}]}
                ),
                ("GET", search.format(2)): FakeResponse(200, {"items": []}),
                ("GET", url): FakeResponse(
                    200,
                    {"url": url, "draft": True, "created_at": "2026-01-01T10:00:00Z"},
                ),
            }
        )
        [mp] = GitHub(transport).iter_my_proposals(author="jelmer")
        self.assertTrue(mp.is_work_in_progress())
        self.assertEqual(datetime(2026, 1, 1, 10, 0, 0), mp.get_created_at())


class LazyDictTests(TestCase):
    def make_dict(self):
        self.loads = 0

        def load():
            self.loads += 1
            return {"a": 1, "b": 2}

        return _LazyDict({"a": 1}, load)

    def test_keys_twice(self):
        d = self.make_dict()
        self.assertEqual({"a", "b"}, set(d.keys()))
        self.assertEqual({"a", "b"}, set(d.keys()))
        self.assertEqual(1, self.loads)

    def test_items_after_getitem_loaded(self):
        d = self.make_dict()
        self.assertEqual(2, d["b"])
        self.assertEqual({("a", 1), ("b", 2)}, set(d.items()))
        self.assertEqual(1, self.loads)

    def test_values_twice(self):
        d = self.make_dict()
        self.assertEqual([1, 2], sorted(d.values()))
        self.assertEqual([1, 2], sorted(d.values()))
        self.assertEqual(1, self.loads)

    def test_get_loads_missing(self):
        d = self.make_dict()
        self.assertEqual(2, d.get("b"))
        self.assertEqual(None, d.get("c"))
        self.assertEqual(1, self.loads)

    def test_get_present_does_not_load(self):
        d = self.make_dict()
        self.assertEqual(1, d.get("a"))
        self.assertEqual(0, self.loads)
