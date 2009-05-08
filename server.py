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
import stat
import tempfile

from bzrlib.bzrdir import (
    BzrDir,
    )
from bzrlib.inventory import (
    InventoryDirectory,
    InventoryFile,
    )
from bzrlib.osutils import (
    splitpath,
    )
from bzrlib.repository import (
    Repository,
    )

from bzrlib.plugins.git.converter import (
    BazaarObjectStore,
    )
from bzrlib.plugins.git.fetch import (
    import_git_objects,
    )
from bzrlib.plugins.git.mapping import (
    default_mapping,
    inventory_to_tree_and_blobs,
    revision_to_commit,
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
    Blob,
    Commit,
    ShaFile,
    Tree,
    )


class BzrBackend(Backend):

    def __init__(self, directory):
        self.directory = directory
        self.mapping = default_mapping

    def get_refs(self):
        """ return a dict of all tags and branches in repository (and shas) """
        ret = {}
        repo_dir = BzrDir.open(self.directory)
        repo = repo_dir.open_repository()
        branch = None
        for branch in repo.find_branches(using=True):
            #FIXME: Look for 'master' or 'trunk' in here, and set HEAD accordingly...
            #FIXME: Need to get branch path relative to its repository and use this instead of nick
            rev, mapping = self.mapping.revision_id_bzr_to_foreign(branch.last_revision())
            ret["refs/heads/"+branch.nick] = rev
        if 'HEAD' not in ret and branch:
            rev, mapping = self.mapping.revision_id_bzr_to_foreign(branch.last_revision())
            ret['HEAD'] = rev
        return ret

    def apply_pack(self, refs, read):
        """ apply pack from client to current repository """

        fd, path = tempfile.mkstemp(suffix=".pack")
        f = os.fdopen(fd, 'w')
        f.write(read())
        f.close()

        p = PackData(path)
        entries = p.sorted_entries()
        write_pack_index_v2(path[:-5]+".idx", entries, p.calculate_checksum())

        def get_objects():
            pack = Pack(path[:-5])
            for obj in pack.iterobjects():
                yield obj

        target = Repository.open(self.directory)

        target.lock_write()
        try:
            target.start_write_group()
            try:
                import_git_objects(target, self.mapping, iter(get_objects()))
            finally:
                target.commit_write_group()
        finally:
            target.unlock()

        for oldsha, sha, ref in refs:
            if ref[:11] == 'refs/heads/':
                branch_nick = ref[11:]

                try:
                    target_dir = BzrDir.open(self.directory + "/" + branch_nick)
                except:
                    target_dir = BzrDir.create(self.directory + "/" + branch_nick)

                try:
                    target_branch = target_dir.open_branch()
                except:
                    target_branch = target_dir.create_branch()

                rev_id = self.mapping.revision_id_foreign_to_bzr(sha)
                target_branch.generate_revision_history(rev_id)

    def fetch_objects(self, determine_wants, graph_walker, progress):
        """ yield git objects to send to client """
        repo = Repository.open(self.directory)

        # If this is a Git repository, just use the existing fetch_objects implementation.
        if getattr(repo, "fetch_objects", None) is not None:
            return repo.fetch_objects(determine_wants, graph_walker, None, progress)

        wants = determine_wants(self.get_refs())

        repo.lock_read()
        try:
            store = BazaarObjectStore(repo)
            missing_sha1s = store.find_missing_objects(wants, graphwalker, progress)
            return (len(missing_sha1s), iter(store.iter_shas(missing_sha1s)))
        finally:
            repo.unlock()
