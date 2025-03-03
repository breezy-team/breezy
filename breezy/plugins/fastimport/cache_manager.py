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
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""A manager of caches."""

import atexit
import os
import shutil
import tempfile
import weakref

from fastimport.reftracker import RefTracker

from ... import lru_cache, trace
from . import branch_mapper
from .helpers import single_plural


class _Cleanup:
    """This class makes sure we clean up when CacheManager goes away.

    We use a helper class to ensure that we are never in a refcycle.
    """

    def __init__(self, disk_blobs):
        self.disk_blobs = disk_blobs
        self.tempdir = None
        self.small_blobs = None

    def __del__(self):
        self.finalize()

    def finalize(self):
        if self.disk_blobs is not None:
            for info in self.disk_blobs.values():
                if info[-1] is not None:
                    os.unlink(info[-1])
            self.disk_blobs = None
        if self.small_blobs is not None:
            self.small_blobs.close()
            self.small_blobs = None
        if self.tempdir is not None:
            shutil.rmtree(self.tempdir)


class CacheManager:
    _small_blob_threshold = 25 * 1024
    _sticky_cache_size = 300 * 1024 * 1024
    _sticky_flushed_size = 100 * 1024 * 1024

    def __init__(self, info=None, verbose=False, inventory_cache_size=10):
        """Create a manager of caches.

        :param info: a ConfigObj holding the output from
            the --info processor, or None if no hints are available
        """
        self.verbose = verbose

        # dataref -> data. datref is either :mark or the sha-1.
        # Sticky blobs are referenced more than once, and are saved until their
        # refcount goes to 0
        self._blobs = {}
        self._sticky_blobs = {}
        self._sticky_memory_bytes = 0
        # if we overflow our memory cache, then we will dump large blobs to
        # disk in this directory
        self._tempdir = None
        # id => (offset, n_bytes, fname)
        #   if fname is None, then the content is stored in the small file
        self._disk_blobs = {}
        self._cleanup = _Cleanup(self._disk_blobs)

        # revision-id -> Inventory cache
        # these are large and we probably don't need too many as
        # most parents are recent in history
        self.inventories = lru_cache.LRUCache(inventory_cache_size)

        # import commmit-ids -> revision-id lookup table
        # we need to keep all of these but they are small
        self.marks = {}

        # (path, branch_ref) -> file-ids - as generated.
        # (Use store_file_id/fetch_fileid methods rather than direct access.)

        # Work out the blobs to make sticky - None means all
        self._blob_ref_counts = {}
        if info is not None:
            try:
                blobs_by_counts = info["Blob reference counts"]
                # The parser hands values back as lists, already parsed
                for count, blob_list in blobs_by_counts.items():
                    n = int(count)
                    for b in blob_list:
                        self._blob_ref_counts[b] = n
            except KeyError:
                # info not in file - possible when no blobs used
                pass

        # BranchMapper has no state (for now?), but we keep it around rather
        # than reinstantiate on every usage
        self.branch_mapper = branch_mapper.BranchMapper()

        self.reftracker = RefTracker()

    def add_mark(self, mark, commit_id):
        if mark.startswith(b":"):
            raise ValueError(mark)
        is_new = mark in self.marks
        self.marks[mark] = commit_id
        return is_new

    def lookup_committish(self, committish):
        """Resolve a 'committish' to a revision id.

        :param committish: A "committish" string
        :return: Bazaar revision id
        """
        if not committish.startswith(b":"):
            raise ValueError(committish)
        return self.marks[committish.lstrip(b":")]

    def dump_stats(self, note=trace.note):
        """Dump some statistics about what we cached."""
        # TODO: add in inventory stastistics
        note("Cache statistics:")
        self._show_stats_for(self._sticky_blobs, "sticky blobs", note=note)
        self._show_stats_for(self.marks, "revision-ids", note=note)
        # These aren't interesting so omit from the output, at least for now
        # self._show_stats_for(self._blobs, "other blobs", note=note)
        # self.reftracker.dump_stats(note=note)

    def _show_stats_for(self, a_dict, label, note, tuple_key=False):
        """Dump statistics about a given dictionary.

        By the key and value need to support len().
        """
        count = len(a_dict)
        if tuple_key:
            size = sum(map(len, ("".join(k) for k in a_dict)))
        else:
            size = sum(map(len, a_dict))
        size += sum(map(len, a_dict.values()))
        size = size * 1.0 / 1024
        unit = "K"
        if size > 1024:
            size = size / 1024
            unit = "M"
            if size > 1024:
                size = size / 1024
                unit = "G"
        note(
            "    %-12s: %8.1f %s (%d %s)",
            label, size, unit, count, single_plural(count, "item", "items")
        )

    def clear_all(self):
        """Free up any memory used by the caches."""
        self._blobs.clear()
        self._sticky_blobs.clear()
        self.marks.clear()
        self.reftracker.clear()
        self.inventories.clear()

    def _flush_blobs_to_disk(self):
        blobs = list(self._sticky_blobs)
        sticky_blobs = self._sticky_blobs
        total_blobs = len(sticky_blobs)
        blobs.sort(key=lambda k: len(sticky_blobs[k]))
        if self._tempdir is None:
            tempdir = tempfile.mkdtemp(prefix="fastimport_blobs-")
            self._tempdir = tempdir
            self._cleanup.tempdir = self._tempdir
            self._cleanup.small_blobs = tempfile.TemporaryFile(
                prefix="small-blobs-", dir=self._tempdir
            )
            small_blob_ref = weakref.ref(self._cleanup.small_blobs)
            # Even though we add it to _Cleanup it seems that the object can be
            # destroyed 'too late' for cleanup to actually occur. Probably a
            # combination of bzr's "die directly, don't clean up" and how
            # exceptions close the running stack.

            def exit_cleanup():
                small_blob = small_blob_ref()
                if small_blob is not None:
                    small_blob.close()
                shutil.rmtree(tempdir, ignore_errors=True)

            atexit.register(exit_cleanup)
        count = 0
        bytes = 0
        n_small_bytes = 0
        while self._sticky_memory_bytes > self._sticky_flushed_size:
            id = blobs.pop()
            blob = self._sticky_blobs.pop(id)
            n_bytes = len(blob)
            self._sticky_memory_bytes -= n_bytes
            if n_bytes < self._small_blob_threshold:
                f = self._cleanup.small_blobs
                f.seek(0, os.SEEK_END)
                self._disk_blobs[id] = (f.tell(), n_bytes, None)
                f.write(blob)
                n_small_bytes += n_bytes
            else:
                fd, name = tempfile.mkstemp(prefix="blob-", dir=self._tempdir)
                os.write(fd, blob)
                os.close(fd)
                self._disk_blobs[id] = (0, n_bytes, name)
            bytes += n_bytes
            del blob
            count += 1
        trace.note(
            "flushed %d/%d blobs w/ %.1fMB (%.1fMB small) to disk",
            count, total_blobs, bytes / 1024.0 / 1024, n_small_bytes / 1024.0 / 1024
        )

    def store_blob(self, id, data):
        """Store a blob of data."""
        # Note: If we're not reference counting, everything has to be sticky
        if not self._blob_ref_counts or id in self._blob_ref_counts:
            self._sticky_blobs[id] = data
            self._sticky_memory_bytes += len(data)
            if self._sticky_memory_bytes > self._sticky_cache_size:
                self._flush_blobs_to_disk()
        elif data == b"":
            # Empty data is always sticky
            self._sticky_blobs[id] = data
        else:
            self._blobs[id] = data

    def _decref(self, id, cache, fn):
        if not self._blob_ref_counts:
            return False
        count = self._blob_ref_counts.get(id, None)
        if count is not None:
            count -= 1
            if count <= 0:
                del cache[id]
                if fn is not None:
                    os.unlink(fn)
                del self._blob_ref_counts[id]
                return True
            else:
                self._blob_ref_counts[id] = count
        return False

    def fetch_blob(self, id):
        """Fetch a blob of data."""
        if id in self._blobs:
            return self._blobs.pop(id)
        if id in self._disk_blobs:
            (offset, n_bytes, fn) = self._disk_blobs[id]
            if fn is None:
                f = self._cleanup.small_blobs
                f.seek(offset)
                content = f.read(n_bytes)
            else:
                with open(fn, "rb") as fp:
                    content = fp.read()
            self._decref(id, self._disk_blobs, fn)
            return content
        content = self._sticky_blobs[id]
        if self._decref(id, self._sticky_blobs, None):
            self._sticky_memory_bytes -= len(content)
        return content
