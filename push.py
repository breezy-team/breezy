# Copyright (C) 2009 Jelmer Vernooij <jelmer@samba.org>
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

"""Push implementation that simply prints message saying push is not supported."""

from bzrlib import (
    ui,
    )
from bzrlib.repository import (
    InterRepository,
    )

from bzrlib.plugins.git.errors import (
    NoPushSupport,
    )
from bzrlib.plugins.git.mapping import (
    inventory_to_tree_and_blobs,
    revision_to_commit,
    )
from bzrlib.plugins.git.repository import (
    GitRepository,
    GitRepositoryFormat,
    )

class InterToGitRepository(InterRepository):
    """InterRepository that copies into a Git repository."""

    _matching_repo_format = GitRepositoryFormat()

    @staticmethod
    def _get_repo_format_to_test():
        return None

    def copy_content(self, revision_id=None, pb=None):
        """See InterRepository.copy_content."""
        self.fetch(revision_id, pb, find_ghosts=False)

    def fetch(self, revision_id=None, pb=None, find_ghosts=False, 
            fetch_spec=None):
        raise NoPushSupport()

    def import_revision_gist(self, revid, parent_lookup):
        """Import the gist of a revision into this Git repository.

        """
        objects = []
        rev = self.source.get_revision(revid)
        for sha, object, path in inventory_to_tree_and_blobs(
                self.source.get_inventory(revid), self.source.texts, None):
            if path == "":
                tree_sha = sha
            objects.append((object, path))
        commit = revision_to_commit(rev, tree_sha, parent_lookup)
        objects.append((commit, None))
        self.target._git.object_store.add_objects(objects)
        return commit.sha().hexdigest()

    def missing_revisions(self, stop_revision=None, ghosts=False):
        if stop_revision is not None:
            ancestry = [x for x in self.source.get_ancestry(stop_revision) if x is not None]
        else:
            ancestry = self.source.all_revision_ids()
        missing = []
        graph = self.source.get_graph()
        for revid in graph.iter_topo_order(ancestry):
            if not self.target.has_revision(revid):
                missing.append(revid)
            elif not ghosts:
                break
        return missing

    def dfetch(self, stop_revision=None, fetch_ghosts=False):
        """Import the gist of the ancestry of a particular revision."""
        revidmap = {}
        gitidmap = {}
        def parent_lookup(revid):
            try:
                return gitidmap[revid]
            except KeyError:
                return self.target.lookup_git_revid(revid)[0]
        mapping = self.target.get_mapping()
        self.source.lock_write()
        try:
            todo = self.missing_revisions(stop_revision, ghosts=fetch_ghosts)
            pb = ui.ui_factory.nested_progress_bar()
            try:
                for i, revid in enumerate(todo):
                    pb.update("pushing revisions", i, len(todo))
                    git_commit = self.import_revision_gist(revid, parent_lookup)
                    gitidmap[revid] = git_commit
                    git_revid = mapping.revision_id_foreign_to_bzr(git_commit)
                    revidmap[revid] = git_revid
            finally:
                pb.finished()
            if revidmap != {}:
                self.source.fetch(self.target, 
                        revision_id=revidmap[stop_revision])
        finally:
            self.source.unlock()
        return revidmap

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with GitRepository."""
        return (not isinstance(source, GitRepository) and 
                isinstance(target, GitRepository))
