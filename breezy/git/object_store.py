# Copyright (C) 2009-2018 Jelmer Vernooij <jelmer@jelmer.uk>
# Copyright (C) 2012 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Map from Git sha's to Bazaar objects."""

import posixpath
import stat
from collections.abc import Iterable, Iterator
from typing import AbstractSet

from dulwich.object_store import BaseObjectStore
from dulwich.objects import ZERO_SHA, Blob, Commit, ObjectID, Tree, sha_to_hex
from dulwich.pack import Pack, PackData, UnpackedObject, pack_objects_to_data

from .. import errors, lru_cache, osutils, trace, ui
from ..bzr.testament import StrictTestament3
from ..lock import LogicalLockResult
from ..revision import NULL_REVISION
from ..tree import InterTree
from .cache import from_repository as cache_from_repository
from .mapping import (
    default_mapping,
    encode_git_path,
    entry_mode,
    extract_unusual_modes,
    mapping_registry,
    symlink_to_blob,
)
from .unpeel_map import UnpeelMap

BANNED_FILENAMES = [".git"]


def get_object_store(repo, mapping=None):
    git = getattr(repo, "_git", None)
    if git is not None:
        git.object_store.unlock = lambda: None
        git.object_store.lock_read = lambda: LogicalLockResult(lambda: None)
        git.object_store.lock_write = lambda: LogicalLockResult(lambda: None)
        return git.object_store
    return BazaarObjectStore(repo, mapping)


MAX_TREE_CACHE_SIZE = 50 * 1024 * 1024


class LRUTreeCache:
    def __init__(self, repository):
        def approx_tree_size(tree):
            # Very rough estimate, 250 per inventory entry
            return len(tree.root_inventory) * 250

        self.repository = repository
        self._cache = lru_cache.LRUSizeCache(
            max_size=MAX_TREE_CACHE_SIZE,
            after_cleanup_size=None,
            compute_size=approx_tree_size,
        )

    def revision_tree(self, revid):
        try:
            tree = self._cache[revid]
        except KeyError:
            tree = self.repository.revision_tree(revid)
            self.add(tree)
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
                if tree.get_revision_id() != revid:
                    raise AssertionError(
                        "revision id did not match: {} != {}".format(
                            tree.get_revision_id(), revid
                        )
                    )
                trees[revid] = tree
        for tree in self.repository.revision_trees(todo):
            trees[tree.get_revision_id()] = tree
            self.add(tree)
        return (trees[r] for r in revids)

    def revision_trees(self, revids):
        return list(self.iter_revision_trees(revids))

    def add(self, tree):
        self._cache[tree.get_revision_id()] = tree


def _find_missing_bzr_revids(graph, want, have, shallow=None):
    """Find the revisions that have to be pushed.

    :param get_parent_map: Function that returns the parents for a sequence
        of revisions.
    :param want: Revisions the target wants
    :param have: Revisions the target already has
    :return: Set of revisions to fetch
    """
    handled = set(have)
    if shallow:
        # Shallows themselves still need to be fetched, but let's exclude their
        # parents.
        for ps in graph.get_parent_map(shallow).values():
            handled.update(ps)
    handled.add(NULL_REVISION)
    todo = set()
    for rev in want:
        extra_todo = graph.find_unique_ancestors(rev, handled)
        todo.update(extra_todo)
        handled.update(extra_todo)
    return todo


def _check_expected_sha(expected_sha, object):
    """Check whether an object matches an expected SHA.

    :param expected_sha: None or expected SHA as either binary or as hex digest
    :param object: Object to verify
    """
    if expected_sha is None:
        return
    if len(expected_sha) == 40:
        if expected_sha != object.sha().hexdigest().encode("ascii"):
            raise AssertionError(
                "Invalid sha for {!r}: {}".format(object, expected_sha)
            )
    elif len(expected_sha) == 20:
        if expected_sha != object.sha().digest():
            raise AssertionError(
                "Invalid sha for {!r}: {}".format(object, sha_to_hex(expected_sha))
            )
    else:
        raise AssertionError(f"Unknown length {len(expected_sha)} for {expected_sha!r}")


def directory_to_tree(
    path, children, lookup_ie_sha1, unusual_modes, empty_file_name, allow_empty=False
):
    """Create a Git Tree object from a Bazaar directory.

    :param path: directory path
    :param children: Children inventory entries
    :param lookup_ie_sha1: Lookup the Git SHA1 for a inventory entry
    :param unusual_modes: Dictionary with unusual file modes by file ids
    :param empty_file_name: Name to use for dummy files in empty directories,
        None to ignore empty directories.
    """
    tree = Tree()
    for value in children:
        if value.name in BANNED_FILENAMES:
            continue
        child_path = osutils.pathjoin(path, value.name)
        try:
            mode = unusual_modes[child_path]
        except KeyError:
            mode = entry_mode(value)
        hexsha = lookup_ie_sha1(child_path, value)
        if hexsha is not None:
            tree.add(encode_git_path(value.name), mode, hexsha)
    if not allow_empty and len(tree) == 0:
        # Only the root can be an empty tree
        if empty_file_name is not None:
            tree.add(empty_file_name, stat.S_IFREG | 0o644, Blob().id)
        else:
            return None
    return tree


def _tree_to_objects(
    tree, parent_trees, idmap, unusual_modes, dummy_file_name=None, add_cache_entry=None
):
    """Iterate over the objects that were introduced in a revision.

    :param idmap: id map
    :param parent_trees: Parent revision trees
    :param unusual_modes: Unusual file modes dictionary
    :param dummy_file_name: File name to use for dummy files
        in empty directories. None to skip empty directories
    :return: Yields (path, object, ie) entries
    """
    dirty_dirs = set()
    new_blobs = []
    shamap = {}
    try:
        base_tree = parent_trees[0]
        other_parent_trees = parent_trees[1:]
    except IndexError:
        base_tree = tree._repository.revision_tree(NULL_REVISION)
        other_parent_trees = []

    def find_unchanged_parent_ie(path, kind, other, parent_trees):
        for ptree in parent_trees:
            intertree = InterTree.get(ptree, tree)
            ppath = intertree.find_source_path(path)
            if ppath is not None:
                pkind = ptree.kind(ppath)
                if kind == "file":
                    if pkind == "file" and ptree.get_file_sha1(ppath) == other:
                        return (ptree.path2id(ppath), ptree.get_file_revision(ppath))
                if kind == "symlink":
                    if pkind == "symlink" and ptree.get_symlink_target(ppath) == other:
                        return (ptree.path2id(ppath), ptree.get_file_revision(ppath))
        raise KeyError

    # Find all the changed blobs
    for change in tree.iter_changes(base_tree):
        if change.name[1] in BANNED_FILENAMES:
            continue
        if change.kind[1] == "file":
            sha1 = tree.get_file_sha1(change.path[1])
            blob_id = None
            try:
                (pfile_id, prevision) = find_unchanged_parent_ie(
                    change.path[1], change.kind[1], sha1, other_parent_trees
                )
            except KeyError:
                pass
            else:
                # It existed in one of the parents, with the same contents.
                # So no need to yield any new git objects.
                try:
                    blob_id = idmap.lookup_blob_id(pfile_id, prevision)
                except KeyError:
                    if not change.changed_content:
                        # no-change merge ?
                        blob = Blob()
                        blob.data = tree.get_file_text(change.path[1])
                        blob_id = blob.id
            if blob_id is None:
                new_blobs.append((change.path[1], change.file_id))
            else:
                # TODO(jelmer): This code path does not have any test coverage.
                shamap[change.path[1]] = blob_id
                if add_cache_entry is not None:
                    add_cache_entry(
                        ("blob", blob_id),
                        (change.file_id, tree.get_file_revision(change.path[1])),
                        change.path[1],
                    )
        elif change.kind[1] == "symlink":
            target = tree.get_symlink_target(change.path[1])
            blob = symlink_to_blob(target)
            shamap[change.path[1]] = blob.id
            if add_cache_entry is not None:
                add_cache_entry(
                    blob,
                    (change.file_id, tree.get_file_revision(change.path[1])),
                    change.path[1],
                )
            try:
                find_unchanged_parent_ie(
                    change.path[1], change.kind[1], target, other_parent_trees
                )
            except KeyError:
                if change.changed_content:
                    yield (
                        change.path[1],
                        blob,
                        (change.file_id, tree.get_file_revision(change.path[1])),
                    )
        elif change.kind[1] is None:
            shamap[change.path[1]] = None
        elif change.kind[1] != "directory":
            raise AssertionError(change.kind[1])
        for p in change.path:
            if p is None:
                continue
            dirty_dirs.add(osutils.dirname(p))

    # Fetch contents of the blobs that were changed
    for (path, file_id), chunks in tree.iter_files_bytes(
        [(path, (path, file_id)) for (path, file_id) in new_blobs]
    ):
        obj = Blob()
        obj.chunked = list(chunks)
        if add_cache_entry is not None:
            add_cache_entry(obj, (file_id, tree.get_file_revision(path)), path)
        yield path, obj, (file_id, tree.get_file_revision(path))
        shamap[path] = obj.id

    for path in unusual_modes:
        dirty_dirs.add(posixpath.dirname(path))

    for dir in list(dirty_dirs):
        for parent in osutils.parent_directories(dir):
            if parent in dirty_dirs:
                break
            dirty_dirs.add(parent)

    if dirty_dirs:
        dirty_dirs.add("")

    def ie_to_hexsha(path, ie):
        try:
            return shamap[path]
        except KeyError:
            pass
        # FIXME: Should be the same as in parent
        if ie.kind == "file":
            try:
                return idmap.lookup_blob_id(ie.file_id, ie.revision)
            except KeyError:
                # no-change merge ?
                blob = Blob()
                blob.data = tree.get_file_text(path)
                if add_cache_entry is not None:
                    add_cache_entry(blob, (ie.file_id, ie.revision), path)
                return blob.id
        elif ie.kind == "symlink":
            try:
                return idmap.lookup_blob_id(ie.file_id, ie.revision)
            except KeyError:
                # no-change merge ?
                target = tree.get_symlink_target(path)
                blob = symlink_to_blob(target)
                if add_cache_entry is not None:
                    add_cache_entry(blob, (ie.file_id, ie.revision), path)
                return blob.id
        elif ie.kind == "directory":
            # Not all cache backends store the tree information,
            # calculate again from scratch
            ret = directory_to_tree(
                path,
                ie.children.values(),
                ie_to_hexsha,
                unusual_modes,
                dummy_file_name,
                ie.parent_id is None,
            )
            if ret is None:
                return ret
            return ret.id
        else:
            raise AssertionError

    for path in sorted(dirty_dirs, reverse=True):
        if not tree.has_filename(path):
            continue

        if tree.kind(path) != "directory":
            continue

        obj = directory_to_tree(
            path,
            tree.iter_child_entries(path),
            ie_to_hexsha,
            unusual_modes,
            dummy_file_name,
            path == "",
        )

        if obj is not None:
            file_id = tree.path2id(path)
            if add_cache_entry is not None:
                add_cache_entry(obj, (file_id, tree.get_revision_id()), path)
            yield path, obj, (file_id, tree.get_revision_id())
            shamap[path] = obj.id


class BazaarObjectStore(BaseObjectStore):
    """A Git-style object store backed onto a Bazaar repository."""

    def __init__(self, repository, mapping=None):
        """Initialize BazaarObjectStore.

        Args:
            repository: The Bazaar repository to wrap.
            mapping: Optional mapping for Git/Bazaar conversion.
        """
        from dulwich.object_format import DEFAULT_OBJECT_FORMAT

        self.repository = repository
        self._map_updated = False
        self._locked = None
        if mapping is None:
            self.mapping = default_mapping
        else:
            self.mapping = mapping
        self._cache = cache_from_repository(repository)
        self._content_cache_types = ("tree",)
        self.start_write_group = self._cache.idmap.start_write_group
        self.abort_write_group = self._cache.idmap.abort_write_group
        self.commit_write_group = self._cache.idmap.commit_write_group
        self.tree_cache = LRUTreeCache(self.repository)
        self.unpeel_map = UnpeelMap.from_repository(self.repository)
        self.object_format = DEFAULT_OBJECT_FORMAT

    def _missing_revisions(self, revisions):
        return self._cache.idmap.missing_revisions(revisions)

    def _update_sha_map(self, stop_revision=None):
        if not self.is_locked():
            raise errors.LockNotHeld(self)
        if self._map_updated:
            return
        if stop_revision is not None and not self._missing_revisions([stop_revision]):
            return
        graph = self.repository.get_graph()
        if stop_revision is None:
            all_revids = self.repository.all_revision_ids()
            missing_revids = self._missing_revisions(all_revids)
        else:
            heads = {stop_revision}
            missing_revids = self._missing_revisions(heads)
            while heads:
                parents = graph.get_parent_map(heads)
                todo = set()
                for p in parents.values():
                    todo.update([x for x in p if x not in missing_revids])
                heads = self._missing_revisions(todo)
                missing_revids.update(heads)
        if NULL_REVISION in missing_revids:
            missing_revids.remove(NULL_REVISION)
        missing_revids = self.repository.has_revisions(missing_revids)
        if not missing_revids:
            if stop_revision is None:
                self._map_updated = True
            return
        self.start_write_group()
        try:
            with ui.ui_factory.nested_progress_bar() as pb:
                for i, revid in enumerate(graph.iter_topo_order(missing_revids)):
                    trace.mutter("processing %r", revid)
                    pb.update("updating git map", i, len(missing_revids))
                    self._update_sha_map_revision(revid)
            if stop_revision is None:
                self._map_updated = True
        except BaseException:
            self.abort_write_group()
            raise
        else:
            self.commit_write_group()

    def __iter__(self):
        self._update_sha_map()
        return iter(self._cache.idmap.sha1s())

    def _reconstruct_commit(self, rev, tree_sha, lossy, verifiers):
        """Reconstruct a Commit object.

        :param rev: Revision object
        :param tree_sha: SHA1 of the root tree object
        :param lossy: Whether or not to roundtrip bzr metadata
        :param verifiers: Verifiers for the commits
        :return: Commit object
        """

        def parent_lookup(revid):
            try:
                return self._lookup_revision_sha1(revid)
            except errors.NoSuchRevision:
                return None

        return self.mapping.export_commit(
            rev, tree_sha, parent_lookup, lossy, verifiers
        )

    def _revision_to_objects(self, rev, tree, lossy, add_cache_entry=None):
        """Convert a revision to a set of git objects.

        :param rev: Bazaar revision object
        :param tree: Bazaar revision tree
        :param lossy: Whether to not roundtrip all Bazaar revision data
        """
        unusual_modes = extract_unusual_modes(rev)
        present_parents = self.repository.has_revisions(rev.parent_ids)
        parent_trees = self.tree_cache.revision_trees(
            [p for p in rev.parent_ids if p in present_parents]
        )
        root_tree = None
        for path, obj, bzr_key_data in _tree_to_objects(
            tree,
            parent_trees,
            self._cache.idmap,
            unusual_modes,
            self.mapping.BZR_DUMMY_FILE,
            add_cache_entry,
        ):
            if path == "":
                root_tree = obj
                root_key_data = bzr_key_data
                # Don't yield just yet
            else:
                yield path, obj
        if root_tree is None:
            # Pointless commit - get the tree sha elsewhere
            if not rev.parent_ids:
                root_tree = Tree()
            else:
                base_sha1 = self._lookup_revision_sha1(rev.parent_ids[0])
                root_tree = self[self[base_sha1].tree]
            root_key_data = (tree.path2id(""), tree.get_revision_id())
        if add_cache_entry is not None:
            add_cache_entry(root_tree, root_key_data, "")
        yield "", root_tree
        if not lossy:
            testament3 = StrictTestament3(rev, tree)
            verifiers = {"testament3-sha1": testament3.as_sha1()}
        else:
            verifiers = {}
        commit_obj = self._reconstruct_commit(
            rev, root_tree.id, lossy=lossy, verifiers=verifiers
        )
        try:
            foreign_revid, _mapping = mapping_registry.parse_revision_id(rev.revision_id)
        except errors.InvalidRevisionId:
            pass
        else:
            _check_expected_sha(foreign_revid, commit_obj)
        if add_cache_entry is not None:
            add_cache_entry(commit_obj, verifiers, None)

        yield None, commit_obj

    def _get_updater(self, rev):
        return self._cache.get_updater(rev)

    def _update_sha_map_revision(self, revid):
        rev = self.repository.get_revision(revid)
        tree = self.tree_cache.revision_tree(rev.revision_id)
        updater = self._get_updater(rev)
        # FIXME JRV 2011-12-15: Shouldn't we try both values for lossy ?
        for _path, obj in self._revision_to_objects(
            rev,
            tree,
            lossy=(not self.mapping.roundtripping),
            add_cache_entry=updater.add_object,
        ):
            if isinstance(obj, Commit):
                commit_obj = obj
        commit_obj = updater.finish()
        return commit_obj.id

    def iter_unpacked_subset(
        self,
        shas,
        include_comp=False,
        allow_missing: bool = False,
        convert_ofs_delta: bool = True,
    ) -> Iterator[UnpackedObject]:
        # We don't store unpacked objects, so...
        if not allow_missing and shas:
            raise KeyError(shas.pop())
        yield from []

    def _reconstruct_blobs(self, keys):
        """Return a Git Blob object from a fileid and revision stored in bzr.

        :param fileid: File id of the text
        :param revision: Revision of the text
        """
        stream = self.repository.iter_files_bytes((key[0], key[1], key) for key in keys)
        for (file_id, revision, expected_sha), chunks in stream:
            blob = Blob()
            blob.chunked = list(chunks)
            if blob.id != expected_sha and blob.data == b"":
                # Perhaps it's a symlink ?
                tree = self.tree_cache.revision_tree(revision)
                path = tree.id2path(file_id)
                if tree.kind(path) == "symlink":
                    blob = symlink_to_blob(tree.get_symlink_target(path))
            _check_expected_sha(expected_sha, blob)
            yield blob

    def _reconstruct_tree(
        self, fileid, revid, bzr_tree, unusual_modes, expected_sha=None
    ):
        """Return a Git Tree object from a file id and a revision stored in bzr.

        :param fileid: fileid in the tree.
        :param revision: Revision of the tree.
        """

        def get_ie_sha1(path, entry):
            if entry.kind == "directory":
                try:
                    return self._cache.idmap.lookup_tree_id(entry.file_id, revid)
                except (NotImplementedError, KeyError):
                    obj = self._reconstruct_tree(
                        entry.file_id, revid, bzr_tree, unusual_modes
                    )
                    if obj is None:
                        return None
                    else:
                        return obj.id
            elif entry.kind in ("file", "symlink"):
                try:
                    return self._cache.idmap.lookup_blob_id(
                        entry.file_id, entry.revision
                    )
                except KeyError:
                    # no-change merge?
                    return next(
                        self._reconstruct_blobs([(entry.file_id, entry.revision, None)])
                    ).id
            elif entry.kind == "tree-reference":
                # FIXME: Make sure the file id is the root id
                return self._lookup_revision_sha1(entry.reference_revision)
            else:
                raise AssertionError("unknown entry kind '{}'".format(entry.kind))

        path = bzr_tree.id2path(fileid)
        tree = directory_to_tree(
            path,
            bzr_tree.iter_child_entries(path),
            get_ie_sha1,
            unusual_modes,
            self.mapping.BZR_DUMMY_FILE,
            bzr_tree.path2id("") == fileid,
        )
        if tree is not None:
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
                self._update_sha_map(revid)
                return self._cache.idmap.lookup_commit(revid)

    def get_raw(self, sha):
        """Get the raw representation of a Git object by SHA1.

        :param sha: SHA1 of the git object
        """
        if len(sha) == 20:
            sha = sha_to_hex(sha)
        obj = self[sha]
        return (obj.type_num, obj.as_raw_string())

    def __contains__(self, sha):
        # See if sha is in map
        try:
            for type, type_data in self.lookup_git_sha(sha):
                if type == "commit":
                    if self.repository.has_revision(type_data[0]):
                        return True
                elif type == "blob":
                    if type_data in self.repository.texts:
                        return True
                elif type == "tree":
                    if self.repository.has_revision(type_data[1]):
                        return True
                else:
                    raise AssertionError("Unknown object type '{}'".format(type))
            else:
                return False
        except KeyError:
            return False

    def lock_read(self):
        self._locked = "r"
        self._map_updated = False
        self.repository.lock_read()
        return LogicalLockResult(self.unlock)

    def lock_write(self):
        self._locked = "r"
        self._map_updated = False
        self.repository.lock_write()
        return LogicalLockResult(self.unlock)

    def is_locked(self):
        return self._locked is not None

    def unlock(self):
        self._locked = None
        self._map_updated = False
        self.repository.unlock()

    def lookup_git_shas(self, shas: Iterable[ObjectID]) -> dict[ObjectID, list]:
        ret: dict[ObjectID, list] = {}
        for sha in shas:
            if sha == ZERO_SHA:
                ret[sha] = [("commit", (NULL_REVISION, None, {}))]
                continue
            try:
                ret[sha] = list(self._cache.idmap.lookup_git_sha(sha))
            except KeyError:
                # if not, see if there are any unconverted revisions and
                # add them to the map, search for sha in map again
                self._update_sha_map()
                try:
                    ret[sha] = list(self._cache.idmap.lookup_git_sha(sha))
                except KeyError:
                    pass
        return ret

    def lookup_git_sha(self, sha):
        return self.lookup_git_shas([sha])[sha]

    def __getitem__(self, sha):
        with self.repository.lock_read():
            for kind, type_data in self.lookup_git_sha(sha):
                # convert object to git object
                if kind == "commit":
                    (revid, tree_sha, verifiers) = type_data
                    try:
                        rev = self.repository.get_revision(revid)
                    except errors.NoSuchRevision:
                        if revid == NULL_REVISION:
                            raise AssertionError(
                                "should not try to look up NULL_REVISION"
                            )
                        trace.mutter(
                            "entry for %s %s in shamap: %r, but not "
                            "found in repository",
                            kind,
                            sha,
                            type_data,
                        )
                        raise KeyError(sha)
                    # FIXME: the type data should say whether conversion was
                    # lossless
                    commit = self._reconstruct_commit(
                        rev,
                        tree_sha,
                        lossy=(not self.mapping.roundtripping),
                        verifiers=verifiers,
                    )
                    _check_expected_sha(sha, commit)
                    return commit
                elif kind == "blob":
                    (fileid, revision) = type_data
                    blobs = self._reconstruct_blobs([(fileid, revision, sha)])
                    return next(blobs)
                elif kind == "tree":
                    (fileid, revid) = type_data
                    try:
                        tree = self.tree_cache.revision_tree(revid)
                        rev = self.repository.get_revision(revid)
                    except errors.NoSuchRevision:
                        trace.mutter(
                            "entry for %s %s in shamap: %r, but not found in "
                            "repository",
                            kind,
                            sha,
                            type_data,
                        )
                        raise KeyError(sha)
                    unusual_modes = extract_unusual_modes(rev)
                    try:
                        return self._reconstruct_tree(
                            fileid, revid, tree, unusual_modes, expected_sha=sha
                        )
                    except errors.NoSuchRevision:
                        raise KeyError(sha)
                else:
                    raise AssertionError("Unknown object type '{}'".format(kind))
            else:
                raise KeyError(sha)

    def generate_lossy_pack_data(
        self, have, want, shallow=None, progress=None, get_tagged=None, ofs_delta=False
    ):
        object_ids = list(
            self.find_missing_objects(
                have,
                want,
                progress=progress,
                shallow=shallow,
                get_tagged=get_tagged,
                lossy=True,
            )
        )
        return pack_objects_to_data(
            [(self[oid], path) for (oid, (type_num, path)) in object_ids]
        )

    def find_missing_objects(
        self,
        haves: Iterable[ObjectID],
        wants: Iterable[ObjectID],
        shallow: AbstractSet[ObjectID] | None = None,
        progress=None,
        get_tagged=None,
        get_parents=None,
        ofs_delta: bool = False,
        lossy: bool = False,
    ) -> Iterator[tuple[ObjectID, tuple[int, bytes | None] | None]]:
        """Iterate over the contents of a pack file.

        :param haves: List of SHA1s of objects that should not be sent
        :param wants: List of SHA1s of objects that should be sent
        """
        processed = set()
        ret: dict[ObjectID, list] = self.lookup_git_shas(list(haves) + list(wants))
        for commit_sha in haves:
            commit_sha = self.unpeel_map.peel_tag(commit_sha, commit_sha)
            try:
                for type, type_data in ret[commit_sha]:
                    if type != "commit":
                        raise AssertionError("Type was {}, not commit".format(type))
                    processed.add(type_data[0])
            except KeyError:
                trace.mutter("unable to find remote ref %s", commit_sha)
        pending = set()
        for commit_sha in wants:
            if commit_sha in haves:
                continue
            try:
                for type, type_data in ret[commit_sha]:
                    if type != "commit":
                        raise AssertionError("Type was {}, not commit".format(type))
                    pending.add(type_data[0])
            except KeyError:
                pass
        shallows = set()
        for commit_sha in shallow or set():
            try:
                for type, type_data in ret[commit_sha]:
                    if type != "commit":
                        raise AssertionError("Type was {}, not commit".format(type))
                    shallows.add(type_data[0])
            except KeyError:
                pass

        seen = set()
        with self.repository.lock_read():
            graph = self.repository.get_graph()
            todo = _find_missing_bzr_revids(graph, pending, processed, shallow)
            with ui.ui_factory.nested_progress_bar() as pb:
                for i, revid in enumerate(graph.iter_topo_order(todo)):
                    pb.update("generating git objects", i, len(todo))
                    try:
                        rev = self.repository.get_revision(revid)
                    except errors.NoSuchRevision:
                        continue
                    tree = self.tree_cache.revision_tree(revid)
                    for path, obj in self._revision_to_objects(rev, tree, lossy=lossy):
                        if obj.id not in seen:
                            # Convert path to bytes for PackHint compatibility
                            path_bytes = (
                                encode_git_path(path) if path is not None else None
                            )
                            yield (obj.id, (obj.type_num, path_bytes))
                            seen.add(obj.id)

    def add_thin_pack(self):
        import os
        import tempfile

        fd, path = tempfile.mkstemp(suffix=".pack")
        f = os.fdopen(fd, "wb")

        def commit():
            from .fetch import import_git_objects

            os.fsync(fd)
            f.close()
            if os.path.getsize(path) == 0:
                return
            pd = PackData(path)
            pd.create_index_v2(path[:-5] + ".idx", self.object_store.get_raw)

            p = Pack(path[:-5])
            with self.repository.lock_write():
                self.repository.start_write_group()
                try:
                    import_git_objects(
                        self.repository,
                        self.mapping,
                        p.iterobjects(get_raw=self.get_raw),
                        self.object_store,
                    )
                except BaseException:
                    self.repository.abort_write_group()
                    raise
                else:
                    self.repository.commit_write_group()

        return f, commit

    # The pack isn't kept around anyway, so no point
    # in treating full packs different from thin packs
    add_pack = add_thin_pack
