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

"""Test the smart client."""

import gzip
import os
import time
from io import BytesIO

from dulwich import porcelain
from dulwich.errors import HangupException
from dulwich.repo import Repo as GitRepo

from ...branch import Branch
from ...controldir import ControlDir
from ...errors import (
    ConnectionReset,
    DivergedBranches,
    NoSuchTag,
    NotBranchError,
    PermissionDenied,
    TransportError,
    UnexpectedHttpStatus,
)
from ...tests import TestCase, TestCaseWithTransport
from ...tests.features import ExecutableFeature
from ...urlutils import join as urljoin
from ..mapping import default_mapping
from ..remote import (
    GitRemoteRevisionTree,
    GitSmartRemoteNotSupported,
    HeadUpdateFailed,
    ProtectedBranchHookDeclined,
    RemoteGitBranchFormat,
    RemoteGitError,
    _git_url_and_path_from_transport,
    parse_git_error,
    parse_git_hangup,
    split_git_url,
)
from ..tree import MissingNestedTree


class SplitUrlTests(TestCase):
    def test_simple(self):
        self.assertEqual(("foo", None, None, "/bar"), split_git_url("git://foo/bar"))

    def test_port(self):
        self.assertEqual(("foo", 343, None, "/bar"), split_git_url("git://foo:343/bar"))

    def test_username(self):
        self.assertEqual(("foo", None, "la", "/bar"), split_git_url("git://la@foo/bar"))

    def test_username_password(self):
        self.assertEqual(
            ("foo", None, "la", "/bar"), split_git_url("git://la:passwd@foo/bar")
        )

    def test_nopath(self):
        self.assertEqual(("foo", None, None, "/"), split_git_url("git://foo/"))

    def test_slashpath(self):
        self.assertEqual(("foo", None, None, "//bar"), split_git_url("git://foo//bar"))

    def test_homedir(self):
        self.assertEqual(("foo", None, None, "~bar"), split_git_url("git://foo/~bar"))

    def test_file(self):
        self.assertEqual(("", None, None, "/bar"), split_git_url("file:///bar"))


class ParseGitErrorTests(TestCase):
    def test_unknown(self):
        e = parse_git_error("url", "foo")
        self.assertIsInstance(e, RemoteGitError)

    def test_connection_closed(self):
        e = parse_git_error(
            "url", "The remote server unexpectedly closed the connection."
        )
        self.assertIsInstance(e, TransportError)

    def test_notbrancherror(self):
        e = parse_git_error("url", "\n Could not find Repository foo/bar")
        self.assertIsInstance(e, NotBranchError)

    def test_notbrancherror_launchpad(self):
        e = parse_git_error("url", "Repository 'foo/bar' not found.")
        self.assertIsInstance(e, NotBranchError)

    def test_notbrancherror_github(self):
        e = parse_git_error("url", "Repository not found.\n")
        self.assertIsInstance(e, NotBranchError)

    def test_notbrancherror_normal(self):
        e = parse_git_error(
            "url",
            "fatal: '/srv/git/lintian-brush' does not appear to be a git repository",
        )
        self.assertIsInstance(e, NotBranchError)

    def test_head_update(self):
        e = parse_git_error("url", "HEAD failed to update\n")
        self.assertIsInstance(e, HeadUpdateFailed)

    def test_permission_dnied(self):
        e = parse_git_error(
            "url", "access denied or repository not exported: /debian/altermime.git"
        )
        self.assertIsInstance(e, PermissionDenied)

    def test_permission_denied_gitlab(self):
        e = parse_git_error(
            "url", "GitLab: You are not allowed to push code to this project.\n"
        )
        self.assertIsInstance(e, PermissionDenied)

    def test_permission_denied_github(self):
        e = parse_git_error(
            "url", "Permission to porridge/gaduhistory.git denied to jelmer."
        )
        self.assertIsInstance(e, PermissionDenied)
        self.assertEqual(e.path, "porridge/gaduhistory.git")
        self.assertEqual(e.extra, ": denied to jelmer")

    def test_pre_receive_hook_declined(self):
        e = parse_git_error("url", "pre-receive hook declined")
        self.assertIsInstance(e, PermissionDenied)
        self.assertEqual(e.path, "url")
        self.assertEqual(e.extra, ": pre-receive hook declined")

    def test_invalid_repo_name(self):
        e = parse_git_error(
            "url",
            """Gregwar/fatcat/tree/debian is not a valid repository name
Email support@github.com for help
""",
        )
        self.assertIsInstance(e, NotBranchError)

    def test_invalid_git_error(self):
        self.assertEqual(
            PermissionDenied(
                "url",
                "GitLab: You are not allowed to push code to protected "
                "branches on this project.",
            ),
            parse_git_error(
                "url",
                RemoteGitError(
                    "GitLab: You are not allowed to push code to "
                    "protected branches on this project."
                ),
            ),
        )

    def test_protected_branch(self):
        self.assertEqual(
            ProtectedBranchHookDeclined(msg="protected branch hook declined"),
            parse_git_error("url", RemoteGitError("protected branch hook declined")),
        )

    def test_host_key_verification(self):
        self.assertEqual(
            TransportError("Host key verification failed"),
            parse_git_error("url", RemoteGitError("Host key verification failed.")),
        )

    def test_connection_reset_by_peer(self):
        self.assertEqual(
            ConnectionReset("[Errno 104] Connection reset by peer"),
            parse_git_error(
                "url", RemoteGitError("[Errno 104] Connection reset by peer")
            ),
        )

    def test_http_unexpected(self):
        self.assertEqual(
            UnexpectedHttpStatus(
                "https://example.com/bigint.git/git-upload-pack",
                403,
                extra=(
                    "unexpected http resp 403 for "
                    "https://example.com/bigint.git/git-upload-pack"
                ),
            ),
            parse_git_error(
                "url",
                RemoteGitError(
                    "unexpected http resp 403 for "
                    "https://example.com/bigint.git/git-upload-pack"
                ),
            ),
        )


class ParseHangupTests(TestCase):
    def setUp(self):
        super().setUp()
        try:
            HangupException([b"foo"])
        except TypeError:
            self.skipTest("dulwich version too old")

    def test_not_set(self):
        self.assertIsInstance(
            parse_git_hangup("http://", HangupException()), ConnectionReset
        )

    def test_single_line(self):
        self.assertEqual(
            RemoteGitError("foo bar"),
            parse_git_hangup("http://", HangupException([b"foo bar"])),
        )

    def test_multi_lines(self):
        self.assertEqual(
            RemoteGitError("foo bar\nbla bla"),
            parse_git_hangup("http://", HangupException([b"foo bar", b"bla bla"])),
        )

    def test_filter_boring(self):
        self.assertEqual(
            RemoteGitError("foo bar"),
            parse_git_hangup(
                "http://", HangupException([b"=======", b"foo bar", b"======"])
            ),
        )
        self.assertEqual(
            RemoteGitError("foo bar"),
            parse_git_hangup(
                "http://",
                HangupException(
                    [b"remote: =======", b"remote: foo bar", b"remote: ======"]
                ),
            ),
        )

    def test_permission_denied(self):
        self.assertEqual(
            PermissionDenied(
                "http://", "You are not allowed to push code to this project."
            ),
            parse_git_hangup(
                "http://",
                HangupException(
                    [
                        b"=======",
                        b"You are not allowed to push code to this project.",
                        b"",
                        b"======",
                    ]
                ),
            ),
        )

    def test_notbrancherror_yet(self):
        self.assertEqual(
            NotBranchError(
                "http://", "A repository for this project does not exist yet."
            ),
            parse_git_hangup(
                "http://",
                HangupException(
                    [
                        b"=======",
                        b"",
                        b"A repository for this project does not exist yet.",
                        b"",
                        b"======",
                    ]
                ),
            ),
        )


class TestRemoteGitBranchFormat(TestCase):
    def setUp(self):
        super().setUp()
        self.format = RemoteGitBranchFormat()

    def test_get_format_description(self):
        self.assertEqual("Remote Git Branch", self.format.get_format_description())

    def test_get_network_name(self):
        self.assertEqual(b"git", self.format.network_name())

    def test_supports_tags(self):
        self.assertTrue(self.format.supports_tags())


class TestRemoteGitBranch(TestCaseWithTransport):
    _test_needs_features = [ExecutableFeature("git")]

    def setUp(self):
        TestCaseWithTransport.setUp(self)
        self.remote_real = GitRepo.init("remote", mkdir=True)
        self.remote_url = "git://{}/".format(os.path.abspath(self.remote_real.path))
        self.permit_url(self.remote_url)

    def test_set_last_revision_info(self):
        c1 = self.remote_real.get_worktree().commit(
            message=b"message 1",
            committer=b"committer <committer@example.com>",
            author=b"author <author@example.com>",
            ref=b"refs/heads/newbranch",
        )
        c2 = self.remote_real.get_worktree().commit(
            message=b"message 2",
            committer=b"committer <committer@example.com>",
            author=b"author <author@example.com>",
            ref=b"refs/heads/newbranch",
        )

        remote = ControlDir.open(self.remote_url)
        newbranch = remote.open_branch("newbranch")
        self.assertEqual(
            newbranch.lookup_foreign_revision_id(c2), newbranch.last_revision()
        )
        newbranch.set_last_revision_info(1, newbranch.lookup_foreign_revision_id(c1))
        self.assertEqual(c1, self.remote_real.refs[b"refs/heads/newbranch"])
        self.assertEqual(
            newbranch.last_revision(), newbranch.lookup_foreign_revision_id(c1)
        )


class FetchFromRemoteTestBase:
    _test_needs_features = [ExecutableFeature("git")]

    _to_format: str

    def setUp(self):
        TestCaseWithTransport.setUp(self)
        self.remote_real = GitRepo.init("remote", mkdir=True)
        self.remote_url = "git://{}/".format(os.path.abspath(self.remote_real.path))
        self.permit_url(self.remote_url)

    def test_sprout_simple(self):
        self.remote_real.get_worktree().commit(
            message=b"message",
            committer=b"committer <committer@example.com>",
            author=b"author <author@example.com>",
        )

        remote = ControlDir.open(self.remote_url)
        self.make_controldir("local", format=self._to_format)
        local = remote.sprout("local")
        self.assertEqual(
            default_mapping.revision_id_foreign_to_bzr(self.remote_real.head()),
            local.open_branch().last_revision(),
        )

    def test_sprout_submodule_invalid(self):
        self.sub_real = GitRepo.init("sub", mkdir=True)
        self.sub_real.get_worktree().commit(
            message=b"message in sub",
            committer=b"committer <committer@example.com>",
            author=b"author <author@example.com>",
        )

        self.sub_real.clone("remote/nested")
        self.remote_real.get_worktree().stage("nested")
        self.permit_url(urljoin(self.remote_url, "../sub"))
        self.assertIn(b"nested", self.remote_real.open_index())
        self.remote_real.get_worktree().commit(
            message=b"message",
            committer=b"committer <committer@example.com>",
            author=b"author <author@example.com>",
        )

        remote = ControlDir.open(self.remote_url)
        self.make_controldir("local", format=self._to_format)
        local = remote.sprout("local")
        self.assertEqual(
            default_mapping.revision_id_foreign_to_bzr(self.remote_real.head()),
            local.open_branch().last_revision(),
        )
        self.assertRaises(
            MissingNestedTree, local.open_workingtree().get_nested_tree, "nested"
        )

    def test_sprout_submodule_relative(self):
        self.sub_real = GitRepo.init("sub", mkdir=True)
        self.sub_real.get_worktree().commit(
            message=b"message in sub",
            committer=b"committer <committer@example.com>",
            author=b"author <author@example.com>",
        )

        with open("remote/.gitmodules", "w") as f:
            f.write("""
[submodule "lala"]
\tpath = nested
\turl = ../sub/.git
""")
        self.remote_real.get_worktree().stage(".gitmodules")
        self.sub_real.clone("remote/nested")
        self.remote_real.get_worktree().stage("nested")
        self.permit_url(urljoin(self.remote_url, "../sub"))
        self.assertIn(b"nested", self.remote_real.open_index())
        self.remote_real.get_worktree().commit(
            message=b"message",
            committer=b"committer <committer@example.com>",
            author=b"author <author@example.com>",
        )

        remote = ControlDir.open(self.remote_url)
        self.make_controldir("local", format=self._to_format)
        local = remote.sprout("local")
        self.assertEqual(
            default_mapping.revision_id_foreign_to_bzr(self.remote_real.head()),
            local.open_branch().last_revision(),
        )
        self.assertEqual(
            default_mapping.revision_id_foreign_to_bzr(self.sub_real.head()),
            local.open_workingtree().get_nested_tree("nested").last_revision(),
        )

    def test_sprout_with_tags(self):
        c1 = self.remote_real.get_worktree().commit(
            message=b"message",
            committer=b"committer <committer@example.com>",
            author=b"author <author@example.com>",
        )
        c2 = self.remote_real.get_worktree().commit(
            message=b"another commit",
            committer=b"committer <committer@example.com>",
            author=b"author <author@example.com>",
            ref=b"refs/tags/another",
        )
        self.remote_real.refs[b"refs/tags/blah"] = self.remote_real.head()

        remote = ControlDir.open(self.remote_url)
        self.make_controldir("local", format=self._to_format)
        local = remote.sprout("local")
        local_branch = local.open_branch()
        self.assertEqual(
            default_mapping.revision_id_foreign_to_bzr(c1), local_branch.last_revision()
        )
        self.assertEqual(
            {
                "blah": local_branch.last_revision(),
                "another": default_mapping.revision_id_foreign_to_bzr(c2),
            },
            local_branch.tags.get_tag_dict(),
        )

    def test_sprout_with_annotated_tag(self):
        c1 = self.remote_real.get_worktree().commit(
            message=b"message",
            committer=b"committer <committer@example.com>",
            author=b"author <author@example.com>",
        )
        c2 = self.remote_real.get_worktree().commit(
            message=b"another commit",
            committer=b"committer <committer@example.com>",
            author=b"author <author@example.com>",
            ref=b"refs/heads/another",
        )
        porcelain.tag_create(
            self.remote_real,
            tag=b"blah",
            author=b"author <author@example.com>",
            objectish=c2,
            tag_time=int(time.time()),
            tag_timezone=0,
            annotated=True,
            message=b"Annotated tag",
        )

        remote = ControlDir.open(self.remote_url)
        self.make_controldir("local", format=self._to_format)
        local = remote.sprout(
            "local", revision_id=default_mapping.revision_id_foreign_to_bzr(c1)
        )
        local_branch = local.open_branch()
        self.assertEqual(
            default_mapping.revision_id_foreign_to_bzr(c1), local_branch.last_revision()
        )
        self.assertEqual(
            {"blah": default_mapping.revision_id_foreign_to_bzr(c2)},
            local_branch.tags.get_tag_dict(),
        )

    def test_sprout_with_annotated_tag_unreferenced(self):
        c1 = self.remote_real.get_worktree().commit(
            message=b"message",
            committer=b"committer <committer@example.com>",
            author=b"author <author@example.com>",
        )
        self.remote_real.get_worktree().commit(
            message=b"another commit",
            committer=b"committer <committer@example.com>",
            author=b"author <author@example.com>",
        )
        porcelain.tag_create(
            self.remote_real,
            tag=b"blah",
            author=b"author <author@example.com>",
            objectish=c1,
            tag_time=int(time.time()),
            tag_timezone=0,
            annotated=True,
            message=b"Annotated tag",
        )

        remote = ControlDir.open(self.remote_url)
        self.make_controldir("local", format=self._to_format)
        local = remote.sprout(
            "local", revision_id=default_mapping.revision_id_foreign_to_bzr(c1)
        )
        local_branch = local.open_branch()
        self.assertEqual(
            default_mapping.revision_id_foreign_to_bzr(c1), local_branch.last_revision()
        )
        self.assertEqual(
            {"blah": default_mapping.revision_id_foreign_to_bzr(c1)},
            local_branch.tags.get_tag_dict(),
        )


class FetchFromRemoteToBzrTests(FetchFromRemoteTestBase, TestCaseWithTransport):
    _to_format = "2a"


class FetchFromRemoteToGitTests(FetchFromRemoteTestBase, TestCaseWithTransport):
    _to_format = "git"


class PushToRemoteBase:
    _test_needs_features = [ExecutableFeature("git")]

    _from_format: str

    def setUp(self):
        TestCaseWithTransport.setUp(self)
        self.remote_real = GitRepo.init("remote", mkdir=True)
        self.remote_url = "git://{}/".format(os.path.abspath(self.remote_real.path))
        self.permit_url(self.remote_url)

    def test_push_branch_new(self):
        remote = ControlDir.open(self.remote_url)
        wt = self.make_branch_and_tree("local", format=self._from_format)
        self.build_tree(["local/blah"])
        wt.add(["blah"])
        wt.commit("blah")

        if self._from_format == "git":
            result = remote.push_branch(wt.branch, name="newbranch")
        else:
            result = remote.push_branch(wt.branch, lossy=True, name="newbranch")

        self.assertEqual(0, result.old_revno)
        if self._from_format == "git":
            self.assertEqual(1, result.new_revno)
        else:
            self.assertIs(None, result.new_revno)

        result.report(BytesIO())

        self.assertEqual(
            {
                b"refs/heads/newbranch": self.remote_real.refs[b"refs/heads/newbranch"],
            },
            self.remote_real.get_refs(),
        )

    def test_push_branch_symref(self):
        cfg = self.remote_real.get_config()
        cfg.set((b"core",), b"bare", True)
        cfg.write_to_path()
        self.remote_real.refs.set_symbolic_ref(b"HEAD", b"refs/heads/master")
        self.remote_real.get_worktree().commit(
            message=b"message",
            committer=b"committer <committer@example.com>",
            author=b"author <author@example.com>",
            ref=b"refs/heads/master",
        )
        remote = ControlDir.open(self.remote_url)
        wt = self.make_branch_and_tree("local", format=self._from_format)
        self.build_tree(["local/blah"])
        wt.add(["blah"])
        wt.commit("blah")

        if self._from_format == "git":
            result = remote.push_branch(wt.branch, overwrite=True)
        else:
            result = remote.push_branch(wt.branch, lossy=True, overwrite=True)

        self.assertEqual(None, result.old_revno)
        if self._from_format == "git":
            self.assertEqual(1, result.new_revno)
        else:
            self.assertIs(None, result.new_revno)

        result.report(BytesIO())

        self.assertEqual(
            {
                b"HEAD": self.remote_real.refs[b"refs/heads/master"],
                b"refs/heads/master": self.remote_real.refs[b"refs/heads/master"],
            },
            self.remote_real.get_refs(),
        )

    def test_push_branch_new_with_tags(self):
        remote = ControlDir.open(self.remote_url)
        builder = self.make_branch_builder("local", format=self._from_format)
        builder.start_series()
        rev_1 = builder.build_snapshot(
            None,
            [
                ("add", ("", None, "directory", "")),
                ("add", ("filename", None, "file", b"content")),
            ],
        )
        rev_2 = builder.build_snapshot(
            [rev_1], [("modify", ("filename", b"new-content\n"))]
        )
        builder.build_snapshot(
            [rev_1], [("modify", ("filename", b"new-new-content\n"))]
        )
        builder.finish_series()
        branch = builder.get_branch()
        try:
            branch.tags.set_tag("atag", rev_2)
        except TagsNotSupported:
            raise TestNotApplicable("source format does not support tags")

        branch.get_config_stack().set("branch.fetch_tags", True)
        if self._from_format == "git":
            result = remote.push_branch(branch, name="newbranch")
        else:
            result = remote.push_branch(branch, lossy=True, name="newbranch")

        self.assertEqual(0, result.old_revno)
        if self._from_format == "git":
            self.assertEqual(2, result.new_revno)
        else:
            self.assertIs(None, result.new_revno)

        result.report(BytesIO())

        self.assertEqual(
            {b"refs/heads/newbranch", b"refs/tags/atag"},
            set(self.remote_real.get_refs().keys()),
        )

    def test_push(self):
        self.remote_real.get_worktree().commit(
            message=b"message",
            committer=b"committer <committer@example.com>",
            author=b"author <author@example.com>",
        )

        remote = ControlDir.open(self.remote_url)
        self.make_controldir("local", format=self._from_format)
        local = remote.sprout("local")
        self.build_tree(["local/blah"])
        wt = local.open_workingtree()
        wt.add(["blah"])
        revid = wt.commit("blah")
        wt.branch.tags.set_tag("sometag", revid)
        wt.branch.get_config_stack().set("branch.fetch_tags", True)

        if self._from_format == "git":
            result = wt.branch.push(remote.create_branch("newbranch"))
        else:
            result = wt.branch.push(remote.create_branch("newbranch"), lossy=True)

        self.assertEqual(0, result.old_revno)
        self.assertEqual(2, result.new_revno)

        result.report(BytesIO())

        self.assertEqual(
            {
                b"refs/heads/master": self.remote_real.head(),
                b"HEAD": self.remote_real.head(),
                b"refs/heads/newbranch": self.remote_real.refs[b"refs/heads/newbranch"],
                b"refs/tags/sometag": self.remote_real.refs[b"refs/heads/newbranch"],
            },
            self.remote_real.get_refs(),
        )

    def test_push_diverged(self):
        c1 = self.remote_real.get_worktree().commit(
            message=b"message",
            committer=b"committer <committer@example.com>",
            author=b"author <author@example.com>",
            ref=b"refs/heads/newbranch",
        )

        remote = ControlDir.open(self.remote_url)
        wt = self.make_branch_and_tree("local", format=self._from_format)
        self.build_tree(["local/blah"])
        wt.add(["blah"])
        wt.commit("blah")

        newbranch = remote.open_branch("newbranch")
        if self._from_format == "git":
            self.assertRaises(DivergedBranches, wt.branch.push, newbranch)
        else:
            self.assertRaises(DivergedBranches, wt.branch.push, newbranch, lossy=True)

        self.assertEqual({b"refs/heads/newbranch": c1}, self.remote_real.get_refs())

        if self._from_format == "git":
            wt.branch.push(newbranch, overwrite=True)
        else:
            wt.branch.push(newbranch, lossy=True, overwrite=True)

        self.assertNotEqual(c1, self.remote_real.refs[b"refs/heads/newbranch"])


class PushToRemoteFromBzrTests(PushToRemoteBase, TestCaseWithTransport):
    _from_format = "2a"


class PushToRemoteFromGitTests(PushToRemoteBase, TestCaseWithTransport):
    _from_format = "git"


class RemoteControlDirTests(TestCaseWithTransport):
    _test_needs_features = [ExecutableFeature("git")]

    def setUp(self):
        TestCaseWithTransport.setUp(self)
        self.remote_real = GitRepo.init("remote", mkdir=True)
        self.remote_url = "git://{}/".format(os.path.abspath(self.remote_real.path))
        self.permit_url(self.remote_url)

    def test_remove_branch(self):
        self.remote_real.get_worktree().commit(
            message=b"message",
            committer=b"committer <committer@example.com>",
            author=b"author <author@example.com>",
        )
        self.remote_real.get_worktree().commit(
            message=b"another commit",
            committer=b"committer <committer@example.com>",
            author=b"author <author@example.com>",
            ref=b"refs/heads/blah",
        )

        remote = ControlDir.open(self.remote_url)
        remote.destroy_branch(name="blah")
        self.assertEqual(
            self.remote_real.get_refs(),
            {
                b"refs/heads/master": self.remote_real.head(),
                b"HEAD": self.remote_real.head(),
            },
        )

    def test_list_branches(self):
        self.remote_real.get_worktree().commit(
            message=b"message",
            committer=b"committer <committer@example.com>",
            author=b"author <author@example.com>",
        )
        self.remote_real.get_worktree().commit(
            message=b"another commit",
            committer=b"committer <committer@example.com>",
            author=b"author <author@example.com>",
            ref=b"refs/heads/blah",
        )

        remote = ControlDir.open(self.remote_url)
        self.assertEqual({"master", "blah"}, {b.name for b in remote.list_branches()})

    def test_get_branches(self):
        self.remote_real.get_worktree().commit(
            message=b"message",
            committer=b"committer <committer@example.com>",
            author=b"author <author@example.com>",
        )
        self.remote_real.get_worktree().commit(
            message=b"another commit",
            committer=b"committer <committer@example.com>",
            author=b"author <author@example.com>",
            ref=b"refs/heads/blah",
        )

        remote = ControlDir.open(self.remote_url)
        self.assertEqual(
            {"": "master", "blah": "blah", "master": "master"},
            {n: b.name for (n, b) in remote.get_branches().items()},
        )
        self.assertEqual({"", "blah", "master"}, set(remote.branch_names()))

    def test_remove_tag(self):
        self.remote_real.get_worktree().commit(
            message=b"message",
            committer=b"committer <committer@example.com>",
            author=b"author <author@example.com>",
        )
        self.remote_real.get_worktree().commit(
            message=b"another commit",
            committer=b"committer <committer@example.com>",
            author=b"author <author@example.com>",
            ref=b"refs/tags/blah",
        )

        remote = ControlDir.open(self.remote_url)
        remote_branch = remote.open_branch()
        remote_branch.tags.delete_tag("blah")
        self.assertRaises(NoSuchTag, remote_branch.tags.delete_tag, "blah")
        self.assertEqual(
            self.remote_real.get_refs(),
            {
                b"refs/heads/master": self.remote_real.head(),
                b"HEAD": self.remote_real.head(),
            },
        )

    def test_set_tag(self):
        c1 = self.remote_real.get_worktree().commit(
            message=b"message",
            committer=b"committer <committer@example.com>",
            author=b"author <author@example.com>",
        )
        self.remote_real.get_worktree().commit(
            message=b"another commit",
            committer=b"committer <committer@example.com>",
            author=b"author <author@example.com>",
        )

        remote = ControlDir.open(self.remote_url)
        remote.open_branch().tags.set_tag(
            b"blah", default_mapping.revision_id_foreign_to_bzr(c1)
        )
        self.assertEqual(
            self.remote_real.get_refs(),
            {
                b"refs/heads/master": self.remote_real.head(),
                b"refs/tags/blah": c1,
                b"HEAD": self.remote_real.head(),
            },
        )

    def test_annotated_tag(self):
        self.remote_real.get_worktree().commit(
            message=b"message",
            committer=b"committer <committer@example.com>",
            author=b"author <author@example.com>",
        )
        c2 = self.remote_real.get_worktree().commit(
            message=b"another commit",
            committer=b"committer <committer@example.com>",
            author=b"author <author@example.com>",
        )

        porcelain.tag_create(
            self.remote_real,
            tag=b"blah",
            author=b"author <author@example.com>",
            objectish=c2,
            tag_time=int(time.time()),
            tag_timezone=0,
            annotated=True,
            message=b"Annotated tag",
        )

        remote = ControlDir.open(self.remote_url)
        remote_branch = remote.open_branch()
        self.assertEqual(
            {"blah": default_mapping.revision_id_foreign_to_bzr(c2)},
            remote_branch.tags.get_tag_dict(),
        )

    def test_get_branch_reference(self):
        self.remote_real.get_worktree().commit(
            message=b"message",
            committer=b"committer <committer@example.com>",
            author=b"author <author@example.com>",
        )
        self.remote_real.get_worktree().commit(
            message=b"another commit",
            committer=b"committer <committer@example.com>",
            author=b"author <author@example.com>",
        )

        remote = ControlDir.open(self.remote_url)
        self.assertEqual(
            remote.user_url.rstrip("/") + ",branch=master",
            remote.get_branch_reference(""),
        )
        self.assertEqual(None, remote.get_branch_reference("master"))

    def test_get_branch_nick(self):
        self.remote_real.get_worktree().commit(
            message=b"message",
            committer=b"committer <committer@example.com>",
            author=b"author <author@example.com>",
        )
        remote = ControlDir.open(self.remote_url)
        self.assertEqual("master", remote.open_branch().nick)


class GitUrlAndPathFromTransportTests(TestCase):
    def test_file(self):
        split_url = _git_url_and_path_from_transport("file:///home/blah")
        self.assertEqual(split_url.scheme, "file")
        self.assertEqual(split_url.path, "/home/blah")

    def test_file_segment_params(self):
        split_url = _git_url_and_path_from_transport("file:///home/blah,branch=master")
        self.assertEqual(split_url.scheme, "file")
        self.assertEqual(split_url.path, "/home/blah")

    def test_git_smart(self):
        split_url = _git_url_and_path_from_transport(
            "git://github.com/dulwich/dulwich,branch=master"
        )
        self.assertEqual(split_url.scheme, "git")
        self.assertEqual(split_url.path, "/dulwich/dulwich")

    def test_https(self):
        split_url = _git_url_and_path_from_transport(
            "https://github.com/dulwich/dulwich"
        )
        self.assertEqual(split_url.scheme, "https")
        self.assertEqual(split_url.path, "/dulwich/dulwich")

    def test_https_segment_params(self):
        split_url = _git_url_and_path_from_transport(
            "https://github.com/dulwich/dulwich,branch=master"
        )
        self.assertEqual(split_url.scheme, "https")
        self.assertEqual(split_url.path, "/dulwich/dulwich")


class RemoteRevisionTreeTests(TestCaseWithTransport):
    _test_needs_features = [ExecutableFeature("git")]

    def setUp(self):
        TestCaseWithTransport.setUp(self)
        self.remote_real = GitRepo.init("remote", mkdir=True)
        self.remote_url = "git://{}/".format(os.path.abspath(self.remote_real.path))
        self.permit_url(self.remote_url)
        self.remote_real.get_worktree().commit(
            message=b"message",
            committer=b"committer <committer@example.com>",
            author=b"author <author@example.com>",
        )

    def test_open(self):
        br = Branch.open(self.remote_url)
        t = br.basis_tree()
        self.assertIsInstance(t, GitRemoteRevisionTree)
        self.assertRaises(GitSmartRemoteNotSupported, t.is_versioned, "la")
        self.assertRaises(GitSmartRemoteNotSupported, t.has_filename, "la")
        self.assertRaises(GitSmartRemoteNotSupported, t.get_file_text, "la")
        self.assertRaises(GitSmartRemoteNotSupported, t.list_files, "la")

    def test_archive(self):
        br = Branch.open(self.remote_url)
        t = br.basis_tree()
        chunks = list(t.archive("tgz", "foo.tar.gz"))
        with gzip.GzipFile(fileobj=BytesIO(b"".join(chunks))) as g:
            self.assertEqual("", g.name)

    def test_archive_unsupported(self):
        # archive is not supported over HTTP, so simulate that
        br = Branch.open(self.remote_url)
        t = br.basis_tree()

        def raise_unsupp(*args, **kwargs):
            raise GitSmartRemoteNotSupported(raise_unsupp, None)

        self.overrideAttr(t._repository.controldir._client, "archive", raise_unsupp)
        self.assertRaises(GitSmartRemoteNotSupported, t.archive, "tgz", "foo.tar.gz")
