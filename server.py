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

from bzrlib.bzrdir import BzrDir
from bzrlib.repository import Repository

from bzrlib.plugins.git.fetch import import_git_objects
from bzrlib.plugins.git.mapping import default_mapping

from dulwich.server import Backend
from dulwich.pack import Pack, PackData, write_pack_index_v2
from dulwich.objects import ShaFile

import os, tempfile

class BzrBackend(Backend):

    def __init__(self, directory):
        self.directory = directory
        self.mapping = default_mapping

    def get_refs(self):
        """ return a dict of all tags and branches in repository (and shas) """
        return {}

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

