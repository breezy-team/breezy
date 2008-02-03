# Copyright (C) 2006-2007 Jelmer Vernooij <jelmer@samba.org>

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
"""Generation of file-ids."""

from bzrlib import ui
from bzrlib.errors import NotBranchError, RevisionNotPresent
from bzrlib.knit import KnitVersionedFile
from bzrlib.revision import NULL_REVISION
from bzrlib.trace import mutter

import urllib

from mapping import escape_svn_path

def get_local_changes(paths, mapping, generate_revid, get_children=None):
    new_paths = {}
    for p in sorted(paths.keys()):
        data = paths[p]
        new_p = mapping.scheme.unprefix(p)[1]
        if data[1] is not None:
            try:
                (cbp, crp) = mapping.scheme.unprefix(data[1])

                # Branch copy
                if (crp == "" and new_p == ""):
                    data = ('M', None, None)
                else:
                    data = (data[0], crp, generate_revid(
                                  data[2], cbp, mapping))
            except NotBranchError:
                # Copied from outside of a known branch
                # Make it look like the files were added in this revision
                if get_children is not None:
                    for c in get_children(data[1], data[2]):
                        mutter('oops: %r child %r' % (data[1], c))
                        new_paths[(new_p+"/"+c[len(data[1]):].strip("/")).strip("/")] = (data[0], None, -1)
                data = (data[0], None, -1)

        new_paths[new_p] = data
    return new_paths


FILEIDMAP_VERSION = 1

class FileIdMap:
    """File id store. 

    Keeps a map

    revnum -> branch -> path -> fileid
    """
    def __init__(self, repos, cache_transport):
        self.repos = repos
        self.idmap_knit = KnitVersionedFile("fileidmap-v%d" % FILEIDMAP_VERSION, cache_transport, create=True)

    def save(self, revid, parent_revids, _map):
        mutter('saving file id map for %r' % revid)
                
        self.idmap_knit.add_lines_with_ghosts(revid, parent_revids, 
                ["%s\t%s\t%s\n" % (urllib.quote(filename), urllib.quote(_map[filename][0]), 
                                        urllib.quote(_map[filename][1])) for filename in sorted(_map.keys())])

    def load(self, revid):
        map = {}
        for line in self.idmap_knit.get_lines(revid):
            (filename, id, create_revid) = line.rstrip("\n").split("\t", 3)
            map[urllib.unquote(filename)] = (urllib.unquote(id), urllib.unquote(create_revid))
            assert isinstance(map[urllib.unquote(filename)][0], str)

        return map

    def apply_changes(self, uuid, revnum, branch, global_changes, 
                      renames, mapping, find_children=None):
        """Change file id map to incorporate specified changes.

        :param uuid: UUID of repository changes happen in
        :param revnum: Revno for revision in which changes happened
        :param branch: Branch path where changes happened
        :param global_changes: Dict with global changes that happened
        :param renames: List of renames (known file ids for particular paths)
        :param mapping: Mapping
        """
        changes = get_local_changes(global_changes, mapping,
                    self.repos.generate_revision_id, find_children)
        if find_children is not None:
            def get_children(path, revid):
                (bp, revnum, mapping) = self.repos.lookup_revision_id(revid)
                for p in find_children(bp+"/"+path, revnum):
                    yield mapping.unprefix(bp, p)
        else:
            get_children = None

        def new_file_id(x):
            return mapping.generate_file_id(self.repos.uuid, revnum, branch, x)
         
        idmap = self._apply_changes(new_file_id, changes, get_children)
        idmap.update(renames)
        return idmap

    def get_map(self, uuid, revnum, branch, renames_cb, mapping):
        """Make sure the map is up to date until revnum."""
        # First, find the last cached map
        todo = []
        next_parent_revs = []
        if revnum == 0:
            assert branch == ""
            return {"": (mapping.generate_file_id(uuid, revnum, branch, u""), 
              self.repos.generate_revision_id(revnum, branch, mapping))}

        quickrevidmap = {}

        # No history -> empty map
        for (bp, paths, rev) in self.repos.follow_branch_history(branch, 
                                             revnum, mapping):
            revid = self.repos.generate_revision_id(rev, bp, mapping)
            quickrevidmap[revid] = (rev, bp)
            try:
                map = self.load(revid)
                # found the nearest cached map
                next_parent_revs = [revid]
                break
            except RevisionNotPresent:
                todo.append((revid, paths))
   
        # target revision was present
        if len(todo) == 0:
            return map

        if len(next_parent_revs) == 0:
            if mapping.scheme.is_branch(""):
                map = {u"": (mapping.generate_file_id(uuid, 0, "", u""), NULL_REVISION)}
            else:
                map = {}

        pb = ui.ui_factory.nested_progress_bar()

        try:
            i = 1
            for (revid, global_changes) in reversed(todo):
                expensive = False
                def log_find_children(path, revnum):
                    expensive = True
                    return self.repos._log.find_children(path, revnum)
                changes = get_local_changes(global_changes, mapping,
                                            self.repos.generate_revision_id, 
                                            log_find_children)
                pb.update('generating file id map', i, len(todo))

                def find_children(path, revid):
                    (revnum, bp) = quickrevidmap[revid]
                    for p in log_find_children(bp+"/"+path, revnum):
                        yield mapping.unprefix(bp, p)

                parent_revs = next_parent_revs

                def new_file_id(x):
                    (revnum, branch) = quickrevidmap[revid]
                    return mapping.generate_file_id(self.repos.uuid, revnum, branch, x)
                
                revmap = self._apply_changes(new_file_id, changes, find_children)
                revmap.update(renames_cb(revid))

                for p in changes:
                    if changes[p][0] == 'M' and not revmap.has_key(p):
                        revmap[p] = map[p][0]

                map.update(dict([(x, (str(revmap[x]), revid)) for x in revmap]))

                # Mark all parent paths as changed
                for p in revmap:
                    parts = p.split("/")
                    for j in range(1, len(parts)+1):
                        parent = "/".join(parts[0:len(parts)-j])
                        assert map.has_key(parent), "Parent item %s of %s doesn't exist in map" % (parent, p)
                        if map[parent][1] == revid:
                            break
                        map[parent] = map[parent][0], revid
                        
                saved = False
                if i % 500 == 0 or expensive:
                    self.save(revid, parent_revs, map)
                    saved = True
                next_parent_revs = [revid]
                i += 1
        finally:
            pb.finished()
        if not saved:
            self.save(revid, parent_revs, map)
        return map


class SimpleFileIdMap(FileIdMap):
    @staticmethod
    def _apply_changes(new_file_id, changes, find_children=None):
        map = {}
        for p in sorted(changes.keys()):
            data = changes[p]

            if data[0] in ('A', 'R'):
                inv_p = p.decode("utf-8")
                map[inv_p] = new_file_id(inv_p)

                if data[1] is not None:
                    mutter('%r copied from %r:%s' % (inv_p, data[1], data[2]))
                    if find_children is not None:
                        for c in find_children(data[1], data[2]):
                            inv_c = c.decode("utf-8")
                            path = c.replace(data[1].decode("utf-8"), inv_p+"/", 1).replace(u"//", u"/")
                            map[path] = new_file_id(path)
                            mutter('added mapping %r -> %r' % (path, map[path]))

        return map
