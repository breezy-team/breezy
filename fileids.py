# Copyright (C) 2006 Jelmer Vernooij <jelmer@samba.org>

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

from bzrlib.errors import RevisionNotPresent
from bzrlib.inventory import ROOT_ID
from bzrlib.progress import ProgressBar
from bzrlib.trace import mutter
from bzrlib.transport import get_transport
from bzrlib.knit import KnitVersionedFile
from warnings import warn

import os
import shelve
from copy import copy
import logwalker
from repository import (escape_svn_path, generate_svn_revision_id, 
                        parse_svn_revision_id, MAPPING_VERSION)

def generate_svn_file_id(uuid, revnum, branch, path):
    """Create a file id identifying a Subversion file.

    :param uuid: UUID of the repository
    :param revnu: Revision number at which the file was introduced.
    :param branch: Branch path of the branch in which the file was introduced.
    :param path: Original path of the file.
    """
    if path == "":
        return ROOT_ID
    introduced_revision_id = generate_svn_revision_id(uuid, revnum, branch)
    return "%s-%s" % (introduced_revision_id, escape_svn_path(path))


def generate_file_id(revid, path):
    (uuid, branch, revnum) = parse_svn_revision_id(revid)
    return generate_svn_file_id(uuid, revnum, branch, path)


def get_local_changes(paths, scheme, uuid):
    new_paths = {}
    names = paths.keys()
    names.sort()
    for p in names:
        data = paths[p]
        new_p = scheme.unprefix(p)[1]
        if data[1] is not None:
            (cbp, crp) = scheme.unprefix(data[1])

            # Branch copy
            if (crp == "" and new_p == ""):
                data = ('M', None, None)
            else:
                data = (data[0], crp, generate_svn_revision_id(
                    uuid, data[2], cbp))

        new_paths[new_p] = data
    return new_paths


class FileIdMap(object):
    """ File id store. 

    Keeps a map

    revnum -> branch -> path -> fileid
    """
    def __init__(self, log, cache_dir):
        self._log = log
        self.cache_dict = shelve.open(os.path.join(cache_dir, 'fileids-v1'))

    def save(self, revid, parent_revids, _map):
        mutter('saving file id map for %r' % revid)
        self.cache_dict[revid] = _map

    def load(self, revid):
        return self.cache_dict[revid]

    def get_map(self, uuid, revnum, branch, pb=None):
        """Make sure the map is up to date until revnum."""
        # First, find the last cached map
        todo = []
        parent_revs = []
        map = {"": (ROOT_ID, None)} # No history -> empty map
        for (bp, paths, rev) in self._log.follow_history(branch, revnum):
            revid = generate_svn_revision_id(uuid, rev, bp)
            try:
                map = self.load(revid)
                # found the nearest cached map
                parent_revs = [revid]
                break
            except KeyError:
                todo.append((revid, paths))
                continue
        
        # target revision was present
        if len(todo) == 0:
            return map
    
        todo.reverse()

        i = 0
        for (revid, global_changes) in todo:
            changes = get_local_changes(global_changes, self._log.scheme,
                                        uuid)
            mutter('generating file id map for %r' % revid)
            if pb is not None:
                pb.update('generating file id map', i, len(todo))

            def find_children(path, revid):
                (_, bp, revnum) = parse_svn_revision_id(revid)
                for p in self._log.find_children(bp+"/"+path, revnum):
                    yield self._log.scheme.unprefix(p)[1]

            map = self._apply_changes(map, revid, changes, find_children)
            self.save(revid, parent_revs, map)
            parent_revs = [revid]
            i = i + 1

        if pb is not None:
            pb.clear()
        return map


class SimpleFileIdMap(FileIdMap):
    @staticmethod
    def _apply_changes(base_map, revid, changes, find_children=None):
        map = copy(base_map)

        map[""] = (ROOT_ID, revid)

        sorted_paths = changes.keys()
        sorted_paths.sort()
        for p in sorted_paths:
            data = changes[p]
            if data[0] in ('D', 'R'):
                assert map.has_key(p)
                del map[p]
                # Delete all children of p as well
                for c in map.keys():
                    if c.startswith(p+"/"):
                        del map[c]

            if data[0] in ('A', 'R'):
                map[p] = generate_file_id(revid, p), revid

                if not data[1] is None:
                    mutter('%r:%s copied from %r:%s' % (p, revid, data[1], data[2]))
                    if find_children is None:
                        warn('incomplete data for %r' % p)
                    else:
                        for c in find_children(data[1], data[2]):
                            map[c.replace(data[1], p, 1)] = generate_file_id(revid, c), revid

            elif data[0] == 'M':
                if p == "":
                    map[p] = (ROOT_ID, "")
                assert map.has_key(p)
                map[p] = map[p][0], revid
            
            # Mark all parent paths as changed
            parts = p.split("/")
            for i in range(1, len(parts)):
                parent = "/".join(parts[0:len(parts)-i])
                mutter('parent %r for %r' % (parent, p))
                assert map.has_key(parent)
                if map[parent][1] == revid:
                    break
                map[parent] = map[parent][0], revid
        return map
