#!/usr/bin/env python
# vim: expandtab

# Copyright (C) 2011 Jelmer Vernooij <jelmer@apache.org>

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

from cStringIO import StringIO
import os

from dulwich.repo import Repo

from ....tests import (
    TestCaseWithTransport,
    TestSkipped,
    )

from ..object_store import get_object_store
from ..git_remote_helper import (
    RemoteHelper,
    open_local_dir,
    fastexporter,
    fetch,
    )


def map_to_git_sha1(dir, bzr_revid):
    object_store = get_object_store(dir.open_repository())
    with object_store.lock_read():
        return object_store._lookup_revision_sha1(bzr_revid)


class OpenLocalDirTests(TestCaseWithTransport):

    def test_from_env(self):
        self.make_branch_and_tree('bla', format='git')
        self.overrideEnv('GIT_DIR', os.path.join(self.test_dir, 'bla'))
        open_local_dir()

    def test_from_env_dir(self):
        self.make_branch_and_tree('bla', format='git')
        self.overrideEnv('GIT_DIR', os.path.join(self.test_dir, 'bla', '.git'))
        open_local_dir()

    def test_from_dir(self):
        self.make_branch_and_tree('.', format='git')
        open_local_dir()


class FetchTests(TestCaseWithTransport):

    def setUp(self):
        super(FetchTests, self).setUp()
        self.local_dir = self.make_branch_and_tree('local', format='git').controldir
        self.remote_tree = self.make_branch_and_tree('remote')
        self.remote_dir = self.remote_tree.controldir
        self.shortname = 'bzr'

    def fetch(self, wants):
        outf = StringIO()
        fetch(outf, wants, self.shortname, self.remote_dir, self.local_dir)
        return outf.getvalue()

    def test_no_wants(self):
        r = self.fetch([])
        self.assertEquals("\n", r)

    def test_simple(self):
        self.build_tree(['remote/foo'])
        self.remote_tree.add("foo")
        revid = self.remote_tree.commit("msg")
        git_sha1 = map_to_git_sha1(self.remote_dir, revid)
        out = self.fetch([(git_sha1, 'HEAD')])
        self.assertEquals(out, "\n")
        r = Repo('local')
        self.assertTrue(git_sha1 in r.object_store)
        self.assertEquals({
            'HEAD': '0000000000000000000000000000000000000000',
            'refs/heads/master': '0000000000000000000000000000000000000000',
            }, r.get_refs())


class RemoteHelperTests(TestCaseWithTransport):

    def setUp(self):
        super(RemoteHelperTests, self).setUp()
        self.local_dir = self.make_branch_and_tree('local', format='git').controldir
        self.remote_tree = self.make_branch_and_tree('remote')
        self.remote_dir = self.remote_tree.controldir
        self.shortname = 'bzr'
        self.helper = RemoteHelper(self.local_dir, self.shortname, self.remote_dir)

    def test_capabilities(self):
        f = StringIO()
        self.helper.cmd_capabilities(f, [])
        capabs = f.getvalue()
        base = "fetch\noption\npush\n"
        self.assertTrue(capabs in (base+"\n", base+"import\n\n"), capabs)

    def test_option(self):
        f = StringIO()
        self.helper.cmd_option(f, [])
        self.assertEquals("unsupported\n", f.getvalue())

    def test_list_basic(self):
        f = StringIO()
        self.helper.cmd_list(f, [])
        self.assertEquals(
            '0000000000000000000000000000000000000000 HEAD\n\n',
            f.getvalue())

    def test_import(self):
        if fastexporter is None:
            raise TestSkipped("bzr-fastimport not available")
        self.build_tree_contents([("remote/afile", "somecontent")])
        self.remote_tree.add(["afile"])
        self.remote_tree.commit("A commit message", timestamp=1330445983,
            timezone=0, committer='Somebody <jrandom@example.com>')
        f = StringIO()
        self.helper.cmd_import(f, ["import", "refs/heads/master"])
        self.assertEquals(
            'commit refs/heads/master\n'
            'mark :1\n'
            'committer Somebody <jrandom@example.com> 1330445983 +0000\n'
            'data 16\n'
            'A commit message\n'
            'M 644 inline afile\n'
            'data 11\n'
            'somecontent\n',
            f.getvalue())
