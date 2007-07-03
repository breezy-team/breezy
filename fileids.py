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

from bzrlib.errors import NotBranchError
from bzrlib.revision import NULL_REVISION
from bzrlib.trace import mutter
import bzrlib.ui as ui

import sha

from revids import escape_svn_path

def generate_svn_file_id(uuid, revnum, branch, path):
    """Create a file id identifying a Subversion file.

    :param uuid: UUID of the repository
    :param revnu: Revision number at which the file was introduced.
    :param branch: Branch path of the branch in which the file was introduced.
    :param path: Original path of the file within the branch
    """
    ret = "%d@%s:%s:%s" % (revnum, uuid, escape_svn_path(branch), escape_svn_path(path))
    if len(ret) > 150:
        ret = "%d@%s:%s;%s" % (revnum, uuid, 
                            escape_svn_path(branch),
                            sha.new(path).hexdigest())
    assert isinstance(ret, str)
    return ret


def generate_file_id(repos, revid, path):
    (branch, revnum, _) = repos.lookup_revision_id(revid)
    return generate_svn_file_id(repos.uuid, revnum, branch, path)


def get_local_changes(paths, scheme, generate_revid, get_children=None):
    new_paths = {}
    names = paths.keys()
    names.sort()
    for p in names:
        data = paths[p]
        new_p = scheme.unprefix(p)[1]
        if data[1] is not None:
            try:
                (cbp, crp) = scheme.unprefix(data[1])

                # Branch copy
                if (crp == "" and new_p == ""):
                    data = ('M', None, None)
                else:
                    data = (data[0], crp, generate_revid(
                                  data[2], cbp.encode("utf-8"), str(scheme)))
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


class FileIdMap(object):
    """ File id store. 

    Keeps a map

    revnum -> branch -> path -> fileid
    """
    def __init__(self, repos, cache_db):
        self.repos = repos
        self.cachedb = cache_db
        self.cachedb.executescript("""
        create table if not exists filemap (filename text, id integer, create_revid text, revid text);
        create index if not exists revid on filemap(revid);
        """)
        self.cachedb.commit()

    def save(self, revid, parent_revids, _map):
        mutter('saving file id map for %r' % revid)
        for filename in _map:
            self.cachedb.execute("insert into filemap (filename, id, create_revid, revid) values(?,?,?,?)", (filename, _map[filename][0], _map[filename][1], revid))
        self.cachedb.commit()

    def load(self, revid):
        map = {}
        for filename, create_revid, id in self.cachedb.execute("select filename, create_revid, id from filemap where revid='%s'"%revid):
            map[filename] = (id.encode("utf-8"), create_revid.encode("utf-8"))
            assert isinstance(map[filename][0], str)

        return map

    def apply_changes(self, uuid, revnum, branch, global_changes, 
                      renames, scheme, find_children=None):
        """Change file id map to incorporate specified changes.

        :param uuid: UUID of repository changes happen in
        :param revnum: Revno for revision in which changes happened
        :param branch: Branch path where changes happened
        :param global_changes: Dict with global changes that happened
        :param renames: List of renames
        :param scheme: Branching scheme
        """
        changes = get_local_changes(global_changes, scheme,
                    self.repos.generate_revision_id, find_children)
        if find_children is not None:
            def get_children(path, revid):
                (bp, revnum, scheme) = self.repos.lookup_revision_id(revid)
                for p in find_children(bp+"/"+path, revnum):
                    yield scheme.unprefix(p)[1]
        else:
            get_children = None

        revid = self.repos.generate_revision_id(revnum, branch, scheme)

        def new_file_id(x):
            if renames.has_key(x):
                return renames[x]
            return generate_file_id(self.repos, revid, x)
         
        return self._apply_changes(new_file_id, changes, get_children)

    def get_map(self, uuid, revnum, branch, renames_cb, scheme):
        """Make sure the map is up to date until revnum."""
        # First, find the last cached map
        todo = []
        next_parent_revs = []
        if revnum == 0:
            assert branch == ""
            return {"": (generate_svn_file_id(uuid, revnum, branch, ""), 
              self.repos.generate_revision_id(revnum, branch, scheme))}

        # No history -> empty map
        for (bp, paths, rev) in self.repos.follow_branch_history(branch, 
                                             revnum, scheme):
            revid = self.repos.generate_revision_id(rev, bp.encode("utf-8"), 
                                                    scheme)
            map = self.load(revid)
            if map != {}:
                # found the nearest cached map
                next_parent_revs = [revid]
                break
            todo.append((revid, paths))
   
        # target revision was present
        if len(todo) == 0:
            return map

        if len(next_parent_revs) == 0:
            if scheme.is_branch(""):
                map = {"": (generate_svn_file_id(uuid, 0, "", ""), NULL_REVISION)}
            else:
                map = {}

        todo.reverse()
        
        pb = ui.ui_factory.nested_progress_bar()

        try:
            i = 1
            for (revid, global_changes) in todo:
                changes = get_local_changes(global_changes, scheme,
                                            self.repos.generate_revision_id, 
                                            self.repos._log.find_children)
                pb.update('generating file id map', i, len(todo))

                def find_children(path, revid):
                    (bp, revnum, scheme) = self.repos.lookup_revision_id(revid)
                    for p in self.repos._log.find_children(bp+"/"+path, revnum):
                        yield scheme.unprefix(p)[1]

                parent_revs = next_parent_revs

                renames = renames_cb(revid)

                def new_file_id(x):
                    if renames.has_key(x):
                        return renames[x]
                    return generate_file_id(self.repos, revid, x)
                
                revmap = self._apply_changes(new_file_id, changes, find_children)
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
                        
                next_parent_revs = [revid]
                i += 1
        finally:
            pb.finished()
        self.save(revid, parent_revs, map)
        return map


class SimpleFileIdMap(FileIdMap):
    @staticmethod
    def _apply_changes(new_file_id, changes, find_children=None):
        map = {}
        sorted_paths = changes.keys()
        sorted_paths.sort()
        for p in sorted_paths:
            data = changes[p]

            if data[0] in ('A', 'R'):
                map[p] = new_file_id(p)

                if data[1] is not None:
                    mutter('%r copied from %r:%s' % (p, data[1], data[2]))
                    if find_children is not None:
                        for c in find_children(data[1], data[2]):
                            path = c.replace(data[1], p+"/", 1).replace("//", "/")
                            map[path] = new_file_id(path)
                            mutter('added mapping %r -> %r' % (path, map[path]))

        return map
