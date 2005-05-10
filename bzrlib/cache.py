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


"""File stat cache to speed up tree comparisons.

This module basically gives a quick way to find the SHA-1 and related
information of a file in the working directory, without actually
reading and hashing the whole file.

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
to use a tdb instead.
"""



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
