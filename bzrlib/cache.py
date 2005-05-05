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
from binascii import b2a_qp, a2b_qp

from trace import mutter


# file fingerprints are: (path, size, mtime, ctime, ino, dev).
#
# if this is the same for this file as in the previous revision, we
# assume the content is the same and the SHA-1 is the same.

# This is stored in a fingerprint file that also contains the file-id
# and the content SHA-1.

# Thus for any given file we can quickly get the SHA-1, either from
# the cache or if the cache is out of date.

# At the moment this is stored in a simple textfile; it might be nice
# to use a tdb instead.


# What we need:

# build a new cache from scratch
# load cache, incrementally update it

# TODO: Have a paranoid mode where we always compare the texts and
# always recalculate the digest, to trap modification without stat
# change and SHA collisions.



def fingerprint(path, abspath):
    try:
        fs = os.lstat(abspath)
    except OSError:
        # might be missing, etc
        return None

    if stat.S_ISDIR(fs.st_mode):
        return None

    return (fs.st_size, fs.st_mtime,
            fs.st_ctime, fs.st_ino, fs.st_dev)


def write_cache(branch, entry_iter):
    outf = branch.controlfile('work-cache.tmp', 'wt')
    for entry in entry_iter:
        outf.write(entry[0] + ' ' + entry[1] + ' ')
        outf.write(b2a_qp(entry[2], True))
        outf.write(' %d %d %d %d %d\n' % entry[3:])
        
    outf.close()
    os.rename(branch.controlfilename('work-cache.tmp'),
              branch.controlfilename('work-cache'))

        
        
def load_cache(branch):
    cache = {}

    try:
        cachefile = branch.controlfile('work-cache', 'rt')
    except IOError:
        return cache
    
    for l in cachefile:
        f = l.split(' ')
        file_id = f[0]
        if file_id in cache:
            raise BzrError("duplicated file_id in cache: {%s}" % file_id)
        cache[file_id] = (f[0], f[1], a2b_qp(f[2])) + tuple([long(x) for x in f[3:]])
    return cache




def _files_from_inventory(inv):
    for path, ie in inv.iter_entries():
        if ie.kind != 'file':
            continue
        yield ie.file_id, path
    

def build_cache(branch):
    inv = branch.read_working_inventory()

    cache = {}
    _update_cache_from_list(branch, cache, _files_from_inventory(inv))
    


def update_cache(branch, inv):
    # TODO: It's supposed to be faster to stat the files in order by inum.
    # We don't directly know the inum of the files of course but we do
    # know where they were last sighted, so we can sort by that.

    cache = load_cache(branch)
    return _update_cache_from_list(branch, cache, _files_from_inventory(inv))



def _update_cache_from_list(branch, cache, to_update):
    """Update the cache to have info on the named files.

    to_update is a sequence of (file_id, path) pairs.
    """
    hardcheck = dirty = 0
    for file_id, path in to_update:
        fap = branch.abspath(path)
        fp = fingerprint(fap, path)
        cacheentry = cache.get(file_id)

        if fp == None: # not here
            if cacheentry:
                del cache[file_id]
                dirty += 1
            continue

        if cacheentry and (cacheentry[3:] == fp):
            continue                    # all stat fields unchanged

        hardcheck += 1

        dig = sha.new(file(fap, 'rb').read()).hexdigest()

        if cacheentry == None or dig != cacheentry[1]: 
            # if there was no previous entry for this file, or if the
            # SHA has changed, then update the cache
            cacheentry = (file_id, dig, path) + fp
            cache[file_id] = cacheentry
            dirty += 1

    mutter('work cache: read %d files, %d changed' % (hardcheck, dirty))
        
    if dirty:
        write_cache(branch, cache.itervalues())

    return cache
