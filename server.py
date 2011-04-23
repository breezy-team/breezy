# Copyright (C) 2008 Jelmer Vernooij
# Copyright (C) 2008 John Carr
# Copyright (C) 2008 Canonical Ltd
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

from dulwich.server import TCPGitServer

from bzrlib.bzrdir import (
    BzrDir,
    )

from bzrlib.plugins.git.mapping import (
    default_mapping,
    )
from bzrlib.plugins.git.object_store import (
    get_object_store
    )
from bzrlib.plugins.git.refs import (
    BazaarRefsContainer,
    )

from dulwich.server import (
    Backend,
    BackendRepo,
    )

class BzrBackend(Backend):
    """A git serve backend that can use a Bazaar repository."""

    def __init__(self, transport):
        self.transport = transport
        self.mapping = default_mapping

    def open_repository(self, path):
        # FIXME: More secure path sanitization
        return BzrBackendRepo(self.transport.clone(path.lstrip("/")),
            self.mapping)


class BzrBackendRepo(BackendRepo):

    def __init__(self, transport, mapping):
        self.transport = transport
        self.mapping = mapping
        self.repo_dir = BzrDir.open_from_transport(self.transport)
        self.repo = self.repo_dir.find_repository()
        self.object_store = get_object_store(self.repo)
        self.refs = BazaarRefsContainer(self.repo_dir, self.object_store)
        self._refs = self.refs.as_dict() # Much faster for now..

    def get_refs(self):
        return self._refs

    def get_peeled(self, name):
        return self.get_refs()[name]

    def fetch_objects(self, determine_wants, graph_walker, progress,
        get_tagged=None):
        """ yield git objects to send to client """

        wants = determine_wants(self.get_refs())
        self.object_store.lock_read()
        try:
            have = self.object_store.find_common_revisions(graph_walker)
            return self.object_store.generate_pack_contents(have, wants, progress,
                get_tagged)
        finally:
            self.object_store.unlock()


def serve_git(transport, host=None, port=None, inet=False):
    backend = BzrBackend(transport)

    if host is None:
        host = 'localhost'
    if port:
        server = TCPGitServer(backend, host, port)
    else:
        server = TCPGitServer(backend, host)
    server.serve_forever()
