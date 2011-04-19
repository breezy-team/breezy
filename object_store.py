# Copyright (C) 2009 Jelmer Vernooij <jelmer@samba.org>
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Map from Git sha's to Bazaar objects."""

from dulwich.objects import (
    Blob,
    Commit,
    Tree,
    sha_to_hex,
    ZERO_SHA,
    )
from dulwich.object_store import (
    BaseObjectStore,
    )

from bzrlib import (
    errors,
    lru_cache,
    trace,
    ui,
    urlutils,
    )
from bzrlib.revision import (
    NULL_REVISION,
    )
from bzrlib.testament import(
    StrictTestament3,
    )

from bzrlib.plugins.git.mapping import (
    default_mapping,
    directory_to_tree,
    extract_unusual_modes,
    mapping_registry,
    symlink_to_blob,
    )
from bzrlib.plugins.git.cache import (
    from_repository as cache_from_repository,
    )

import posixpath
import stat


def get_object_store(repo, mapping=None):
    git = getattr(repo, "_git", None)
    if git is not None:
        return git.object_store
    return BazaarObjectStore(repo, mapping)


MAX_TREE_CACHE_SIZE = 50 * 1024 * 1024


class LRUTreeCache(object):

    def __init__(self, repository):
        def approx_tree_size(tree):
            # Very rough estimate, 1k per inventory entry
            return len(tree.inventory) * 1024
        self.repository = repository
        self._cache = lru_cache.LRUSizeCache(max_size=MAX_TREE_CACHE_SIZE,
            after_cleanup_size=None, compute_size=approx_tree_size)

    def revision_tree(self, revid):
        try:
            tree = self._cache[revid]
        except KeyError:
            tree = self.repository.revision_tree(revid)
            self.add(tree)
        assert tree.get_revision_id() == tree.inventory.revision_id
        return tree

    def iter_revision_trees(self, revids):
        trees = {}
        todo = []
        for revid in revids:
            try:
                tree = self._cache[revid]
            except KeyError:
                todo.append(revid)
            else:
                assert tree.get_revision_id() == revid
                trees[revid] = tree
        for tree in self.repository.revision_trees(todo):
            trees[tree.get_revision_id()] = tree
            self.add(tree)
        return (trees[r] for r in revids)

    def revision_trees(self, revids):
        return list(self.iter_revision_trees(revids))

    def add(self, tree):
        self._cache.add(tree.get_revision_id(), tree)


def _find_missing_bzr_revids(graph, want, have):
    """Find the revisions that have to be pushed.

    :param get_parent_map: Function that returns the parents for a sequence
        of revisions.
    :param want: Revisions the target wants
    :param have: Revisions the target already has
    :return: Set of revisions to fetch
    """
    todo = set()
    for rev in want:
        todo.update(graph.find_unique_ancestors(rev, have))
    if NULL_REVISION in todo:
        todo.remove(NULL_REVISION)
    return todo


def _check_expected_sha(expected_sha, object):
    """Check whether an object matches an expected SHA.

    :param expected_sha: None or expected SHA as either binary or as hex digest
    :param object: Object to verify
    """
    if expected_sha is None:
        return
    if len(expected_sha) == 40:
        if expected_sha != object.sha().hexdigest():
            raise AssertionError("Invalid sha for %r: %s" % (object,
                expected_sha))
    elif len(expected_sha) == 20:
        if expected_sha != object.sha().digest():
            raise AssertionError("Invalid sha for %r: %s" % (object,
                sha_to_hex(expected_sha)))
    else:
        raise AssertionError("Unknown length %d for %r" % (len(expected_sha),
            expected_sha))


def _tree_to_objects(tree, parent_trees, idmap, unusual_modes,
                     dummy_file_name=None):
    """Iterate over the objects that were introduced in a revision.

    :param idmap: id map
    :param parent_trees: Parent revision trees
    :param unusual_modes: Unusual file modes dictionary
    :param dummy_file_name: File name to use for dummy files
        in empty directories. None to skip empty directories
    :return: Yields (path, object, ie) entries
    """
    new_trees = {}
    new_blobs = []
    shamap = {}
    try:
        base_tree = parent_trees[0]
        other_parent_trees = parent_trees[1:]
    except IndexError:
        base_tree = tree._repository.revision_tree(NULL_REVISION)
        other_parent_trees = []
    def find_unchanged_parent_ie(ie, parent_trees):
        assert ie.kind in ("symlink", "file")
        for ptree in parent_trees:
            try:
                pie = ptree.inventory[ie.file_id]
            except errors.NoSuchId:
                pass
            else:
                if (pie.text_sha1 == ie.text_sha1 and 
                    pie.kind == ie.kind and
                    pie.symlink_target == ie.symlink_target):
                    return pie
        raise KeyError

    # Find all the changed blobs
    for (file_id, path, changed_content, versioned, parent, name, kind,
         executable) in tree.iter_changes(base_tree):
        if kind[1] == "file":
            ie = tree.inventory[file_id]
            if changed_content:
                try:
                    pie = find_unchanged_parent_ie(ie, other_parent_trees)
                except KeyError:
                    pass
                else:
                    try:
                        shamap[ie.file_id] = idmap.lookup_blob_id(
                            pie.file_id, pie.revision)
                    except KeyError:
                        # no-change merge ?
                        blob = Blob()
                        blob.data = tree.get_file_text(ie.file_id)
                        shamap[ie.file_id] = blob.id
            if not file_id in shamap:
                new_blobs.append((path[1], ie))
            new_trees[posixpath.dirname(path[1])] = parent[1]
        elif kind[1] == "symlink":
            ie = tree.inventory[file_id]
            if changed_content:
                blob = symlink_to_blob(ie)
                shamap[file_id] = blob.id
                try:
                    find_unchanged_parent_ie(ie, other_parent_trees)
                except KeyError:
                    yield path[1], blob, ie
            new_trees[posixpath.dirname(path[1])] = parent[1]
        elif kind[1] not in (None, "directory"):
            raise AssertionError(kind[1])
        if (path[0] not in (None, "") and
            parent[0] in tree.inventory and
            tree.inventory[parent[0]].kind == "directory"):
            # Removal
            new_trees[posixpath.dirname(path[0])] = parent[0]
    
    # Fetch contents of the blobs that were changed
    for (path, ie), chunks in tree.iter_files_bytes(
        [(ie.file_id, (path, ie)) for (path, ie) in new_blobs]):
        obj = Blob()
        obj.chunked = chunks
        yield path, obj, ie
        shamap[ie.file_id] = obj.id

    for path in unusual_modes:
        parent_path = posixpath.dirname(path)
        new_trees[parent_path] = tree.path2id(parent_path)

    trees = {}
    while new_trees:
        items = new_trees.items()
        new_trees = {}
        for path, file_id in items:
            parent_id = tree.inventory[file_id].parent_id
            if parent_id is not None:
                parent_path = urlutils.dirname(path)
                new_trees[parent_path] = parent_id
            trees[path] = file_id

    def ie_to_hexsha(ie):
        try:
            return shamap[ie.file_id]
        except KeyError:
            # FIXME: Should be the same as in parent
            if ie.kind in ("file", "symlink"):
                try:
                    return idmap.lookup_blob_id(ie.file_id, ie.revision)
                except KeyError:
                    # no-change merge ?
                    blob = Blob()
                    blob.data = tree.get_file_text(ie.file_id)
                    return blob.id
            elif ie.kind == "directory":
                # Not all cache backends store the tree information, 
                # calculate again from scratch
                ret = directory_to_tree(ie, ie_to_hexsha, unusual_modes,
                    dummy_file_name)
                if ret is None:
                    return ret
                return ret.id
            else:
                raise AssertionError

    for path in sorted(trees.keys(), reverse=True):
        ie = tree.inventory[trees[path]]
        assert ie.kind == "directory"
        obj = directory_to_tree(ie, ie_to_hexsha, unusual_modes,
            dummy_file_name)
        if obj is not None:
            yield path, obj, ie
            shamap[ie.file_id] = obj.id


class BazaarObjectStore(BaseObjectStore):
    """A Git-style object store backed onto a Bazaar repository."""

    def __init__(self, repository, mapping=None):
        self.repository = repository
        if mapping is None:
            self.mapping = default_mapping
        else:
            self.mapping = mapping
        self._cache = cache_from_repository(repository)
        self._content_cache_types = ("tree")
        self.start_write_group = self._cache.idmap.start_write_group
        self.abort_write_group = self._cache.idmap.abort_write_group
        self.commit_write_group = self._cache.idmap.commit_write_group
        self.tree_cache = LRUTreeCache(self.repository)

    def _update_sha_map(self, stop_revision=None):
        graph = self.repository.get_graph()
        if stop_revision is None:
            heads = graph.heads(self.repository.all_revision_ids())
        else:
            heads = set([stop_revision])
        missing_revids = self._cache.idmap.missing_revisions(heads)
        while heads:
            parents = graph.get_parent_map(heads)
            todo = set()
            for p in parents.values():
                todo.update([x for x in p if x not in missing_revids])
            heads = self._cache.idmap.missing_revisions(todo)
            missing_revids.update(heads)
        if NULL_REVISION in missing_revids:
            missing_revids.remove(NULL_REVISION)
        missing_revids = self.repository.has_revisions(missing_revids)
        if not missing_revids:
            return
        self.start_write_group()
        try:
            pb = ui.ui_factory.nested_progress_bar()
            try:
                for i, revid in enumerate(graph.iter_topo_order(missing_revids)):
                    trace.mutter('processing %r', revid)
                    pb.update("updating git map", i, len(missing_revids))
                    self._update_sha_map_revision(revid)
            finally:
                pb.finished()
        except:
            self.abort_write_group()
            raise
        else:
            self.commit_write_group()

    def __iter__(self):
        self._update_sha_map()
        return iter(self._cache.idmap.sha1s())

    def _reconstruct_commit(self, rev, tree_sha, roundtrip, verifiers):
        """Reconstruct a Commit object.

        :param rev: Revision object
        :param tree_sha: SHA1 of the root tree object
        :param roundtrip: Whether or not to roundtrip bzr metadata
        :param verifiers: Verifiers for the commits
        :return: Commit object
        """
        def parent_lookup(revid):
            try:
                return self._lookup_revision_sha1(revid)
            except errors.NoSuchRevision:
                return None
        return self.mapping.export_commit(rev, tree_sha, parent_lookup,
            roundtrip, verifiers)

    def _create_fileid_map_blob(self, inv):
        # FIXME: This can probably be a lot more efficient, 
        # not all files necessarily have to be processed.
        file_ids = {}
        for (path, ie) in inv.iter_entries():
            if self.mapping.generate_file_id(path) != ie.file_id:
                file_ids[path] = ie.file_id
        return self.mapping.export_fileid_map(file_ids)

    def _revision_to_objects(self, rev, tree, roundtrip):
        """Convert a revision to a set of git objects.

        :param rev: Bazaar revision object
        :param tree: Bazaar revision tree
        :param roundtrip: Whether to roundtrip all Bazaar revision data
        """
        unusual_modes = extract_unusual_modes(rev)
        present_parents = self.repository.has_revisions(rev.parent_ids)
        parent_trees = self.tree_cache.revision_trees(
            [p for p in rev.parent_ids if p in present_parents])
        root_tree = None
        for path, obj, ie in _tree_to_objects(tree, parent_trees,
                self._cache.idmap, unusual_modes, self.mapping.BZR_DUMMY_FILE):
            if path == "":
                root_tree = obj
                root_ie = ie
                # Don't yield just yet
            else:
                yield path, obj, ie
        if root_tree is None:
            # Pointless commit - get the tree sha elsewhere
            if not rev.parent_ids:
                root_tree = Tree()
            else:
                base_sha1 = self._lookup_revision_sha1(rev.parent_ids[0])
                root_tree = self[self[base_sha1].tree]
            root_ie = tree.inventory.root
        if roundtrip and self.mapping.BZR_FILE_IDS_FILE is not None:
            b = self._create_fileid_map_blob(tree.inventory)
            if b is not None:
                root_tree[self.mapping.BZR_FILE_IDS_FILE] = ((stat.S_IFREG | 0644), b.id)
                yield self.mapping.BZR_FILE_IDS_FILE, b, None
        yield "", root_tree, root_ie
        if roundtrip:
            testament3 = StrictTestament3(rev, tree.inventory)
            verifiers = { "testament3-sha1": testament3.as_sha1() }
        else:
            verifiers = {}
        commit_obj = self._reconstruct_commit(rev, root_tree.id,
            roundtrip=roundtrip, verifiers=verifiers)
        try:
            foreign_revid, mapping = mapping_registry.parse_revision_id(
                rev.revision_id)
        except errors.InvalidRevisionId:
            pass
        else:
            _check_expected_sha(foreign_revid, commit_obj)
        yield None, commit_obj, None

    def _get_updater(self, rev):
        return self._cache.get_updater(rev)

    def _update_sha_map_revision(self, revid):
        rev = self.repository.get_revision(revid)
        tree = self.tree_cache.revision_tree(rev.revision_id)
        updater = self._get_updater(rev)
        for path, obj, ie in self._revision_to_objects(rev, tree,
            roundtrip=True):
            if isinstance(obj, Commit):
                testament3 = StrictTestament3(rev, tree.inventory)
                ie = { "testament3-sha1": testament3.as_sha1() }
            updater.add_object(obj, ie, path)
        commit_obj = updater.finish()
        return commit_obj.id

    def _reconstruct_blobs(self, keys):
        """Return a Git Blob object from a fileid and revision stored in bzr.

        :param fileid: File id of the text
        :param revision: Revision of the text
        """
        stream = self.repository.iter_files_bytes(
            ((key[0], key[1], key) for key in keys))
        for (fileid, revision, expected_sha), chunks in stream:
            blob = Blob()
            blob.chunked = chunks
            if blob.id != expected_sha and blob.data == "":
                # Perhaps it's a symlink ?
                tree = self.tree_cache.revision_tree(revision)
                entry = tree.inventory[fileid]
                if entry.kind == 'symlink':
                    blob = symlink_to_blob(entry)
            _check_expected_sha(expected_sha, blob)
            yield blob

    def _reconstruct_tree(self, fileid, revid, inv, unusual_modes,
        expected_sha=None):
        """Return a Git Tree object from a file id and a revision stored in bzr.

        :param fileid: fileid in the tree.
        :param revision: Revision of the tree.
        """
        def get_ie_sha1(entry):
            if entry.kind == "directory":
                try:
                    return self._cache.idmap.lookup_tree_id(entry.file_id,
                        revid)
                except (NotImplementedError, KeyError):
                    obj = self._reconstruct_tree(entry.file_id, revid, inv,
                        unusual_modes)
                    if obj is None:
                        return None
                    else:
                        return obj.id
            elif entry.kind in ("file", "symlink"):
                try:
                    return self._cache.idmap.lookup_blob_id(entry.file_id,
                        entry.revision)
                except KeyError:
                    # no-change merge?
                    return self._reconstruct_blobs(
                        [(entry.file_id, entry.revision, None)]).next().id
            else:
                raise AssertionError("unknown entry kind '%s'" % entry.kind)
        tree = directory_to_tree(inv[fileid], get_ie_sha1, unusual_modes,
            self.mapping.BZR_DUMMY_FILE)
        if (inv.root.file_id == fileid and
            self.mapping.BZR_FILE_IDS_FILE is not None):
            b = self._create_fileid_map_blob(inv)
            # If this is the root tree, add the file ids
            tree[self.mapping.BZR_FILE_IDS_FILE] = ((stat.S_IFREG | 0644), b.id)
        _check_expected_sha(expected_sha, tree)
        return tree

    def get_parents(self, sha):
        """Retrieve the parents of a Git commit by SHA1.

        :param sha: SHA1 of the commit
        :raises: KeyError, NotCommitError
        """
        return self[sha].parents

    def _lookup_revision_sha1(self, revid):
        """Return the SHA1 matching a Bazaar revision."""
        if revid == NULL_REVISION:
            return ZERO_SHA
        try:
            return self._cache.idmap.lookup_commit(revid)
        except KeyError:
            try:
                return mapping_registry.parse_revision_id(revid)[0]
            except errors.InvalidRevisionId:
                self.repository.lock_read()
                try:
                    self._update_sha_map(revid)
                finally:
                    self.repository.unlock()
                return self._cache.idmap.lookup_commit(revid)

    def get_raw(self, sha):
        """Get the raw representation of a Git object by SHA1.

        :param sha: SHA1 of the git object
        """
        obj = self[sha]
        return (obj.type, obj.as_raw_string())

    def __contains__(self, sha):
        # See if sha is in map
        try:
            for (type, type_data) in self.lookup_git_sha(sha):
                if type == "commit":
                    if self.repository.has_revision(type_data[0]):
                        return True
                elif type == "blob":
                    if self.repository.texts.has_key(type_data):
                        return True
                elif type == "tree":
                    if self.repository.has_revision(type_data[1]):
                        return True
                else:
                    raise AssertionError("Unknown object type '%s'" % type)
            else:
                return False
        except KeyError:
            return False

    def lookup_git_shas(self, shas, update_map=True):
        ret = {}
        for sha in shas:
            if sha == ZERO_SHA:
                ret[sha] = [("commit", (NULL_REVISION, None, {}))]
                continue
            try:
                ret[sha] = list(self._cache.idmap.lookup_git_sha(sha))
            except KeyError:
                if update_map:
                    # if not, see if there are any unconverted revisions and add
                    # them to the map, search for sha in map again
                    self._update_sha_map()
                    update_map = False
                    try:
                        ret[sha] = list(self._cache.idmap.lookup_git_sha(sha))
                    except KeyError:
                        pass
        return ret

    def lookup_git_sha(self, sha, update_map=True):
        return self.lookup_git_shas([sha], update_map=update_map)[sha]

    def __getitem__(self, sha):
        if self._cache.content_cache is not None:
            try:
                return self._cache.content_cache[sha]
            except KeyError:
                pass
        for (kind, type_data) in self.lookup_git_sha(sha):
            # convert object to git object
            if kind == "commit":
                (revid, tree_sha, verifiers) = type_data
                try:
                    rev = self.repository.get_revision(revid)
                except errors.NoSuchRevision:
                    trace.mutter('entry for %s %s in shamap: %r, but not '
                                 'found in repository', kind, sha, type_data)
                    raise KeyError(sha)
                commit = self._reconstruct_commit(rev, tree_sha, roundtrip=True,
                    verifiers=verifiers)
                _check_expected_sha(sha, commit)
                return commit
            elif kind == "blob":
                (fileid, revision) = type_data
                return self._reconstruct_blobs([(fileid, revision, sha)]).next()
            elif kind == "tree":
                (fileid, revid) = type_data
                try:
                    tree = self.tree_cache.revision_tree(revid)
                    rev = self.repository.get_revision(revid)
                except errors.NoSuchRevision:
                    trace.mutter('entry for %s %s in shamap: %r, but not found in repository', kind, sha, type_data)
                    raise KeyError(sha)
                unusual_modes = extract_unusual_modes(rev)
                try:
                    return self._reconstruct_tree(fileid, revid,
                        tree.inventory, unusual_modes, expected_sha=sha)
                except errors.NoSuchRevision:
                    raise KeyError(sha)
            else:
                raise AssertionError("Unknown object type '%s'" % kind)
        else:
            raise KeyError(sha)

    def generate_lossy_pack_contents(self, have, want, progress=None,
            get_tagged=None):
        return self.generate_pack_contents(have, want, progress, get_tagged,
            lossy=True)

    def generate_pack_contents(self, have, want, progress=None,
            get_tagged=None, lossy=False):
        """Iterate over the contents of a pack file.

        :param have: List of SHA1s of objects that should not be sent
        :param want: List of SHA1s of objects that should be sent
        """
        processed = set()
        ret = self.lookup_git_shas(have + want)
        for commit_sha in have:
            try:
                for (type, type_data) in ret[commit_sha]:
                    assert type == "commit"
                    processed.add(type_data[0])
            except KeyError:
                pass
        pending = set()
        for commit_sha in want:
            if commit_sha in have:
                continue
            try:
                for (type, type_data) in ret[commit_sha]:
                    assert type == "commit"
                    pending.add(type_data[0])
            except KeyError:
                pass

        graph = self.repository.get_graph()
        todo = _find_missing_bzr_revids(graph, pending, processed)
        trace.mutter('sending revisions %r', todo)
        ret = []
        pb = ui.ui_factory.nested_progress_bar()
        try:
            for i, revid in enumerate(todo):
                pb.update("generating git objects", i, len(todo))
                try:
                    rev = self.repository.get_revision(revid)
                except errors.NoSuchRevision:
                    continue
                tree = self.tree_cache.revision_tree(revid)
                for path, obj, ie in self._revision_to_objects(rev, tree,
                    roundtrip=not lossy):
                    ret.append((obj, path))
        finally:
            pb.finished()
        return ret

    def add_thin_pack(self):
        import tempfile
        import os
        fd, path = tempfile.mkstemp(suffix=".pack")
        f = os.fdopen(fd, 'wb')
        def commit():
            from dulwich.pack import PackData, Pack
            from bzrlib.plugins.git.fetch import import_git_objects
            os.fsync(fd)
            f.close()
            if os.path.getsize(path) == 0:
                return
            pd = PackData(path)
            pd.create_index_v2(path[:-5]+".idx", self.object_store.get_raw)

            p = Pack(path[:-5])
            self.repository.lock_write()
            try:
                self.repository.start_write_group()
                try:
                    import_git_objects(self.repository, self.mapping, 
                        p.iterobjects(get_raw=self.get_raw),
                        self.object_store)
                except:
                    self.repository.abort_write_group()
                    raise
                else:
                    self.repository.commit_write_group()
            finally:
                self.repository.unlock()
        return f, commit

    # The pack isn't kept around anyway, so no point 
    # in treating full packs different from thin packs
    add_pack = add_thin_pack
