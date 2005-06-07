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

import stat, os, sha, time

from trace import mutter
from errors import BzrError, BzrCheckError


"""File stat cache to speed up tree comparisons.

This module basically gives a quick way to find the SHA-1 and related
information of a file in the working directory, without actually
reading and hashing the whole file.



Implementation
==============

Users of this module should not need to know about how this is
implemented, and in particular should not depend on the particular
data which is stored or its format.

This is done by maintaining a cache indexed by a file fingerprint of
(path, size, mtime, ctime, ino, dev) pointing to the SHA-1.  If the
fingerprint has changed, we assume the file content has not changed
either and the SHA-1 is therefore the same.

If any of the fingerprint fields have changed then the file content
*may* have changed, or it may not have.  We need to reread the file
contents to make sure, but this is not visible to the user or
higher-level code (except as a delay of course).

The mtime and ctime are stored with nanosecond fields, but not all
filesystems give this level of precision.  There is therefore a
possible race: the file might be modified twice within a second
without changing the size or mtime, and a SHA-1 cached from the first
version would be wrong.  We handle this by not recording a cached hash
for any files which were modified in the current second and that
therefore have the chance to change again before the second is up.

The only known hole in this design is if the system clock jumps
backwards crossing invocations of bzr.  Please don't do that; use ntp
to gradually adjust your clock or don't use bzr over the step.

At the moment this is stored in a simple textfile; it might be nice
to use a tdb instead to allow faster lookup by file-id.

The cache is represented as a map from file_id to a tuple of (file_id,
sha1, path, size, mtime, ctime, ino, dev).

The SHA-1 is stored in memory as a hexdigest.

This version of the file on disk has one line per record, and fields
separated by \0 records.
"""

# order of fields returned by fingerprint()
FP_SIZE  = 0
FP_MTIME = 1
FP_CTIME = 2
FP_INO   = 3
FP_DEV   = 4

# order of fields in the statcache file and in the in-memory map
SC_FILE_ID = 0
SC_SHA1    = 1
SC_PATH    = 2
SC_SIZE    = 3
SC_MTIME   = 4
SC_CTIME   = 5
SC_INO     = 6
SC_DEV     = 7



CACHE_HEADER = "### bzr statcache v4"


def fingerprint(abspath):
    try:
        fs = os.lstat(abspath)
    except OSError:
        # might be missing, etc
        return None

    if stat.S_ISDIR(fs.st_mode):
        return None

    return (fs.st_size, fs.st_mtime,
            fs.st_ctime, fs.st_ino, fs.st_dev)



def _write_cache(basedir, entries):
    from atomicfile import AtomicFile

    cachefn = os.path.join(basedir, '.bzr', 'stat-cache')
    outf = AtomicFile(cachefn, 'wb')
    try:
        outf.write(CACHE_HEADER + '\n')
    
        for entry in entries:
            if len(entry) != 8:
                raise ValueError("invalid statcache entry tuple %r" % entry)
            outf.write(entry[0].encode('utf-8')) # file id
            outf.write('\0')
            outf.write(entry[1])             # hex sha1
            outf.write('\0')
            outf.write(entry[2].encode('utf-8')) # name
            for nf in entry[3:]:
                outf.write('\0%d' % nf)
            outf.write('\n')

        outf.commit()
    finally:
        if not outf.closed:
            outf.abort()


def _try_write_cache(basedir, entries):
    try:
        return _write_cache(basedir, entries)
    except IOError, e:
        mutter("cannot update statcache in %s: %s" % (basedir, e))
    except OSError, e:
        mutter("cannot update statcache in %s: %s" % (basedir, e))
        
        
        
def load_cache(basedir):
    import re
    cache = {}
    seen_paths = {}
    from bzrlib.trace import warning

    assert isinstance(basedir, basestring)

    sha_re = re.compile(r'[a-f0-9]{40}')

    try:
        cachefn = os.path.join(basedir, '.bzr', 'stat-cache')
        cachefile = open(cachefn, 'rb')
    except IOError:
        return cache

    line1 = cachefile.readline().rstrip('\r\n')
    if line1 != CACHE_HEADER:
        mutter('cache header marker not found at top of %s; discarding cache'
               % cachefn)
        return cache

    for l in cachefile:
        f = l.split('\0')

        file_id = f[0].decode('utf-8')
        if file_id in cache:
            warning("duplicated file_id in cache: {%s}" % file_id)

        text_sha = f[1]
        if len(text_sha) != 40 or not sha_re.match(text_sha):
            raise BzrCheckError("invalid file SHA-1 in cache: %r" % text_sha)
        
        path = f[2].decode('utf-8')
        if path in seen_paths:
            warning("duplicated path in cache: %r" % path)
        seen_paths[path] = True
        
        entry = (file_id, text_sha, path) + tuple([long(x) for x in f[3:]])
        if len(entry) != 8:
            raise ValueError("invalid statcache entry tuple %r" % entry)

        cache[file_id] = entry
    return cache



def _files_from_inventory(inv):
    for path, ie in inv.iter_entries():
        if ie.kind != 'file':
            continue
        yield ie.file_id, path
    


def update_cache(basedir, inv, flush=False):
    """Update and return the cache for the branch.

    The returned cache may contain entries that have not been written
    to disk for files recently touched.

    flush -- discard any previous cache and recalculate from scratch.
    """

    # load the existing cache; use information there to find a list of
    # files ordered by inode, which is alleged to be the fastest order
    # to stat the files.
    
    to_update = _files_from_inventory(inv)

    assert isinstance(flush, bool)
    if flush:
        cache = {}
    else:
        cache = load_cache(basedir)

        by_inode = []
        without_inode = []
        for file_id, path in to_update:
            if file_id in cache:
                by_inode.append((cache[file_id][SC_INO], file_id, path))
            else:
                without_inode.append((file_id, path))
        by_inode.sort()

        to_update = [a[1:] for a in by_inode] + without_inode
            
    stat_cnt = missing_cnt = new_cnt = hardcheck = change_cnt = 0

    # dangerfiles have been recently touched and can't be committed to
    # a persistent cache yet, but they are returned to the caller.
    dangerfiles = []
    
    now = int(time.time())

    ## mutter('update statcache under %r' % basedir)
    for file_id, path in to_update:
        abspath = os.path.join(basedir, path)
        fp = fingerprint(abspath)
        stat_cnt += 1
        
        cacheentry = cache.get(file_id)

        if fp == None: # not here
            if cacheentry:
                del cache[file_id]
                change_cnt += 1
            missing_cnt += 1
            continue
        elif not cacheentry:
            new_cnt += 1

        if (fp[FP_MTIME] >= now) or (fp[FP_CTIME] >= now):
            dangerfiles.append(file_id)

        if cacheentry and (cacheentry[3:] == fp):
            continue                    # all stat fields unchanged

        hardcheck += 1

        dig = sha.new(file(abspath, 'rb').read()).hexdigest()

        # We update the cache even if the digest has not changed from
        # last time we looked, so that the fingerprint fields will
        # match in future.
        cacheentry = (file_id, dig, path) + fp
        cache[file_id] = cacheentry
        change_cnt += 1

    mutter('statcache: statted %d files, read %d files, %d changed, %d dangerous, '
           '%d deleted, %d new, '
           '%d in cache'
           % (stat_cnt, hardcheck, change_cnt, len(dangerfiles),
              missing_cnt, new_cnt, len(cache)))
        
    if change_cnt:
        mutter('updating on-disk statcache')

        if dangerfiles:
            safe_cache = cache.copy()
            for file_id in dangerfiles:
                del safe_cache[file_id]
        else:
            safe_cache = cache
        
        _try_write_cache(basedir, safe_cache.itervalues())

    return cache
