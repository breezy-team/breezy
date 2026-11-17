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
from datetime import datetime

from dromedary.errors import NoSuchFile, RedirectRequested, UnexpectedHttpStatus

from breezy.forge import (
    DiffRefs,
    HeadChanged,
    NoSuchProject,
    ProposalEvent,
    ProposalEventKind,
)
from breezy.git.mapping import default_mapping
from breezy.tests import TestCase

from ..forge import (
    GitLab,
    GitLabError,
    GitLabMergeProposal,
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

    def test_without_fraction(self):
        self.assertEqual(
            datetime(2018, 9, 7, 11, 16, 17),
            parse_timestring("2018-09-07T11:16:17Z"),
        )


class FakeResponse:
    def __init__(self, status, data=b""):
        self.status = status
        self.data = data

    def getheader(self, name):
        return None

    def getheaders(self):
        return {}


class FakeTransport:
    """Transport answering requests from a table of canned responses."""

    base = "https://gitlab.example.com/"

    def __init__(self, responses):
        self.responses = responses
        self.calls = []
        self.fields = []

    def request(self, method, url, headers=None, fields=None, body=None):
        self.calls.append((method, url))
        self.fields.append(fields)
        response = self.responses[url]
        if isinstance(response, list):
            response = response.pop(0)
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
        self.assertEqual({"path_with_namespace": "foo/new"}, gl._get_project("foo/old"))
        self.assertEqual(
            [
                ("GET", "https://gitlab.example.com/api/v4/projects/foo%2Fold"),
                ("GET", "https://gitlab.example.com/foo/old"),
                ("GET", "https://gitlab.example.com/api/v4/projects/foo%2Fnew"),
            ],
            transport.calls,
        )


class GetAuthorTests(TestCase):
    def test_author(self):
        mp = GitLabMergeProposal(None, {"author": {"username": "jelmer"}})
        self.assertEqual("jelmer", mp.get_author())

    def test_no_author(self):
        mp = GitLabMergeProposal(None, {"author": None})
        self.assertIsNone(mp.get_author())


class MetadataTests(TestCase):
    def test_draft(self):
        mp = GitLabMergeProposal(None, {"draft": True, "work_in_progress": True})
        self.assertTrue(mp.is_work_in_progress())

    def test_not_draft(self):
        mp = GitLabMergeProposal(None, {"draft": False, "work_in_progress": False})
        self.assertFalse(mp.is_work_in_progress())

    def test_work_in_progress_only(self):
        mp = GitLabMergeProposal(None, {"work_in_progress": True})
        self.assertTrue(mp.is_work_in_progress())

    def test_timestamps(self):
        mp = GitLabMergeProposal(
            None,
            {
                "created_at": "2026-01-01T10:00:00.000Z",
                "updated_at": "2026-01-02T11:30:00.250Z",
            },
        )
        self.assertEqual(datetime(2026, 1, 1, 10, 0, 0), mp.get_created_at())
        self.assertEqual(datetime(2026, 1, 2, 11, 30, 0, 250000), mp.get_updated_at())


MR_URL = "https://gitlab.example.com/api/v4/projects/3/merge_requests/7"


class GetDiffTests(TestCase):
    def test_diff(self):
        diff = b"diff --git a/foo b/foo\n"
        transport = FakeTransport({MR_URL + "/raw_diffs": FakeResponse(200, diff)})
        mp = GitLabMergeProposal(
            GitLab(transport, "token"), {"project_id": 3, "iid": 7}
        )
        self.assertEqual(diff, mp.get_diff())

    def test_error(self):
        transport = FakeTransport({MR_URL + "/raw_diffs": FakeResponse(404)})
        mp = GitLabMergeProposal(
            GitLab(transport, "token"), {"project_id": 3, "iid": 7}
        )
        self.assertRaises(UnexpectedHttpStatus, mp.get_diff)


class GetDiffRefsTests(TestCase):
    def test_refs(self):
        mr = {
            "project_id": 3,
            "iid": 7,
            "sha": "a" * 40,
            "diff_refs": {
                "head_sha": "a" * 40,
                "base_sha": "b" * 40,
                "start_sha": "c" * 40,
            },
        }
        transport = FakeTransport({MR_URL: FakeResponse(200, json.dumps(mr).encode())})
        mp = GitLabMergeProposal(
            GitLab(transport, "token"), {"project_id": 3, "iid": 7}
        )
        self.assertEqual(
            DiffRefs(
                head_revision=b"git-v1:" + b"a" * 40,
                base_revision=b"git-v1:" + b"b" * 40,
                start_revision=b"git-v1:" + b"c" * 40,
            ),
            mp.get_diff_refs(),
        )
        self.assertEqual(b"git-v1:" + b"a" * 40, mp.get_source_revision())


HEAD_SHA = "a" * 40
NEW_SHA = "b" * 40
HEAD_REVISION = b"git-v1:" + HEAD_SHA.encode("ascii")
NEW_REVISION = b"git-v1:" + NEW_SHA.encode("ascii")


def mr_response(**mr):
    data = {"project_id": 3, "iid": 7, "sha": HEAD_SHA}
    data.update(mr)
    return FakeResponse(200, json.dumps(data).encode("utf-8"))


def make_proposal(responses):
    transport = FakeTransport(responses)
    mp = GitLabMergeProposal(
        GitLab(transport, "token"), {"project_id": 3, "iid": 7, "sha": HEAD_SHA}
    )
    return mp, transport


class RebaseTests(TestCase):
    def test_rebase(self):
        mp, transport = make_proposal(
            {
                MR_URL + "?include_diverged_commits_count=true": mr_response(
                    diverged_commits_count=2
                ),
                MR_URL + "/rebase": FakeResponse(202, b'{"rebase_in_progress": true}'),
            }
        )
        self.assertTrue(mp.rebase(expected_revision=HEAD_REVISION))
        self.assertEqual(
            [
                ("GET", MR_URL + "?include_diverged_commits_count=true"),
                ("PUT", MR_URL + "/rebase"),
            ],
            transport.calls,
        )

    def test_up_to_date(self):
        mp, transport = make_proposal(
            {
                MR_URL + "?include_diverged_commits_count=true": mr_response(
                    diverged_commits_count=0
                ),
            }
        )
        self.assertFalse(mp.rebase())
        self.assertEqual(1, len(transport.calls))

    def test_head_changed(self):
        mp, transport = make_proposal(
            {
                MR_URL + "?include_diverged_commits_count=true": mr_response(
                    sha=NEW_SHA, diverged_commits_count=2
                ),
            }
        )
        e = self.assertRaises(HeadChanged, mp.rebase, expected_revision=HEAD_REVISION)
        self.assertEqual((HEAD_REVISION, NEW_REVISION), (e.expected, e.actual))
        self.assertEqual(1, len(transport.calls))


def json_response(payload):
    return FakeResponse(200, json.dumps(payload).encode("utf-8"))


def notes_page(nodes, cursor=None):
    return json_response(
        {
            "data": {
                "project": {
                    "mergeRequest": {
                        "notes": {
                            "nodes": nodes,
                            "pageInfo": {
                                "hasNextPage": cursor is not None,
                                "endCursor": cursor,
                            },
                        }
                    }
                }
            }
        }
    )


def note(created_at, username, action=None, bot=False):
    return {
        "system": action is not None,
        "createdAt": created_at,
        "author": None if username is None else {"username": username, "bot": bot},
        "systemNoteMetadata": None if action is None else {"action": action},
    }


class IterEventsTests(TestCase):
    MR = {"project_id": 5, "iid": 2}
    VERSIONS_URL = (
        "https://gitlab.example.com/api/v4/projects/5/merge_requests/2/versions"
        "?per_page=50&page=1"
    )
    GRAPHQL_URL = "https://gitlab.example.com/api/graphql"

    def test_events(self):
        transport = FakeTransport(
            {
                self.VERSIONS_URL: json_response(
                    [
                        {
                            "head_commit_sha": "b" * 40,
                            "created_at": "2026-01-03T10:00:00.000Z",
                        },
                        {
                            "head_commit_sha": "a" * 40,
                            "created_at": "2026-01-01T10:00:00.000Z",
                        },
                    ]
                ),
                self.GRAPHQL_URL: [
                    notes_page(
                        [
                            note("2026-01-01T11:00:00Z", "ci", bot=True),
                            note("2026-01-01T12:00:00Z", "alice", "requested_changes"),
                            note("2026-01-03T10:00:00Z", "bob", "commit"),
                        ],
                        cursor="c1",
                    ),
                    notes_page(
                        [
                            note("2026-01-04T10:00:00Z", "alice", "approved"),
                            note("2026-01-04T11:00:00Z", None),
                            note("2026-01-05T10:00:00Z", "alice", "unapproved"),
                        ]
                    ),
                ],
            }
        )
        mp = GitLabMergeProposal(GitLab(transport, "token"), self.MR)

        def revid(sha):
            return default_mapping.revision_id_foreign_to_bzr(sha.encode("ascii"))

        events = mp.iter_events()
        self.assertEqual(
            [
                ProposalEvent(
                    kind=ProposalEventKind.PUSH,
                    actor=None,
                    timestamp=datetime(2026, 1, 1, 10, 0, 0),
                    revision=revid("a" * 40),
                ),
                ProposalEvent(
                    kind=ProposalEventKind.COMMENT,
                    actor="ci",
                    timestamp=datetime(2026, 1, 1, 11, 0, 0),
                    actor_is_bot=True,
                ),
                ProposalEvent(
                    kind=ProposalEventKind.UNAPPROVAL,
                    actor="alice",
                    timestamp=datetime(2026, 1, 1, 12, 0, 0),
                ),
                ProposalEvent(
                    kind=ProposalEventKind.PUSH,
                    actor=None,
                    timestamp=datetime(2026, 1, 3, 10, 0, 0),
                    revision=revid("b" * 40),
                ),
                ProposalEvent(
                    kind=ProposalEventKind.APPROVAL,
                    actor="alice",
                    timestamp=datetime(2026, 1, 4, 10, 0, 0),
                ),
                ProposalEvent(
                    kind=ProposalEventKind.COMMENT,
                    actor=None,
                    timestamp=datetime(2026, 1, 4, 11, 0, 0),
                ),
                ProposalEvent(
                    kind=ProposalEventKind.UNAPPROVAL,
                    actor="alice",
                    timestamp=datetime(2026, 1, 5, 10, 0, 0),
                ),
            ],
            events,
        )
        # The "commit" system note from bob is suppressed; pushes come from
        # the versions, which do not record who pushed.
        self.assertNotIn("bob", [event.actor for event in events])

    def test_not_found(self):
        transport = FakeTransport(
            {
                self.VERSIONS_URL: json_response([]),
                self.GRAPHQL_URL: json_response({"data": {"project": None}}),
            }
        )
        mp = GitLabMergeProposal(GitLab(transport, "token"), self.MR)
        self.assertRaises(NoSuchProject, mp.iter_events)

    def test_graphql_errors(self):
        transport = FakeTransport(
            {
                self.VERSIONS_URL: json_response([]),
                self.GRAPHQL_URL: json_response(
                    {"data": None, "errors": [{"message": "boom"}]}
                ),
            }
        )
        mp = GitLabMergeProposal(GitLab(transport, "token"), self.MR)
        e = self.assertRaises(GitLabError, mp.iter_events)
        self.assertEqual("boom", e.error)


class LabelsTests(TestCase):
    def make_proposal(self, responses):
        transport = FakeTransport(responses)
        mr = {"project_id": 3, "iid": 7, "labels": ["bug"]}
        return transport, GitLabMergeProposal(GitLab(transport, "token"), mr)

    def test_get_labels(self):
        _, mp = self.make_proposal({})
        self.assertEqual(["bug"], mp.get_labels())

    def test_add_label(self):
        transport, mp = self.make_proposal(
            {
                MR_URL: FakeResponse(
                    200,
                    b'{"project_id": 3, "iid": 7, "labels": ["bug", "new label"]}',
                )
            }
        )
        mp.add_label("new label")
        self.assertEqual([("PUT", MR_URL)], transport.calls)
        self.assertEqual([{"add_labels": "new label"}], transport.fields)
        self.assertEqual(["bug", "new label"], mp.get_labels())

    def test_remove_label(self):
        transport, mp = self.make_proposal(
            {MR_URL: FakeResponse(200, b'{"project_id": 3, "iid": 7, "labels": []}')}
        )
        mp.remove_label("bug")
        self.assertEqual([("PUT", MR_URL)], transport.calls)
        self.assertEqual([{"remove_labels": "bug"}], transport.fields)
        self.assertEqual([], mp.get_labels())

    def test_comma(self):
        transport, mp = self.make_proposal({})
        self.assertRaises(ValueError, mp.add_label, "a,b")
        self.assertRaises(ValueError, mp.remove_label, "a,b")
        self.assertEqual([], transport.calls)


class GetFileTextTests(TestCase):
    url = (
        "https://gitlab.example.com/api/v4/projects/3/repository/files/"
        f"sub%2FREADME/raw?ref={HEAD_SHA}"
    )

    def make_proposal(self, response):
        transport = FakeTransport({self.url: response})
        mr = {"project_id": 4, "target_project_id": 3}
        return GitLabMergeProposal(GitLab(transport, "token"), mr)

    def test_found(self):
        mp = self.make_proposal(FakeResponse(200, b"hi\n"))
        self.assertEqual(b"hi\n", mp.get_file_text("sub/README", HEAD_REVISION))

    def test_missing(self):
        mp = self.make_proposal(FakeResponse(404))
        e = self.assertRaises(NoSuchFile, mp.get_file_text, "sub/README", HEAD_REVISION)
        self.assertEqual("sub/README", e.path)

    def test_error(self):
        mp = self.make_proposal(FakeResponse(500))
        self.assertRaises(
            UnexpectedHttpStatus, mp.get_file_text, "sub/README", HEAD_REVISION
        )
