# Copyright (C) 2006-2007 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
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
from bzrlib.knit import make_file_factory
from bzrlib.revision import NULL_REVISION
from bzrlib.trace import mutter
from bzrlib.versionedfile import ConstantMapper

import urllib

from bzrlib.plugins.svn import changes

def get_local_changes(paths, branch, mapping, layout, generate_revid, 
                      get_children=None):
    """Obtain all of the changes relative to a particular path
    (usually a branch path).

    :param paths: Changes
    :param branch: Path under which to select changes
    :param mapping: Mapping to use to determine what are valid branch paths
    :param layout: Layout to use 
    :param generate_revid: Function for generating revision id from svn revnum
    :param get_children: Function for obtaining the children of a path
    """
    new_paths = {}
    for p in sorted(paths.keys(), reverse=False):
        if not changes.path_is_child(branch, p):
            continue
        data = paths[p]
        new_p = layout.parse(p)[3]
        if data[1] is not None:
            try:
                (pt, proj, cbp, crp) = layout.parse(data[1])

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
                        mutter('oops: %r child %r', data[1], c)
                        new_paths[(new_p+"/"+c[len(data[1]):].strip("/")).strip("/")] = (data[0], None, -1)
                data = (data[0], None, -1)

        new_paths[new_p] = data
    return new_paths


FILEIDMAP_VERSION = 2

def simple_apply_changes(new_file_id, changes, find_children=None):
    """Simple function that generates a dictionary with file id changes.
    
    Does not track renames. """
    map = {}
    for p in sorted(changes.keys(), reverse=False):
        data = changes[p]

        inv_p = p.decode("utf-8")
        if data[0] in ('D', 'R'):
            if not inv_p in map:
                map[inv_p] = None
        if data[0] in ('A', 'R'):
            map[inv_p] = new_file_id(inv_p)

            if data[1] is not None:
                mutter('%r copied from %r:%s', inv_p, data[1], data[2])
                if find_children is not None:
                    for c in find_children(data[1], data[2]):
                        inv_c = c.decode("utf-8")
                        path = c.replace(data[1].decode("utf-8"), inv_p+"/", 1).replace(u"//", u"/")
                        map[path] = new_file_id(path)
                        mutter('added mapping %r -> %r', path, map[path])

    return map


class FileIdMap(object):
    """File id store. 

    Keeps a map

    revnum -> branch -> path -> fileid
    """
    def __init__(self, apply_changes_fn, repos):
        self.apply_changes_fn = apply_changes_fn
        self.repos = repos

    def _use_text_revids(self, mapping, revmeta, map):
        text_revids = mapping.import_text_revisions(revmeta.revprops, revmeta.fileprops).items()
        for path, revid in text_revids:
            assert path in map
            map[path] = (map[path][0], revid)

    def apply_changes(self, revmeta, mapping, find_children=None):
        """Change file id map to incorporate specified changes.

        :param revmeta: RevisionMetadata object for revision with changes
        :param renames: List of renames (known file ids for particular paths)
        :param mapping: Mapping
        """
        renames = mapping.import_fileid_map(revmeta.revprops, revmeta.fileprops)
        assert revmeta.paths is not None
        changes = get_local_changes(revmeta.paths, revmeta.branch_path, mapping,
                    self.repos.get_layout(),
                    self.repos.generate_revision_id, find_children)
        if find_children is not None:
            def get_children(path, revid):
                (bp, revnum, mapping) = self.repos.lookup_revision_id(revid)
                for p in find_children(bp+"/"+path, revnum):
                    yield mapping.unprefix(bp, p)
        else:
            get_children = None

        def new_file_id(x):
            return mapping.generate_file_id(revmeta.uuid, revmeta.revnum, revmeta.branch_path, x)
         
        idmap = self.apply_changes_fn(new_file_id, changes, get_children)
        idmap.update(renames)
        return (idmap, changes)

    def get_map(self, uuid, revnum, branch, mapping):
        """Make sure the map is up to date until revnum."""
        # First, find the last cached map
        if revnum == 0:
            assert branch == ""
            return {"": (mapping.generate_file_id(uuid, 0, "", u""), 
              self.repos.generate_revision_id(0, "", mapping))}

        todo = []
        next_parent_revs = []
        if mapping.is_branch(""):
            map = {u"": (mapping.generate_file_id(uuid, 0, "", u""), NULL_REVISION)}
        else:
            map = {}

        # No history -> empty map
        for revmeta in self.repos.iter_reverse_branch_changes(branch, revnum, to_revnum=0, mapping=mapping):
            revid = revmeta.get_revision_id(mapping)
            todo.append(revmeta)
   
        pb = ui.ui_factory.nested_progress_bar()

        try:
            for i, revmeta in enumerate(reversed(todo)):
                pb.update('generating file id map', i, len(todo))
                revid = revmeta.get_revision_id(mapping)
                (idmap, changes) = self.apply_changes(revmeta, 
                        mapping, self.repos._log.find_children)
                self.update_map(map, revid, idmap, changes)
                self._use_text_revids(mapping, revmeta, map)

                parent_revs = next_parent_revs

                next_parent_revs = [revid]
        finally:
            pb.finished()
        return map

    def update_map(self, map, revid, delta, changes):
        """Update a file id map.

        :param map: Existing file id map.
        :param revid: Revision id of the id map
        :param delta: Id map for just the delta
        :param changes: Changes in revid.
        """
        for p in changes:
            if changes[p][0] == 'M' and not delta.has_key(p):
                delta[p] = map[p][0]
        
        for x in sorted(delta.keys(), reverse=True):
            if delta[x] is None:
                del map[x]
                for p in map.keys():
                    if p.startswith(u"%s/" % x):
                        del map[p]

        for x in sorted(delta.keys()):
            if (delta[x] is not None and 
                # special case - we change metadata in svn at the branch root path
                # but that's not reflected as a bzr metadata change in bzr
                (x != "" or not "" in map or map[x][1] == NULL_REVISION)):
                map[x] = (str(delta[x]), revid)


class FileIdMapCache(object):

    def __init__(self, cache_transport):
        mapper = ConstantMapper("fileidmap-v%d" % FILEIDMAP_VERSION)
        self.idmap_knit = make_file_factory(True, mapper)(cache_transport)

    def save(self, revid, parent_revids, _map):
        mutter('saving file id map for %r', revid)

        for path, (id, created_revid)  in _map.items():
            assert isinstance(path, unicode)
            assert isinstance(id, str)
            assert isinstance(created_revid, str)

        self.idmap_knit.add_lines((revid,), [(r, ) for r in parent_revids], 
                ["%s\t%s\t%s\n" % (urllib.quote(filename.encode("utf-8")), urllib.quote(_map[filename][0]), 
                                        urllib.quote(_map[filename][1])) for filename in sorted(_map.keys())])

    def load(self, revid):
        map = {}
        for ((create_revid,), line) in self.idmap_knit.annotate((revid,)):
            (filename, id, create_revid) = line.rstrip("\n").split("\t", 3)
            map[urllib.unquote(filename).decode("utf-8")] = (urllib.unquote(id), urllib.unquote(create_revid))
            assert isinstance(map[urllib.unquote(filename).decode("utf-8")][0], str)

        return map


class CachingFileIdMap(object):
    """A file id map that uses a cache."""
    def __init__(self, cache_transport, actual):
        self.cache = FileIdMapCache(cache_transport)
        self.actual = actual
        self.apply_changes = actual.apply_changes
        self._use_text_revids = actual._use_text_revids
        self.repos = actual.repos

    def get_map(self, uuid, revnum, branch, mapping):
        """Make sure the map is up to date until revnum."""
        # First, find the last cached map
        if revnum == 0:
            assert branch == ""
            return {"": (mapping.generate_file_id(uuid, 0, "", u""), 
              self.repos.generate_revision_id(0, "", mapping))}

        todo = []
        next_parent_revs = []

        # No history -> empty map
        try:
            pb = ui.ui_factory.nested_progress_bar()
            for revmeta in self.repos.iter_reverse_branch_changes(branch, revnum, to_revnum=0, mapping=mapping):
                pb.update("fetching changes for file ids", revnum-revmeta.revnum, revnum)
                revid = revmeta.get_revision_id(mapping)
                try:
                    map = self.cache.load(revid)
                    # found the nearest cached map
                    next_parent_revs = [revid]
                    break
                except RevisionNotPresent:
                    todo.append(revmeta)
        finally:
            pb.finished()
       
        # target revision was present
        if len(todo) == 0:
            return map

        if len(next_parent_revs) == 0:
            if mapping.is_branch(""):
                map = {u"": (mapping.generate_file_id(uuid, 0, "", u""), NULL_REVISION)}
            else:
                map = {}

        pb = ui.ui_factory.nested_progress_bar()

        try:
            for i, revmeta in enumerate(reversed(todo)):
                pb.update('generating file id map', i, len(todo))
                revid = revmeta.get_revision_id(mapping)
                def log_find_children(path, revnum):
                    return self.repos._log.find_children(path, revnum)

                (idmap, changes) = self.actual.apply_changes(
                        revmeta, mapping, log_find_children)

                self.actual.update_map(map, revid, idmap, changes)
                self._use_text_revids(mapping, revmeta, map)

                parent_revs = next_parent_revs
                       
                self.cache.save(revid, parent_revs, map)
                next_parent_revs = [revid]
        finally:
            pb.finished()
        return map

