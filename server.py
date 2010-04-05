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
from bzrlib.errors import (
    NotBranchError,
    )

from bzrlib.plugins.git.branch import (
    branch_name_to_ref,
    ref_to_branch_name,
    )
from bzrlib.plugins.git.mapping import (
    default_mapping,
    )
from bzrlib.plugins.git.object_store import (
    get_object_store
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

    def get_peeled(self, name):
        return self.get_refs()[name]

    def get_refs(self):
        """Return a dict of all tags and branches in repository (and shas) """
        ret = {}
        self.repo.lock_read()
        try:
            for branch in self.repo_dir.list_branches():
                ref = branch_name_to_ref(branch.name, "refs/heads/master")
                ret[ref] = self.object_store._lookup_revision_sha1(
                    branch.last_revision())
                assert type(ref) == str and type(ret[ref]) == str, \
                        "(%s) %r -> %r" % (branch.name, ref, ret[ref])

        finally:
            self.repo.unlock()
        return ret

    def set_refs(self, refs):
        for oldsha, sha, ref in refs:
            try:
                branch_name = ref_to_branch_name(ref)
            except ValueError:
                # FIXME: Cope with tags!
                continue
            try:
                target_branch = self.repo_dir.open_branch(branch_name)
            except NotBranchError:
                target_branch = self.repo.create_branch(branch_name)

            rev_id = self.mapping.revision_id_foreign_to_bzr(sha)
            target_branch.lock_write()
            try:
                target_branch.generate_revision_history(rev_id)
            finally:
                target_branch.unlock()

    def fetch_objects(self, determine_wants, graph_walker, progress,
        get_tagged=None):
        """ yield git objects to send to client """

        # If this is a Git repository, just use the existing fetch_objects implementation.
        if getattr(self.repo, "fetch_objects", None) is not None:
            return self.repo.fetch_objects(determine_wants, graph_walker, progress,
                get_tagged)

        wants = determine_wants(self.get_refs())
        self.repo.lock_read()
        try:
            have = self.object_store.find_common_revisions(graph_walker)
            return self.object_store.generate_pack_contents(have, wants, progress,
                get_tagged)
        finally:
            self.repo.unlock()


def serve_git(transport, host=None, port=None, inet=False):
    backend = BzrBackend(transport)

    if host is None:
        host = 'localhost'
    if port:
        server = TCPGitServer(backend, host, port)
    else:
        server = TCPGitServer(backend, host)
    server.serve_forever()
