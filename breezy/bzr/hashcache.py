# Copyright (C) 2005-2010 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

# TODO: Up-front, stat all files in order and remove those which are deleted or
# out-of-date.  Don't actually re-read them until they're needed.  That ought
# to bring all the inodes into core so that future stats to them are fast, and
# it preserves the nice property that any caller will always get up-to-date
# data except in unavoidable cases.

# TODO: Perhaps return more details on the file to avoid statting it
# again: nonexistent, file type, size, etc

# TODO: Perhaps use a Python pickle instead of a text file; might be faster.


CACHE_HEADER = b"### bzr hashcache v5\n"

import os
import stat
import time

from .. import (
    atomicfile,
    errors,
    filters as _mod_filters,
    osutils,
    trace,
    )


FP_MTIME_COLUMN = 1
FP_CTIME_COLUMN = 2
FP_MODE_COLUMN = 5


class HashCache(object):
    """Cache for looking up file SHA-1.

    Files are considered to match the cached value if the fingerprint
    of the file has not changed.  This includes its mtime, ctime,
    device number, inode number, and size.  This should catch
    modifications or replacement of the file by a new one.

    This may not catch modifications that do not change the file's
    size and that occur within the resolution window of the
    timestamps.  To handle this we specifically do not cache files
    which have changed since the start of the present second, since
    they could undetectably change again.

    This scheme may fail if the machine's clock steps backwards.
    Don't do that.

    This does not canonicalize the paths passed in; that should be
    done by the caller.

    _cache
        Indexed by path, points to a two-tuple of the SHA-1 of the file.
        and its fingerprint.

    stat_count
        number of times files have been statted

    hit_count
        number of times files have been retrieved from the cache, avoiding a
        re-read

    miss_count
        number of misses (times files have been completely re-read)
    """
    needs_write = False

    def __init__(self, root, cache_file_name, mode=None,
                 content_filter_stack_provider=None):
        """Create a hash cache in base dir, and set the file mode to mode.

        :param content_filter_stack_provider: a function that takes a
            path (relative to the top of the tree) and a file-id as
            parameters and returns a stack of ContentFilters.
            If None, no content filtering is performed.
        """
        if not isinstance(root, str):
            raise ValueError("Base dir for hashcache must be text")
        self.root = root
        self.hit_count = 0
        self.miss_count = 0
        self.stat_count = 0
        self.danger_count = 0
        self.removed_count = 0
        self.update_count = 0
        self._cache = {}
        self._mode = mode
        self._cache_file_name = cache_file_name
        self._filter_provider = content_filter_stack_provider

    def cache_file_name(self):
        return self._cache_file_name

    def clear(self):
        """Discard all cached information.

        This does not reset the counters."""
        if self._cache:
            self.needs_write = True
            self._cache = {}

    def scan(self):
        """Scan all files and remove entries where the cache entry is obsolete.

        Obsolete entries are those where the file has been modified or deleted
        since the entry was inserted.
        """
        # Stat in inode order as optimisation for at least linux.
        def inode_order(path_and_cache):
            return path_and_cache[1][1][3]
        for path, cache_val in sorted(self._cache.items(), key=inode_order):
            abspath = osutils.pathjoin(self.root, path)
            fp = self._fingerprint(abspath)
            self.stat_count += 1

            if not fp or cache_val[1] != fp:
                # not here or not a regular file anymore
                self.removed_count += 1
                self.needs_write = True
                del self._cache[path]

    def get_sha1(self, path, stat_value=None):
        """Return the sha1 of a file.
        """
        abspath = osutils.pathjoin(self.root, path)
        self.stat_count += 1
        file_fp = self._fingerprint(abspath, stat_value)

        if not file_fp:
            # not a regular file or not existing
            if path in self._cache:
                self.removed_count += 1
                self.needs_write = True
                del self._cache[path]
            return None

        if path in self._cache:
            cache_sha1, cache_fp = self._cache[path]
        else:
            cache_sha1, cache_fp = None, None

        if cache_fp == file_fp:
            self.hit_count += 1
            return cache_sha1

        self.miss_count += 1

        mode = file_fp[FP_MODE_COLUMN]
        if stat.S_ISREG(mode):
            if self._filter_provider is None:
                filters = []
            else:
                filters = self._filter_provider(path=path)
            digest = self._really_sha1_file(abspath, filters)
        elif stat.S_ISLNK(mode):
            target = osutils.readlink(abspath)
            digest = osutils.sha_string(target.encode('UTF-8'))
        else:
            raise errors.BzrError("file %r: unknown file stat mode: %o"
                                  % (abspath, mode))

        # window of 3 seconds to allow for 2s resolution on windows,
        # unsynchronized file servers, etc.
        cutoff = self._cutoff_time()
        if file_fp[FP_MTIME_COLUMN] >= cutoff \
                or file_fp[FP_CTIME_COLUMN] >= cutoff:
            # changed too recently; can't be cached.  we can
            # return the result and it could possibly be cached
            # next time.
            #
            # the point is that we only want to cache when we are sure that any
            # subsequent modifications of the file can be detected.  If a
            # modification neither changes the inode, the device, the size, nor
            # the mode, then we can only distinguish it by time; therefore we
            # need to let sufficient time elapse before we may cache this entry
            # again.  If we didn't do this, then, for example, a very quick 1
            # byte replacement in the file might go undetected.
            ## mutter('%r modified too recently; not caching', path)
            self.danger_count += 1
            if cache_fp:
                self.removed_count += 1
                self.needs_write = True
                del self._cache[path]
        else:
            # mutter('%r added to cache: now=%f, mtime=%d, ctime=%d',
            ##        path, time.time(), file_fp[FP_MTIME_COLUMN],
            # file_fp[FP_CTIME_COLUMN])
            self.update_count += 1
            self.needs_write = True
            self._cache[path] = (digest, file_fp)
        return digest

    def _really_sha1_file(self, abspath, filters):
        """Calculate the SHA1 of a file by reading the full text"""
        return _mod_filters.internal_size_sha_file_byname(abspath, filters)[1]

    def write(self):
        """Write contents of cache to file."""
        with atomicfile.AtomicFile(self.cache_file_name(), 'wb',
                                   new_mode=self._mode) as outf:
            outf.write(CACHE_HEADER)

            for path, c in self._cache.items():
                line_info = [path.encode('utf-8'), b'// ', c[0], b' ']
                line_info.append(b'%d %d %d %d %d %d' % c[1])
                line_info.append(b'\n')
                outf.write(b''.join(line_info))
            self.needs_write = False
            # mutter("write hash cache: %s hits=%d misses=%d stat=%d recent=%d updates=%d",
            #        self.cache_file_name(), self.hit_count, self.miss_count,
            # self.stat_count,
            # self.danger_count, self.update_count)

    def read(self):
        """Reinstate cache from file.

        Overwrites existing cache.

        If the cache file has the wrong version marker, this just clears
        the cache."""
        self._cache = {}

        fn = self.cache_file_name()
        try:
            inf = open(fn, 'rb', buffering=65000)
        except IOError as e:
            trace.mutter("failed to open %s: %s", fn, str(e))
            # better write it now so it is valid
            self.needs_write = True
            return

        with inf:
            hdr = inf.readline()
            if hdr != CACHE_HEADER:
                trace.mutter('cache header marker not found at top of %s;'
                             ' discarding cache', fn)
                self.needs_write = True
                return

            for l in inf:
                pos = l.index(b'// ')
                path = l[:pos].decode('utf-8')
                if path in self._cache:
                    trace.warning('duplicated path %r in cache' % path)
                    continue

                pos += 3
                fields = l[pos:].split(b' ')
                if len(fields) != 7:
                    trace.warning("bad line in hashcache: %r" % l)
                    continue

                sha1 = fields[0]
                if len(sha1) != 40:
                    trace.warning("bad sha1 in hashcache: %r" % sha1)
                    continue

                fp = tuple(map(int, fields[1:]))

                self._cache[path] = (sha1, fp)

        self.needs_write = False

    def _cutoff_time(self):
        """Return cutoff time.

        Files modified more recently than this time are at risk of being
        undetectably modified and so can't be cached.
        """
        return int(time.time()) - 3

    def _fingerprint(self, abspath, stat_value=None):
        if stat_value is None:
            try:
                stat_value = os.lstat(abspath)
            except OSError:
                # might be missing, etc
                return None
        if stat.S_ISDIR(stat_value.st_mode):
            return None
        # we discard any high precision because it's not reliable; perhaps we
        # could do better on some systems?
        return (stat_value.st_size, int(stat_value.st_mtime),
                int(stat_value.st_ctime), stat_value.st_ino,
                stat_value.st_dev, stat_value.st_mode)
