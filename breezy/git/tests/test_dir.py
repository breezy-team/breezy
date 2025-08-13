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

from dulwich.repo import Repo as GitRepo

from ... import controldir, errors, urlutils
from ...transport import get_transport
from .. import dir, tests, workingtree


class TestGitDir(tests.TestCaseInTempDir):
    def test_get_head_branch_reference(self):
        GitRepo.init(".")

        gd = controldir.ControlDir.open(".")
        self.assertEqual(
            f"{urlutils.local_path_to_url(os.path.abspath('.'))},branch=master",
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
        worktree = r.get_worktree()
        worktree.do_commit(message=b"message", ref=b"refs/heads/foo/bar")
        gd = controldir.ControlDir.open(".")
        self.assertRaises(errors.NotBranchError, gd.open_branch, "foo")

    def test_open_workingtree(self):
        r = GitRepo.init(".")
        worktree = r.get_worktree()
        worktree.do_commit(message=b"message")

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
