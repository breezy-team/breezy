# (C) 2005 Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA



# TODO: Perhaps have a way to stat all the files in inode order, and
# then remember that they're all fresh for the lifetime of the object?

# TODO: Keep track of whether there are in-memory updates that need to
# be flushed.

# TODO: Perhaps return more details on the file to avoid statting it
# again: nonexistent, file type, size, etc




CACHE_HEADER = "### bzr hashcache v5\n"


def _fingerprint(abspath):
    import os, stat

    try:
        fs = os.lstat(abspath)
    except OSError:
        # might be missing, etc
        return None

    if stat.S_ISDIR(fs.st_mode):
        return None

    # we discard any high precision because it's not reliable; perhaps we
    # could do better on some systems?
    return (fs.st_size, long(fs.st_mtime),
            long(fs.st_ctime), fs.st_ino, fs.st_dev)


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

    def __init__(self, basedir):
        self.basedir = basedir
        self.hit_count = 0
        self.miss_count = 0
        self.stat_count = 0
        self.danger_count = 0
        self._cache = {}



    def cache_file_name(self):
        import os.path
        return os.path.join(self.basedir, '.bzr', 'stat-cache')




    def clear(self):
        """Discard all cached information.

        This does not reset the counters."""
        if self._cache:
            self.needs_write = True
            self._cache = {}


    def get_sha1(self, path):
        """Return the hex SHA-1 of the contents of the file at path.

        XXX: If the file does not exist or is not a plain file???
        """

        import os, time
        from bzrlib.osutils import sha_file
        from bzrlib.trace import mutter
        
        abspath = os.path.join(self.basedir, path)
        fp = _fingerprint(abspath)
        c = self._cache.get(path)
        if c:
            cache_sha1, cache_fp = c
        else:
            cache_sha1, cache_fp = None, None

        self.stat_count += 1

        if not fp:
            # not a regular file
            return None
        elif cache_fp and (cache_fp == fp):
            self.hit_count += 1
            return cache_sha1
        else:
            self.miss_count += 1
            digest = sha_file(file(abspath, 'rb'))

            now = int(time.time())
            if fp[1] >= now or fp[2] >= now:
                # changed too recently; can't be cached.  we can
                # return the result and it could possibly be cached
                # next time.
                self.danger_count += 1 
                if cache_fp:
                    mutter("remove outdated entry for %s" % path)
                    self.needs_write = True
                    del self._cache[path]
            elif (fp != cache_fp) or (digest != cache_sha1):
                mutter("update entry for %s" % path)
                mutter("  %r" % (fp,))
                mutter("  %r" % (cache_fp,))
                self.needs_write = True
                self._cache[path] = (digest, fp)

            return digest



    def write(self):
        """Write contents of cache to file."""
        from atomicfile import AtomicFile

        outf = AtomicFile(self.cache_file_name(), 'wb')
        try:
            print >>outf, CACHE_HEADER,

            for path, c  in self._cache.iteritems():
                assert '//' not in path, path
                outf.write(path.encode('utf-8'))
                outf.write('// ')
                print >>outf, c[0],     # hex sha1
                for fld in c[1]:
                    print >>outf, "%d" % fld,
                print >>outf

            outf.commit()
            self.needs_write = False
        finally:
            if not outf.closed:
                outf.abort()
        


    def read(self):
        """Reinstate cache from file.

        Overwrites existing cache.

        If the cache file has the wrong version marker, this just clears 
        the cache."""
        from bzrlib.trace import mutter, warning

        self._cache = {}

        fn = self.cache_file_name()
        try:
            inf = file(fn, 'rb')
        except IOError, e:
            mutter("failed to open %s: %s" % (fn, e))
            return


        hdr = inf.readline()
        if hdr != CACHE_HEADER:
            mutter('cache header marker not found at top of %s; discarding cache'
                   % fn)
            return

        for l in inf:
            pos = l.index('// ')
            path = l[:pos].decode('utf-8')
            if path in self._cache:
                warning('duplicated path %r in cache' % path)
                continue

            pos += 3
            fields = l[pos:].split(' ')
            if len(fields) != 6:
                warning("bad line in hashcache: %r" % l)
                continue

            sha1 = fields[0]
            if len(sha1) != 40:
                warning("bad sha1 in hashcache: %r" % sha1)
                continue

            fp = tuple(map(long, fields[1:]))

            self._cache[path] = (sha1, fp)

        self.needs_write = False
           


        
