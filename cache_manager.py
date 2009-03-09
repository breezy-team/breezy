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

"""A manager of caches."""


from bzrlib import lru_cache, trace
from bzrlib.plugins.fastimport import helpers

class CacheManager(object):

    def __init__(self, info=None, verbose=False, inventory_cache_size=10):
        """Create a manager of caches.

        :param info: a ConfigObj holding the output from
            the --info processor, or None if no hints are available
        """
        self.verbose = verbose

        # dataref -> data. datref is either :mark or the sha-1.
        # Sticky blobs aren't removed after being referenced.
        self._blobs = {}
        self._sticky_blobs = {}

        # revision-id -> Inventory cache
        # these are large and we probably don't need too many as
        # most parents are recent in history
        self.inventories = lru_cache.LRUCache(inventory_cache_size)

        # import commmit-ids -> revision-id lookup table
        # we need to keep all of these but they are small
        self.revision_ids = {}

        # path -> file-ids - as generated
        self.file_ids = {}

        # Head tracking: last ref, last id per ref & map of commit ids to ref*s*
        self.last_ref = None
        self.last_ids = {}
        self.heads = {}

        # Work out the blobs to make sticky - None means all
        self._blobs_to_keep = None
        if info is not None:
            try:
                self._blobs_to_keep = info['Blob usage tracking']['multi']
            except KeyError:
                # info not in file - possible when no blobs used
                pass

    def dump_stats(self, note=trace.note):
        """Dump some statistics about what we cached."""
        # TODO: add in inventory stastistics
        note("Cache statistics:")
        self._show_stats_for(self._sticky_blobs, "sticky blobs", note=note)
        self._show_stats_for(self.revision_ids, "revision-ids", note=note)
        self._show_stats_for(self.file_ids, "file-ids", note=note)
        # These aren't interesting so omit from the output, at least for now
        #self._show_stats_for(self._blobs, "other blobs", note=note)
        #self._show_stats_for(self.last_ids, "last-ids", note=note)
        #self._show_stats_for(self.heads, "heads", note=note)

    def _show_stats_for(self, dict, label, note=trace.note):
        """Dump statistics about a given dictionary.

        By the key and value need to support len().
        """
        count = len(dict)
        size = sum(map(len, dict.keys()))
        size += sum(map(len, dict.values()))
        kbytes = size * 1.0 / 1024
        note("    %-12s: %8.1fs kB (%d %s)" % (label, kbytes, count,
            helpers.single_plural(count, "item", "items")))

    def clear_all(self):
        """Free up any memory used by the caches."""
        self._blobs.clear()
        self._sticky_blobs.clear()
        self.revision_ids.clear()
        self.file_ids.clear()
        self.last_ids.clear()
        self.heads.clear()
        self.inventories.clear()

    def store_blob(self, id, data):
        """Store a blob of data."""
        if (self._blobs_to_keep is None or data == '' or
            id in self._blobs_to_keep):
            self._sticky_blobs[id] = data
        else:
            self._blobs[id] = data

    def fetch_blob(self, id):
        """Fetch a blob of data."""
        try:
            return self._sticky_blobs[id]
        except KeyError:
            return self._blobs.pop(id)

    def delete_path(self, path):
        """Remove a path from caches."""
        # we actually want to remember what file-id we gave a path,
        # even when that file is deleted, so doing nothing is correct
        pass

    def rename_path(self, old_path, new_path):
        """Rename a path in the caches."""
        # In this case, we need to forget the file-id we gave a path,
        # otherwise, we'll get duplicate file-ids in the repository.
        self.file_ids[new_path] = self.file_ids[old_path]
        del self.file_ids[old_path]

    def track_heads(self, cmd):
        """Track the repository heads given a CommitCommand.
        
        :param cmd: the CommitCommand
        :return: the list of parents in terms of commit-ids
        """
        # Get the true set of parents
        if cmd.from_ is not None:
            parents = [cmd.from_]
        else:
            last_id = self.last_ids.get(cmd.ref)
            if last_id is not None:
                parents = [last_id]
            else:
                parents = []
        parents.extend(cmd.merges)

        # Track the heads
        self.track_heads_for_ref(cmd.ref, cmd.id, parents)
        return parents

    def track_heads_for_ref(self, cmd_ref, cmd_id, parents=None):
        if parents is not None:
            for parent in parents:
                if parent in self.heads:
                    del self.heads[parent]
        self.heads.setdefault(cmd_id, set()).add(cmd_ref)
        self.last_ids[cmd_ref] = cmd_id
        self.last_ref = cmd_ref
