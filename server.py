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
from bzrlib.repository import Repository, InterRepository

from bzrlib.plugins.git.mapping import default_mapping

from dulwich.server import Backend
from dulwich.repo import Repo

#FIXME: Shouldnt need these imports
import tempfile

class BzrBackend(Backend):

    def __init__(self, directory):
        self.directory = directory
        self.mapping = default_mapping

    def get_refs(self):
        """ return a dict of all tags and branches in repository (and shas) """
        return {}

    def apply_pack(self, refs, read):
        """ apply pack from client to current repository """

        # FIXME: Until we have a VirtualGitRepository, lets just stash it on disk
        source_path = tempfile.mkdtemp()
        Repo.init_bare(source_path)
        repo = Repo(source_path)
        f, commit = repo.object_store.add_pack()
        f.write(read())
        f.close()
        commit()
        for oldsha, sha, ref in refs:
            repo.set_ref(ref, sha)
        source_repos = Repository.open(source_path)
        # END FIXME

        target_repos = Repository.open(self.directory)

        source_repos.lock_read()
        try:
            inter = InterRepository.get(source_repos, target_repos)
            inter.fetch()
        finally:
            source_repos.unlock()

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

