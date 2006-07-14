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

import pickle
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


class FileIdMap(object):
    """ File id store. 

    Keeps a map

    revnum -> branch -> path -> fileid
    """
    def __init__(self, log, cache_dir):
        self._log = log
        self.cache_weave = KnitVersionedFile('fileids-v%d' % MAPPING_VERSION, 
                get_transport(cache_dir),
                access_mode='w', create=True)

    def generate_file_id(self, revid, path):
        (uuid, branch, revnum) = parse_svn_revision_id(revid)
        return generate_svn_file_id(uuid, revnum, branch, path)

    def save(self, revid, parent_revids, _map):
        mutter('saving file id map for %r' % revid)
        def createline((p, v)):
            return "\t".join([p, v[0], v[1]]) + "\n"
        
        self.cache_weave.add_lines(revid, parent_revids, 
                                   map(createline, _map.items()))

    def load(self, revid):
        map = {}
        for l in self.cache_weave.get_lines(revid):
            (svn_path, fileid, revid) = l.strip("\n").split("\t") 
            map[svn_path] = (fileid, revid)
        return map

    def get_map(self, uuid, revnum, branch, pb=None):
        """Make sure the map is up to date until revnum."""
        # First, find the last cached map
        todo = []
        parent_revs = []
        map = {"": (ROOT_ID, None)} # No history -> empty map
        for (bp, paths, rev) in self._log.follow_local_history(branch, revnum):
            revid = generate_svn_revision_id(uuid, rev, bp)
            try:
                map = self.load(revid)
                # found the nearest cached map
                parent_revs = [revid]
                break
            except RevisionNotPresent:
                todo.append((revid, paths))
                continue
        
        # target revision was present
        if len(todo) == 0:
            return map
    
        todo.reverse()

        i = 0
        for (revid, changes) in todo:
            mutter('generating file id map for %r' % revid)
            if pb is not None:
                pb.update('generating file id map', i, len(todo))

            map = self._apply_changes(map, revid, changes)
            self.save(revid, parent_revs, map)
            parent_revs = [revid]
            i = i + 1

        if pb is not None:
            pb.clear()
        return map

    def copy_ids(self, base_map, orig_branch, map, dest_branch):
        for p in base_map:
            if p == orig_branch or p.startswith(orig_branch+"/"):
                map[p.replace(orig_branch, dest_branch, 1)] = base_map[p]
        return map

    def new_ids(self, base_map, orig_parent, map, dest_revid, dest_parent):
        for p in base_map:
            if p.startswith(orig_parent+"/"):
                new_p = p.replace(orig_parent, dest_parent, 1)
                map[new_p] = self.generate_file_id(dest_revid, new_p), dest_revid
        return map

class SimpleFileIdMap(FileIdMap):
    def _apply_changes(self, base_map, revid, changes):
        map = copy(base_map)

        map[""] = (ROOT_ID, revid)

        sorted_paths = changes.keys()
        sorted_paths.sort()
        for p in sorted_paths:
            data = changes[p]
            if data[0] in ('D', 'R'):
                assert map.has_key(p)
                del map[p]
                # FIXME: Delete all children of p

            if data[0] in ('A', 'R'):
                map[p] = self.generate_file_id(revid, p), revid

                if not data[1] is None:
                    mutter('%r:%s copied from %r:%s' % (p, revid, data[1], data[2]))
                    if p == "" and data[1] == "":
                        map = self.copy_ids(base_map, cbp, map, bp)
                    else:
                        map = self.new_ids(base_map, data[1], map, revid, p)
            elif data[0] == 'M':
                if p == "":
                    map[p] = (ROOT_ID, "")
                assert map.has_key(p)
                map[p] = map[p][0], revid
        return map

