# vim: expandtab

# Copyright (C) 2011-2018 Jelmer Vernooij <jelmer@jelmer.uk>

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

"""Tests for the git remote helper."""

import os
import subprocess
import sys
from io import BytesIO

from dulwich.repo import Repo

from ...tests import TestCaseWithTransport
from ...tests.features import PathFeature
from ..git_remote_helper import RemoteHelper, fetch, open_local_dir
from ..object_store import get_object_store
from . import FastimportFeature


def map_to_git_sha1(dir, bzr_revid):
    object_store = get_object_store(dir.open_repository())
    with object_store.lock_read():
        return object_store._lookup_revision_sha1(bzr_revid)


git_remote_bzr_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "git-remote-bzr")
)
git_remote_bzr_feature = PathFeature(git_remote_bzr_path)


class OpenLocalDirTests(TestCaseWithTransport):
    def test_from_env_dir(self):
        self.make_branch_and_tree("bla", format="git")
        self.overrideEnv("GIT_DIR", os.path.join(self.test_dir, "bla", ".git"))
        open_local_dir()

    def test_from_dir(self):
        self.make_branch_and_tree(".", format="git")
        open_local_dir()


class FetchTests(TestCaseWithTransport):
    def setUp(self):
        super().setUp()
        self.local_dir = self.make_branch_and_tree("local", format="git").controldir
        self.remote_tree = self.make_branch_and_tree("remote")
        self.remote_dir = self.remote_tree.controldir
        self.shortname = "bzr"

    def fetch(self, wants):
        outf = BytesIO()
        fetch(outf, wants, self.shortname, self.remote_dir, self.local_dir)
        return outf.getvalue()

    def test_no_wants(self):
        r = self.fetch([])
        self.assertEqual(b"\n", r)

    def test_simple(self):
        self.build_tree(["remote/foo"])
        self.remote_tree.add("foo")
        revid = self.remote_tree.commit("msg")
        git_sha1 = map_to_git_sha1(self.remote_dir, revid)
        out = self.fetch([(git_sha1, "HEAD")])
        self.assertEqual(out, b"\n")
        r = Repo("local")
        self.assertTrue(git_sha1 in r.object_store)
        self.assertEqual({}, r.get_refs())


class ExecuteRemoteHelperTests(TestCaseWithTransport):
    def test_run(self):
        self.requireFeature(git_remote_bzr_feature)
        local_dir = self.make_branch_and_tree("local", format="git").controldir
        local_path = local_dir.control_transport.local_abspath(".")
        remote_tree = self.make_branch_and_tree("remote")
        remote_dir = remote_tree.controldir
        env = dict(os.environ)
        env["GIT_DIR"] = local_path
        env["PYTHONPATH"] = ":".join(sys.path)
        p = subprocess.Popen(
            [sys.executable, git_remote_bzr_path, local_path, remote_dir.user_url],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        (out, err) = p.communicate(b"capabilities\n")
        lines = out.splitlines()
        self.assertIn(
            b"push", lines, "no 'push' in {!r}, error: {!r}".format(lines, err)
        )
        self.assertEqual(
            b"git-remote-bzr is experimental and has not been optimized "
            b"for performance. Use 'brz fast-export' and 'git fast-import' "
            b"for large repositories.\n",
            err,
        )


class RemoteHelperTests(TestCaseWithTransport):
    def setUp(self):
        super().setUp()
        self.local_dir = self.make_branch_and_tree("local", format="git").controldir
        self.remote_tree = self.make_branch_and_tree("remote")
        self.remote_dir = self.remote_tree.controldir
        self.shortname = "bzr"
        self.helper = RemoteHelper(self.local_dir, self.shortname, self.remote_dir)

    def test_capabilities(self):
        f = BytesIO()
        self.helper.cmd_capabilities(f, [])
        capabs = f.getvalue()
        base = b"fetch\noption\npush\n"
        self.assertTrue(
            capabs in (base + b"\n", base + b"import\nrefspec *:*\n\n"), capabs
        )

    def test_option(self):
        f = BytesIO()
        self.helper.cmd_option(f, [])
        self.assertEqual(b"unsupported\n", f.getvalue())

    def test_list_basic(self):
        f = BytesIO()
        self.helper.cmd_list(f, [])
        self.assertEqual(b"\n", f.getvalue())

    def test_import(self):
        self.requireFeature(FastimportFeature)
        self.build_tree_contents([("remote/afile", b"somecontent")])
        self.remote_tree.add(["afile"])
        self.remote_tree.commit(
            b"A commit message",
            timestamp=1330445983,
            timezone=0,
            committer=b"Somebody <jrandom@example.com>",
        )
        f = BytesIO()
        self.helper.cmd_import(f, ["import", "refs/heads/master"])
        self.assertEqual(
            b"reset refs/heads/master\n"
            b"commit refs/heads/master\n"
            b"mark :1\n"
            b"committer Somebody <jrandom@example.com> 1330445983 +0000\n"
            b"data 16\n"
            b"A commit message\n"
            b"M 644 inline afile\n"
            b"data 11\n"
            b"somecontent\n",
            f.getvalue(),
        )
