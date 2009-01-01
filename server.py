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
from bzrlib.osutils import relpath

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
        ret = {}
        repo_dir = BzrDir.open(self.directory)
        repo = repo_dir.open_repository()
        for branch in repo.find_branches(using=True):
            #FIXME: Need to get branch path relative to its repository and use this instead of nick
            ret["refs/heads/"+branch.nick] = self.mapping.revision_id_bzr_to_foreign(branch.last_revision())
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
        wants = determine_wants(self.get_refs())
        commits_to_send = set([self.mapping.revision_id_foreign_to_bzr(w) for w in wants])
        rev_done = set()

        repo = Repository.open(self.directory)
        
        repo.lock_read()
        try:
            have = graph_walker.next()
            while have:
                rev_done.add(have)
                if repo.has_revision(self.mapping.revision_id_foregin_to_bzr(sha)):
                    graph_walker.ack(have)
                have = graph_walker.next()

            while commits_to_send:
                commit = commits_to_send.pop(0)
                if commit in rev_done:
                    continue
                rev_done.add(commit)

                commits_to_send.update([rev for rev in commit.parent_ids if not rev in rev_done])

                # generate and yield blob, tree and commit objects now.
        finally:
            repo.unlock()
