# Copyright (C) 2010-2018 Jelmer Vernooij <jelmer@jelmer.uk>
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


"""Tests for ref handling."""

from dulwich import porcelain
from dulwich.repo import Repo as GitRepo
from dulwich.server import update_server_info

from ... import tests
from ...branch import Branch
from ...controldir import ControlDir
from ...tests import http_server
from ...tests.http_utils import TestCaseWithWebserver
from ..mapping import default_mapping
from ..object_store import BazaarObjectStore
from ..refs import BazaarRefsContainer, branch_name_to_ref, ref_to_branch_name
from ..transportgit import TransportRepo


class BranchNameRefConversionTests(tests.TestCase):
    def test_head(self):
        self.assertEqual("", ref_to_branch_name(b"HEAD"))
        self.assertEqual(b"HEAD", branch_name_to_ref(""))

    def test_tag(self):
        self.assertRaises(ValueError, ref_to_branch_name, b"refs/tags/FOO")

    def test_branch(self):
        self.assertEqual("frost", ref_to_branch_name(b"refs/heads/frost"))
        self.assertEqual(b"refs/heads/frost", branch_name_to_ref("frost"))


class BazaarRefsContainerTests(tests.TestCaseWithTransport):
    def test_empty(self):
        tree = self.make_branch_and_tree(".")
        store = BazaarObjectStore(tree.branch.repository)
        refs = BazaarRefsContainer(tree.controldir, store)
        self.assertEqual(refs.as_dict(), {})

    def test_some_commit(self):
        tree = self.make_branch_and_tree(".")
        revid = tree.commit("somechange")
        store = BazaarObjectStore(tree.branch.repository)
        refs = BazaarRefsContainer(tree.controldir, store)
        self.assertEqual(refs.as_dict(), {b"HEAD": store._lookup_revision_sha1(revid)})

    def test_some_tag(self):
        tree = self.make_branch_and_tree(".")
        revid = tree.commit("somechange")
        tree.branch.tags.set_tag("sometag", revid)
        store = BazaarObjectStore(tree.branch.repository)
        refs = BazaarRefsContainer(tree.controldir, store)
        self.assertEqual(
            refs.as_dict(),
            {
                b"HEAD": store._lookup_revision_sha1(revid),
                b"refs/tags/sometag": store._lookup_revision_sha1(revid),
            },
        )

    def test_some_branch(self):
        tree = self.make_branch_and_tree(".")
        revid = tree.commit("somechange")
        otherbranch = tree.controldir.create_branch(name="otherbranch")
        otherbranch.generate_revision_history(revid)
        store = BazaarObjectStore(tree.branch.repository)
        refs = BazaarRefsContainer(tree.controldir, store)
        self.assertEqual(
            refs.as_dict(),
            {
                b"HEAD": store._lookup_revision_sha1(revid),
                b"refs/heads/otherbranch": store._lookup_revision_sha1(revid),
            },
        )


def make_repo_with_tags(path):
    """Make a repository with a plain tag, an annotated tag and info/refs."""
    repo = GitRepo.init(path, mkdir=True)
    commit = repo.get_worktree().commit(
        message=b"message",
        committer=b"committer <committer@example.com>",
        author=b"author <author@example.com>",
    )
    repo.refs[b"refs/tags/light"] = commit
    porcelain.tag_create(
        repo,
        b"v1.0",
        author=b"author <author@example.com>",
        message=b"version 1.0",
        annotated=True,
        tag_time=0,
        tag_timezone=0,
    )
    update_server_info(repo)
    return repo, commit


class TransportRepoInfoRefsTests(tests.TestCaseWithTransport):
    """Opening a repository from the text of its info/refs file."""

    def setUp(self):
        super().setUp()
        self.git_repo, self.commit = make_repo_with_tags("repo")
        t = self.get_transport("repo/.git")
        self.refs_text = t.get_bytes("info/refs")
        self.repo = TransportRepo(t, True, refs_text=self.refs_text)

    def test_peeled_lines_are_not_refs(self):
        self.assertContainsRe(self.refs_text, rb"\trefs/tags/v1\.0\^\{\}\n")
        self.assertEqual(
            {b"HEAD", b"refs/heads/master", b"refs/tags/light", b"refs/tags/v1.0"},
            set(self.repo.refs.as_dict()),
        )

    def test_refs(self):
        tag = self.git_repo.refs[b"refs/tags/v1.0"]
        self.assertNotEqual(self.commit, tag)
        self.assertEqual(tag, self.repo.refs[b"refs/tags/v1.0"])
        self.assertEqual(self.commit, self.repo.refs[b"refs/tags/light"])
        self.assertEqual(self.commit, self.repo.refs[b"refs/heads/master"])

    def test_get_peeled(self):
        self.assertEqual(self.commit, self.repo.refs.get_peeled(b"refs/tags/v1.0"))


class NoContentTypeRequestHandler(http_server.TestingHTTPRequestHandler):
    """Serve files without a Content-Type, as some static servers do."""

    def send_header(self, keyword, value):
        if keyword.lower() != "content-type":
            super().send_header(keyword, value)


class DumbHttpTagsTests(TestCaseWithWebserver):
    """Tags of a repository served as static files over HTTP."""

    def setUp(self):
        super().setUp()
        self.git_repo, self.commit = make_repo_with_tags("repo")
        self.revid = default_mapping.revision_id_foreign_to_bzr(self.commit)

    def create_transport_readonly_server(self):
        return http_server.HttpServer(
            NoContentTypeRequestHandler, protocol_version=self._protocol_version
        )

    def test_tags(self):
        branch = Branch.open(self.get_readonly_url("repo/.git"))
        self.assertEqual(
            {"light": self.revid, "v1.0": self.revid}, branch.tags.get_tag_dict()
        )

    def test_sprout(self):
        controldir = ControlDir.open(self.get_readonly_url("repo/.git"))
        local = controldir.sprout("local").open_branch()
        self.assertEqual(self.revid, local.last_revision())
        self.assertEqual(
            {"light": self.revid, "v1.0": self.revid}, local.tags.get_tag_dict()
        )
        local_git = GitRepo("local")
        self.assertEqual(
            self.git_repo.refs[b"refs/tags/v1.0"], local_git.refs[b"refs/tags/v1.0"]
        )
        self.assertEqual(self.commit, local_git.refs[b"refs/tags/light"])
