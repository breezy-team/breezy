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

from dromedary.errors import UnexpectedHttpStatus

from ....forge import (
    DiffRefs,
    HeadChanged,
    NoSuchProject,
    ProposalEvent,
    ProposalEventKind,
)
from ....git.mapping import default_mapping
from ....tests import TestCase
from ..forge import (
    GitHub,
    GitHubMergeProposal,
    GraphqlErrors,
    _LazyDict,
    parse_timestring,
)


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

    def __init__(self, status, body=None):
        self.status = status
        if body is None:
            self.data = b""
        elif isinstance(body, bytes):
            self.data = body
        else:
            self.data = json.dumps(body).encode("utf-8")

    @property
    def text(self):
        return self.data.decode("utf-8")

    def getheaders(self):
        return {}


class FakeTransport:
    """A transport answering requests from a table of canned responses.

    A list of responses is answered in order, one per request.
    """

    base = "https://api.github.com/"

    def __init__(self, responses):
        self.responses = responses
        self.requests = []

    def request(self, method, url, headers=None, body=None, retries=None):
        self.requests.append((method, url, headers, body))
        response = self.responses[(method, url)]
        if isinstance(response, list):
            return response.pop(0)
        return response


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


PR_URL = "https://api.github.com/repos/owner/repo/pulls/1"
PR = {
    "url": PR_URL,
    "html_url": "https://github.com/owner/repo/pull/1",
    "head": {"sha": "a" * 40},
    "base": {
        "sha": "b" * 40,
        "repo": {"url": "https://api.github.com/repos/owner/repo"},
    },
}


class GetDiffTests(TestCase):
    def test_diff(self):
        diff = b"diff --git a/foo b/foo\n"
        transport = FakeTransport({("GET", PR_URL): FakeResponse(200, diff)})
        gh = GitHub(transport)
        mp = GitHubMergeProposal(gh, PR)
        self.assertEqual(diff, mp.get_diff())
        self.assertEqual(
            "application/vnd.github.diff", transport.requests[0][2]["Accept"]
        )

    def test_too_large(self):
        transport = FakeTransport({("GET", PR_URL): FakeResponse(406)})
        gh = GitHub(transport)
        mp = GitHubMergeProposal(gh, PR)
        self.assertRaises(UnexpectedHttpStatus, mp.get_diff)


class GetDiffRefsTests(TestCase):
    def test_refs(self):
        moved = dict(PR, head={"sha": "c" * 40})
        compare_url = (
            "https://api.github.com/repos/owner/repo/compare/"
            + "b" * 40
            + "..."
            + "c" * 40
            + "?per_page=1"
        )
        transport = FakeTransport(
            {
                ("GET", PR_URL): FakeResponse(200, moved),
                ("GET", compare_url): FakeResponse(
                    200, {"merge_base_commit": {"sha": "d" * 40}}
                ),
            }
        )
        mp = GitHubMergeProposal(GitHub(transport), PR)
        self.assertEqual(
            DiffRefs(
                head_revision=b"git-v1:" + b"c" * 40,
                base_revision=b"git-v1:" + b"d" * 40,
                start_revision=b"git-v1:" + b"b" * 40,
            ),
            mp.get_diff_refs(),
        )
        self.assertEqual(b"git-v1:" + b"c" * 40, mp.get_source_revision())


HEAD_SHA = "a" * 40
NEW_SHA = "b" * 40
HEAD_REVISION = default_mapping.revision_id_foreign_to_bzr(HEAD_SHA.encode("ascii"))
NEW_REVISION = default_mapping.revision_id_foreign_to_bzr(NEW_SHA.encode("ascii"))
GRAPHQL_URL = "https://api.github.com/graphql"


def make_proposal(responses):
    transport = FakeTransport(responses)
    pr = {"url": PR_URL, "node_id": "PR_1", "head": {"sha": HEAD_SHA}}
    return GitHubMergeProposal(GitHub(transport), pr), transport


def graphql_error(message):
    return FakeResponse(
        200,
        {
            "errors": [
                {
                    "type": "UNPROCESSABLE",
                    "path": ["updatePullRequestBranch"],
                    "message": message,
                }
            ]
        },
    )


class RebaseTests(TestCase):
    def test_rebase(self):
        mp, transport = make_proposal(
            {
                ("POST", GRAPHQL_URL): FakeResponse(
                    200,
                    {
                        "data": {
                            "updatePullRequestBranch": {
                                "pullRequest": {"headRefOid": NEW_SHA}
                            }
                        }
                    },
                )
            }
        )
        self.assertTrue(mp.rebase(expected_revision=HEAD_REVISION))
        body = json.loads(transport.requests[0][3])
        self.assertEqual(
            {"pullRequestId": "PR_1", "expectedHeadOid": HEAD_SHA}, body["variables"]
        )

    def test_up_to_date(self):
        mp, _ = make_proposal(
            {
                ("POST", GRAPHQL_URL): graphql_error(
                    "There are no new commits on the base branch."
                )
            }
        )
        self.assertFalse(mp.rebase())

    def test_head_changed(self):
        mp, _ = make_proposal(
            {
                ("POST", GRAPHQL_URL): graphql_error("Head moved"),
                ("GET", PR_URL): FakeResponse(
                    200, {"url": PR_URL, "head": {"sha": NEW_SHA}}
                ),
            }
        )
        e = self.assertRaises(HeadChanged, mp.rebase, expected_revision=HEAD_REVISION)
        self.assertEqual((HEAD_REVISION, NEW_REVISION), (e.expected, e.actual))

    def test_other_error(self):
        mp, _ = make_proposal(
            {
                ("POST", GRAPHQL_URL): graphql_error("Merge conflict"),
                ("GET", PR_URL): FakeResponse(
                    200, {"url": PR_URL, "head": {"sha": HEAD_SHA}}
                ),
            }
        )
        self.assertRaises(GraphqlErrors, mp.rebase, expected_revision=HEAD_REVISION)


def timeline_page(nodes, cursor=None):
    return FakeResponse(
        200,
        {
            "data": {
                "repository": {
                    "pullRequest": {
                        "timelineItems": {
                            "nodes": nodes,
                            "pageInfo": {
                                "hasNextPage": cursor is not None,
                                "endCursor": cursor,
                            },
                        }
                    }
                }
            }
        },
    )


def revid(sha):
    return default_mapping.revision_id_foreign_to_bzr(sha.encode("ascii"))


class IterEventsTests(TestCase):
    def test_events(self):
        user = {"__typename": "User", "login": "alice"}
        bot = {"__typename": "Bot", "login": "ci"}
        transport = FakeTransport(
            {
                ("POST", GRAPHQL_URL): [
                    timeline_page(
                        [
                            {
                                "__typename": "IssueComment",
                                "createdAt": "2026-01-01T10:00:00Z",
                                "author": bot,
                            },
                            {
                                # Committed before it was pushed.
                                "__typename": "PullRequestCommit",
                                "commit": {
                                    "oid": "a" * 40,
                                    "committedDate": "2026-01-01T09:00:00Z",
                                },
                            },
                            {
                                "__typename": "PullRequestReview",
                                "submittedAt": None,
                                "state": "PENDING",
                                "author": user,
                                "commit": None,
                            },
                        ],
                        cursor="c1",
                    ),
                    timeline_page(
                        [
                            {
                                "__typename": "PullRequestReview",
                                "submittedAt": "2026-01-02T10:00:00Z",
                                "state": "CHANGES_REQUESTED",
                                "author": user,
                                "commit": {"oid": "a" * 40},
                            },
                            {
                                "__typename": "HeadRefForcePushedEvent",
                                "createdAt": "2026-01-03T10:00:00Z",
                                "actor": {"__typename": "User", "login": "bob"},
                                "afterCommit": {"oid": "b" * 40},
                            },
                            {
                                "__typename": "IssueComment",
                                "createdAt": "2026-01-03T11:00:00Z",
                                "author": None,
                            },
                            {
                                "__typename": "PullRequestReview",
                                "submittedAt": "2026-01-04T10:00:00Z",
                                "state": "APPROVED",
                                "author": user,
                                "commit": {"oid": "b" * 40},
                            },
                        ]
                    ),
                ],
            }
        )
        mp = GitHubMergeProposal(
            GitHub(transport), {"html_url": "https://github.com/foo/bar/pull/3"}
        )
        self.assertEqual(
            [
                ProposalEvent(
                    kind=ProposalEventKind.PUSH,
                    actor=None,
                    timestamp=datetime(2026, 1, 1, 9, 0, 0),
                    revision=revid("a" * 40),
                ),
                ProposalEvent(
                    kind=ProposalEventKind.COMMENT,
                    actor="ci[bot]",
                    timestamp=datetime(2026, 1, 1, 10, 0, 0),
                    actor_is_bot=True,
                ),
                ProposalEvent(
                    kind=ProposalEventKind.UNAPPROVAL,
                    actor="alice",
                    timestamp=datetime(2026, 1, 2, 10, 0, 0),
                    revision=revid("a" * 40),
                ),
                ProposalEvent(
                    kind=ProposalEventKind.PUSH,
                    actor="bob",
                    timestamp=datetime(2026, 1, 3, 10, 0, 0),
                    revision=revid("b" * 40),
                ),
                ProposalEvent(
                    kind=ProposalEventKind.COMMENT,
                    actor=None,
                    timestamp=datetime(2026, 1, 3, 11, 0, 0),
                ),
                ProposalEvent(
                    kind=ProposalEventKind.APPROVAL,
                    actor="alice",
                    timestamp=datetime(2026, 1, 4, 10, 0, 0),
                    revision=revid("b" * 40),
                ),
            ],
            list(mp.iter_events()),
        )
        self.assertEqual(
            [
                {"owner": "foo", "name": "bar", "number": 3, "cursor": None},
                {"owner": "foo", "name": "bar", "number": 3, "cursor": "c1"},
            ],
            [json.loads(body)["variables"] for (_, _, _, body) in transport.requests],
        )

    def test_not_found(self):
        transport = FakeTransport(
            {
                ("POST", GRAPHQL_URL): FakeResponse(
                    200, {"data": {"repository": None}}
                ),
            }
        )
        mp = GitHubMergeProposal(
            GitHub(transport), {"html_url": "https://github.com/foo/bar/pull/3"}
        )
        self.assertRaises(NoSuchProject, mp.iter_events)

    def test_graphql_errors(self):
        transport = FakeTransport(
            {
                ("POST", GRAPHQL_URL): FakeResponse(
                    200, {"data": None, "errors": [{"message": "boom"}]}
                ),
            }
        )
        mp = GitHubMergeProposal(
            GitHub(transport), {"html_url": "https://github.com/foo/bar/pull/3"}
        )
        self.assertRaises(GraphqlErrors, mp.iter_events)

    def test_dismissed_review_skipped(self):
        user = {"__typename": "User", "login": "alice"}
        transport = FakeTransport(
            {
                ("POST", GRAPHQL_URL): [
                    timeline_page(
                        [
                            {
                                "__typename": "PullRequestReview",
                                "submittedAt": "2026-01-02T10:00:00Z",
                                "state": "DISMISSED",
                                "author": user,
                                "commit": {"oid": "a" * 40},
                            },
                        ]
                    ),
                ],
            }
        )
        mp = GitHubMergeProposal(
            GitHub(transport), {"html_url": "https://github.com/foo/bar/pull/3"}
        )
        self.assertEqual([], mp.iter_events())


ISSUE_URL = "https://api.github.com/repos/foo/bar/issues/1"


class LabelsTests(TestCase):
    def make_proposal(self, responses):
        transport = FakeTransport(responses)
        pr = {"issue_url": ISSUE_URL, "labels": [{"name": "bug"}]}
        return transport, GitHubMergeProposal(GitHub(transport), pr)

    def test_get_labels(self):
        _, mp = self.make_proposal({})
        self.assertEqual(["bug"], mp.get_labels())

    def test_add_label(self):
        transport, mp = self.make_proposal(
            {
                ("POST", ISSUE_URL + "/labels"): FakeResponse(
                    200, [{"name": "bug"}, {"name": "new label"}]
                )
            }
        )
        mp.add_label("new label")
        self.assertEqual(
            [("POST", ISSUE_URL + "/labels", b'{"labels": ["new label"]}')],
            [(m, u, b) for (m, u, h, b) in transport.requests],
        )
        self.assertEqual(["bug", "new label"], mp.get_labels())

    def test_remove_label(self):
        transport, mp = self.make_proposal(
            {("DELETE", ISSUE_URL + "/labels/bug%2Ffix"): FakeResponse(200, [])}
        )
        mp.remove_label("bug/fix")
        self.assertEqual(
            [("DELETE", ISSUE_URL + "/labels/bug%2Ffix", None)],
            [(m, u, b) for (m, u, h, b) in transport.requests],
        )
        self.assertEqual([], mp.get_labels())

    def test_remove_missing_label(self):
        _, mp = self.make_proposal(
            {
                ("DELETE", ISSUE_URL + "/labels/other"): FakeResponse(
                    404, {"message": "Label does not exist"}
                )
            }
        )
        mp.remove_label("other")
        self.assertEqual(["bug"], mp.get_labels())

    def test_add_label_search_result(self):
        # Search results only have a summary of the pull request.
        transport = FakeTransport(
            {("POST", ISSUE_URL + "/labels"): FakeResponse(200, [{"name": "new"}])}
        )
        pr = _LazyDict(
            {"url": "https://api.github.com/repos/foo/bar/pulls/1"},
            lambda: {"issue_url": ISSUE_URL, "labels": [], "title": "Title"},
        )
        mp = GitHubMergeProposal(GitHub(transport), pr)
        mp.add_label("new")
        self.assertEqual(["new"], mp.get_labels())
        self.assertEqual("Title", mp.get_title())
