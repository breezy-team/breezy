# Copyright (C) 2009-2018 Jelmer Vernooij <jelmer@jelmer.uk>
# Copyright (C) 2007 Canonical Ltd
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

"""Test the GitDir class."""

import os
from io import BytesIO

from dulwich.repo import Repo as GitRepo
from dulwich.server import update_server_info

from ... import controldir, errors, urlutils
from ...branch import Branch
from ...tests.http_utils import TestCaseWithWebserver
from ...transport import get_transport
from .. import RemoteGitProber, dir, tests, workingtree
from ..mapping import default_mapping
from ..remote import RemoteGitControlDirFormat


class TestGitDir(tests.TestCaseInTempDir):
    def test_get_head_branch_reference(self):
        GitRepo.init(".")

        gd = controldir.ControlDir.open(".")
        self.assertEqual(
            "{},branch=master".format(urlutils.local_path_to_url(os.path.abspath("."))),
            gd.get_branch_reference(),
        )

    def test_get_reference_loop(self):
        r = GitRepo.init(".")
        r.refs.set_symbolic_ref(b"refs/heads/loop", b"refs/heads/loop")

        gd = controldir.ControlDir.open(".")
        self.assertRaises(
            controldir.BranchReferenceLoop, gd.get_branch_reference, name="loop"
        )

    def test_open_reference_loop(self):
        r = GitRepo.init(".")
        r.refs.set_symbolic_ref(b"refs/heads/loop", b"refs/heads/loop")

        gd = controldir.ControlDir.open(".")
        self.assertRaises(controldir.BranchReferenceLoop, gd.open_branch, name="loop")

    def test_open_existing(self):
        GitRepo.init(".")

        gd = controldir.ControlDir.open(".")
        self.assertIsInstance(gd, dir.LocalGitDir)

    def test_open_ref_parent(self):
        r = GitRepo.init(".")
        r.get_worktree().commit(message=b"message", ref=b"refs/heads/foo/bar")
        gd = controldir.ControlDir.open(".")
        self.assertRaises(errors.NotBranchError, gd.open_branch, "foo")

    def test_open_workingtree(self):
        r = GitRepo.init(".")
        r.get_worktree().commit(message=b"message")

        gd = controldir.ControlDir.open(".")
        wt = gd.open_workingtree()
        self.assertIsInstance(wt, workingtree.GitWorkingTree)

    def test_open_workingtree_bare(self):
        GitRepo.init_bare(".")

        gd = controldir.ControlDir.open(".")
        self.assertRaises(errors.NoWorkingTree, gd.open_workingtree)

    def test_git_file(self):
        gitrepo = GitRepo.init("blah", mkdir=True)
        self.build_tree_contents([("foo/",), ("foo/.git", b"gitdir: ../blah/.git\n")])

        gd = controldir.ControlDir.open("foo")
        self.assertEqual(
            gd.control_url.rstrip("/"),
            urlutils.local_path_to_url(os.path.abspath(gitrepo.controldir())),
        )

    def test_shared_repository(self):
        t = get_transport(".")
        self.assertRaises(
            errors.SharedRepositoriesUnsupported,
            dir.LocalGitControlDirFormat().initialize_on_transport_ex,
            t,
            shared_repo=True,
        )


class TestGitDirFormat(tests.TestCase):
    def setUp(self):
        super().setUp()
        self.format = dir.LocalGitControlDirFormat()

    def test_get_format_description(self):
        self.assertEqual("Local Git Repository", self.format.get_format_description())

    def test_eq(self):
        format2 = dir.LocalGitControlDirFormat()
        self.assertEqual(self.format, format2)
        self.assertEqual(self.format, self.format)
        bzr_format = controldir.format_registry.make_controldir("default")
        self.assertNotEqual(self.format, bzr_format)


class RemoteGitProberInfoRefsTests(tests.TestCase):
    """Telling smart, dumb and no git at all from the info/refs answer."""

    REFS = b"2001b954f1ec392f84f7cec2f2f96a76ed6ba4ee\trefs/heads/master\n"
    # An annotated tag also gets a peeled ``^{}`` line.
    TAG_REFS = (
        b"0729ab4a7e204353df507e300f72fcda1defb34a\trefs/tags/v1\n"
        b"d0724583ca78e4d47a504ce5b6f26fcd75dc1413\trefs/tags/v1^{}\n"
    )
    HTML = b"<!DOCTYPE html>\n<html><body>\thello</body></html>\n"

    def _probe(self, content_type, body):
        class Response:
            status = 200
            reason = "OK"
            _body = BytesIO(body)

            def getheader(self, name):
                return content_type

            def read(self, amt=None):
                self.read_sizes.append(amt)
                return self._body.read(amt)

        self.read_sizes = Response.read_sizes = []

        class Transport:
            base = "http://example.invalid/"

            def external_url(self):
                return self.base

            def request(self, method, url, headers=None):
                return Response()

        return RemoteGitProber().probe_transport(Transport())

    def test_smart(self):
        format = self._probe(
            "application/x-git-upload-pack-advertisement",
            b"001e# service=git-upload-pack\n0000",
        )
        self.assertIsInstance(format, RemoteGitControlDirFormat)

    def test_dumb_without_content_type(self):
        format = self._probe(None, self.REFS)
        self.assertIsInstance(format, dir.BareLocalGitControlDirFormat)
        self.assertEqual(self.REFS, format._refs_text)

    def test_dumb_with_content_type(self):
        refs = self.REFS + self.TAG_REFS
        for content_type in ("text/plain", "application/octet-stream"):
            format = self._probe(content_type, refs)
            self.assertIsInstance(format, dir.BareLocalGitControlDirFormat)
            self.assertEqual(refs, format._refs_text)

    def test_dumb_sha256(self):
        refs = (
            b"1bcefd3b1e4bb81bbe69ee05d18ea2424429764af11e5fbe32cfb6cb33131d9f"
            b"\trefs/heads/master\n"
        )
        format = self._probe("text/plain", refs)
        self.assertIsInstance(format, dir.BareLocalGitControlDirFormat)

    def test_page_is_not_a_branch(self):
        self.assertRaises(errors.NotBranchError, self._probe, "text/html", self.HTML)
        self.assertRaises(errors.NotBranchError, self._probe, None, self.HTML)

    def test_page_is_not_read_whole(self):
        page = self.HTML + b"x" * 1000
        self.assertRaises(errors.NotBranchError, self._probe, "text/html", page)
        self.assertEqual([65], self.read_sizes)

    def test_empty_without_content_type(self):
        format = self._probe(None, b"")
        self.assertIsInstance(format, dir.BareLocalGitControlDirFormat)
        self.assertEqual(b"", format._refs_text)

    def test_typed_empty_is_not_a_branch(self):
        self.assertRaises(errors.NotBranchError, self._probe, "text/plain", b"")

    def test_smart_body_with_other_type_is_not_a_branch(self):
        self.assertRaises(
            errors.NotBranchError,
            self._probe,
            "text/plain",
            b"001e# service=git-upload-pack\n0000",
        )

    def test_bad_refs_line_is_not_a_branch(self):
        for body in (
            self.REFS + b"hello\n",
            b"2001b954\trefs/heads/master\n",
            b"2001b954f1ec392f84f7cec2f2f96a76ed6ba4ee refs/heads/master\n",
        ):
            self.assertRaises(errors.NotBranchError, self._probe, "text/plain", body)


class DumbHttpTests(TestCaseWithWebserver):
    """A repository served as static files, with a Content-Type."""

    def setUp(self):
        super().setUp()
        self.git_repo = GitRepo.init("repo", mkdir=True)
        self.commit = self.git_repo.get_worktree().commit(
            message=b"message",
            committer=b"committer <committer@example.com>",
            author=b"author <author@example.com>",
        )
        update_server_info(self.git_repo)

    def test_content_type_is_sent(self):
        t = self.get_readonly_transport("repo/.git")
        resp = t.request("GET", t.abspath("info/refs"))
        self.assertEqual("application/octet-stream", resp.getheader("Content-Type"))

    def test_open_branch(self):
        branch = Branch.open(self.get_readonly_url("repo/.git"))
        self.assertEqual(
            default_mapping.revision_id_foreign_to_bzr(self.commit),
            branch.last_revision(),
        )

    def test_sprout(self):
        remote = controldir.ControlDir.open(self.get_readonly_url("repo/.git"))
        local = remote.sprout("local")
        self.assertEqual(
            default_mapping.revision_id_foreign_to_bzr(self.commit),
            local.open_branch().last_revision(),
        )
