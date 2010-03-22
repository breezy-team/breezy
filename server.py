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

import os
import tempfile

from dulwich.server import TCPGitServer

from bzrlib.bzrdir import (
    BzrDir,
    BzrDirFormat,
    )
from bzrlib.repository import (
    Repository,
    )

from bzrlib.plugins.git.fetch import (
    import_git_objects,
    BazaarObjectStore,
    )
from bzrlib.plugins.git.mapping import (
    default_mapping,
    )
from bzrlib.plugins.git.object_store import (
    get_object_store
    )

from dulwich.server import (
    Backend,
    )
from dulwich.pack import (
    Pack,
    PackData,
    write_pack_index_v2,
    )
from dulwich.objects import (
    ShaFile,
    sha_to_hex,
    hex_to_sha,
    )

class BzrBackend(Backend):

    def __init__(self, transport):
        self.transport = transport
        self.mapping = default_mapping

    def get_refs(self):
        """ return a dict of all tags and branches in repository (and shas) """
        ret = {}
        repo_dir = BzrDir.open_from_transport(self.transport)
        repo = repo_dir.find_repository()
        repo.lock_read()
        try:
            store = get_object_store(repo)
            branch = None
            for branch in repo.find_branches(using=True):
                #FIXME: Look for 'master' or 'trunk' in here, and set HEAD accordingly...
                #FIXME: Need to get branch path relative to its repository and use this instead of nick
                ret["refs/heads/"+branch.nick] = store._lookup_revision_sha1(branch.last_revision())
            if 'HEAD' not in ret and branch:
                ret['HEAD'] = store._lookup_revision_sha1(branch.last_revision())
        finally:
            repo.unlock()
        return ret

    def apply_pack(self, refs, read):
        """apply pack from client to current repository"""

        fd, path = tempfile.mkstemp(suffix=".pack")
        f = os.fdopen(fd, 'w')
        f.write(read())
        f.close()

        p = PackData(path)
        entries = p.sorted_entries()
        heads = []
        for e in entries:
            sha = e[0]
            offset = e[1]
            t, o = p.get_object_at (offset)
            if t == 1 or t == 4:
                heads.append(sha)
        write_pack_index_v2(path[:-5]+".idx", entries, p.calculate_checksum())

        repo_dir = BzrDir.open_from_transport(self.transport)
        target = repo_dir.find_repository()

        objects = {}
        for tup in p.iterobjects():
            obj_type, obj = p.get_object_at (tup[0])
            if obj_type in range(1, 4):
                sf = ShaFile.from_raw_string (obj_type, obj)
                objects[hex_to_sha(sf.id)] = sf

        target.lock_write()
        try:
            target.start_write_group()
            try:
                import_git_objects(target, self.mapping, objects,
                                   BazaarObjectStore (target, self.mapping),
                                   heads)
            except:
                target.abort_write_group()
                raise
            else:
                target.commit_write_group()
        finally:
            target.unlock()

        for oldsha, sha, ref in refs:
            if ref[:11] == 'refs/heads/':
                branch_nick = ref[11:]
                transport = self.transport.clone(branch_nick)

                try:
                    target_dir = BzrDir.open_from_transport(transport)
                except:
                    format = BzrDirFormat.get_default_format()
                    format.initialize_on_transport(transport)

                try:
                    target_branch = target_dir.open_branch()
                except:
                    target_branch = target_dir.create_branch()

                rev_id = self.mapping.revision_id_foreign_to_bzr(sha)
                target_branch.generate_revision_history(rev_id)

    def fetch_objects(self, determine_wants, graph_walker, progress):
        """ yield git objects to send to client """
        bzrdir = BzrDir.open_from_transport(self.transport)
        repo = bzrdir.find_repository()

        # If this is a Git repository, just use the existing fetch_objects implementation.
        if getattr(repo, "fetch_objects", None) is not None:
            return repo.fetch_objects(determine_wants, graph_walker, None, progress)[0]

        wants = determine_wants(self.get_refs())
        graph_walker.reset()
        repo.lock_read()
        store = BazaarObjectStore(repo)
        have = store.find_common_revisions(graph_walker)
        missing_sha1s = store.find_missing_objects(have, wants, progress)
        return store.iter_shas(missing_sha1s)


def serve_git(transport, host=None, port=None, inet=False):
    backend = BzrBackend(transport)

    if host is None:
        host = ''
    if port:
        server = TCPGitServer(backend, host, port)
    else:
        server = TCPGitServer(backend, host)
    server.serve_forever()
