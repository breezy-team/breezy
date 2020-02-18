# Copyright (C) 2011-2018 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""Test for git server."""

from dulwich.client import TCPGitClient
from dulwich.repo import Repo
import threading

from ...transport import transport_server_registry
from ...tests import (
    TestCase,
    TestCaseWithTransport,
    )

from ..server import (
    BzrBackend,
    BzrTCPGitServer,
    )


class TestPresent(TestCase):

    def test_present(self):
        # Just test that the server is registered.
        transport_server_registry.get('git')


class GitServerTestCase(TestCaseWithTransport):

    def start_server(self, t):
        backend = BzrBackend(t)
        server = BzrTCPGitServer(backend, 'localhost', port=0)
        self.addCleanup(server.shutdown)
        thread = threading.Thread(target=server.serve).start()
        self._server = server
        _, port = self._server.socket.getsockname()
        return port


class TestPlainFetch(GitServerTestCase):

    def test_fetch_from_native_git(self):
        wt = self.make_branch_and_tree('t', format='git')
        self.build_tree(['t/foo'])
        wt.add('foo')
        revid = wt.commit(message="some data")
        wt.branch.tags.set_tag("atag", revid)
        t = self.get_transport('t')
        port = self.start_server(t)
        c = TCPGitClient('localhost', port=port)
        gitrepo = Repo.init('gitrepo', mkdir=True)
        result = c.fetch('/', gitrepo)
        self.assertEqual(
            set(result.refs.keys()),
            set([b"refs/tags/atag", b'refs/heads/master', b"HEAD"]))

    def test_fetch_nothing(self):
        wt = self.make_branch_and_tree('t')
        self.build_tree(['t/foo'])
        wt.add('foo')
        revid = wt.commit(message="some data")
        wt.branch.tags.set_tag("atag", revid)
        t = self.get_transport('t')
        port = self.start_server(t)
        c = TCPGitClient('localhost', port=port)
        gitrepo = Repo.init('gitrepo', mkdir=True)
        result = c.fetch('/', gitrepo, determine_wants=lambda x: [])
        self.assertEqual(
            set(result.refs.keys()),
            set([b"refs/tags/atag", b"HEAD"]))

    def test_fetch_from_non_git(self):
        wt = self.make_branch_and_tree('t', format='bzr')
        self.build_tree(['t/foo'])
        wt.add('foo')
        revid = wt.commit(message="some data")
        wt.branch.tags.set_tag("atag", revid)
        t = self.get_transport('t')
        port = self.start_server(t)
        c = TCPGitClient('localhost', port=port)
        gitrepo = Repo.init('gitrepo', mkdir=True)
        result = c.fetch('/', gitrepo)
        self.assertEqual(
            set(result.refs.keys()),
            set([b"refs/tags/atag", b"HEAD"]))
