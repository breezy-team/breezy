# Copyright (C) 2009 Canonical Ltd
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

"""Map from Git sha's to Bazaar objects."""

import bzrlib

from bzrlib import ui

from bzrlib.errors import NoSuchRevision

from bzrlib.plugins.git.mapping import (
    inventory_to_tree_and_blobs,
    revision_to_commit,
    )
from bzrlib.plugins.git.shamap import GitShaMap

from dulwich.objects import (
    Blob,
    )


class GitObjectConverter(object):

    def __init__(self, repository, mapping=None):
        self.repository = repository
        if mapping is None:
            self.mapping = self.repository.get_mapping()
        else:
            self.mapping = mapping
        self._idmap = GitShaMap(self.repository._transport)

    def _update_sha_map(self):
        all_revids = self.repository.all_revision_ids()
        graph = self.repository.get_graph()
        present_revids = set(self._idmap.revids())
        pb = ui.ui_factory.nested_progress_bar()
        try:
            for i, revid in enumerate(graph.iter_topo_order(all_revids)):
                if revid in present_revids:
                    continue
                pb.update("updating git map", i, len(all_revids))
                self._update_sha_map_revision(revid)
        finally:
            self._idmap.commit()
            pb.finished()

    def _update_sha_map_revision(self, revid):
        inv = self.repository.get_inventory(revid)
        objects = inventory_to_tree_and_blobs(self.repository, self.mapping, revid)
        for sha, o, path in objects:
            if path == "":
                tree_sha = sha
            ie = inv[inv.path2id(path)]
            if ie.kind in ("file", "symlink"):
                self._idmap.add_entry(sha, "blob", (ie.file_id, ie.revision))
            elif ie.kind == "directory":
                self._idmap.add_entry(sha, "tree", (path, ie.revision))
            else:
                raise AssertionError()
        rev = self.repository.get_revision(revid)
        commit_obj = revision_to_commit(rev, tree_sha, self._idmap._parent_lookup)
        self._idmap.add_entry(commit_obj.sha().hexdigest(), "commit", (revid, tree_sha))

    def _get_blob(self, fileid, revision):
        """Return a Git Blob object from a fileid and revision stored in bzr.
        
        :param fileid: File id of the text
        :param revision: Revision of the text
        """
        text = self.repository.texts.get_record_stream([(fileid, revision)], "unordered", True).next().get_bytes_as("fulltext")
        blob = Blob()
        blob._text = text
        return blob

    def _get_tree(self, path, revid):
        raise NotImplementedError(self._get_tree)

    def _get_commit(self, revid, tree_sha):
        rev = self.repository.get_revision(revid)
        return revision_to_commit(rev, tree_sha, self._idmap._parent_lookup)

    def __getitem__(self, sha):
        # See if sha is in map
        try:
            (type, type_data) = self._idmap.lookup_git_sha(sha)
        except KeyError:
            # if not, see if there are any unconverted revisions and add them 
            # to the map, search for sha in map again
            self._update_sha_map()
            (type, type_data) = self._idmap.lookup_git_sha(sha)
        # convert object to git object
        if type == "commit":
            return self._get_commit(*type_data)
        elif type == "blob":
            return self._get_blob(*type_data)
        elif type == "tree":
            return self._get_tree(*type_data)
        else:
            raise AssertionError("Unknown object type '%s'" % type)
