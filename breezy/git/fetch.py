# Copyright (C) 2008-2018 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""Fetching from git into bzr."""

import posixpath
import stat

from dulwich.object_store import tree_lookup_path
from dulwich.objects import S_IFGITLINK, S_ISGITLINK, ZERO_SHA, Commit, Tag, Tree

from vcsgraph.tsort import topo_sort

from .. import debug, osutils, trace
from ..bzr.inventory import (
    InventoryDirectory,
    InventoryFile,
    InventoryLink,
    TreeReference,
)
from ..bzr.inventory_delta import InventoryDelta
from ..bzr.inventorytree import InventoryRevisionTree
from ..bzr.testament import StrictTestament3
from ..bzr.versionedfile import ChunkedContentFactory
from ..errors import BzrError
from ..revision import NULL_REVISION
from ..transport import NoSuchFile
from ..tree import InterTree
from .mapping import (
    DEFAULT_FILE_MODE,
    decode_git_path,
    mode_is_executable,
    mode_kind,
    warn_unusual_mode,
)
from .object_store import LRUTreeCache, _tree_to_objects


def import_git_blob(
    texts,
    mapping,
    path,
    name,
    hexshas,
    base_bzr_tree,
    parent_id,
    revision_id,
    parent_bzr_trees,
    lookup_object,
    modes,
    store_updater,
    lookup_file_id,
):
    """Import a git blob object into a bzr repository.

    :param texts: VersionedFiles to add to
    :param path: Path in the tree
    :param blob: A git blob
    :return: Inventory delta for this file
    """
    if not isinstance(path, bytes):
        raise TypeError(path)
    decoded_path = decode_git_path(path)
    (base_mode, mode) = modes
    (base_hexsha, hexsha) = hexshas
    if mapping.is_special_file(path):
        return []
    if base_hexsha == hexsha and base_mode == mode:
        # If nothing has changed since the base revision, we're done
        return []
    file_id = lookup_file_id(decoded_path)
    decoded_name = decode_git_path(name)
    kind = "symlink" if stat.S_ISLNK(mode) else "file"
    kwargs = {}
    if base_hexsha == hexsha and mode_kind(base_mode) == mode_kind(mode):
        base_exec = base_bzr_tree.is_executable(decoded_path)
        if kind == "symlink":
            kwargs["symlink_target"] = base_bzr_tree.get_symlink_target(decoded_path)
        else:
            kwargs["text_size"] = base_bzr_tree.get_file_size(decoded_path)
            kwargs["text_sha1"] = base_bzr_tree.get_file_sha1(decoded_path)
            kwargs["executable"] = mode_is_executable(mode)
        if kind == "symlink" or kwargs["executable"] == base_exec:
            kwargs["revision"] = base_bzr_tree.get_file_revision(decoded_path)
        else:
            blob = lookup_object(hexsha)
    else:
        blob = lookup_object(hexsha)
        if kind == "symlink":
            kwargs["revision"] = None
            kwargs["symlink_target"] = decode_git_path(blob.data)
        else:
            kwargs["executable"] = mode_is_executable(mode)
            kwargs["text_size"] = sum(map(len, blob.chunked))
            kwargs["text_sha1"] = osutils.sha_strings(blob.chunked)
    # Check what revision we should store
    parent_keys = []
    for ptree in parent_bzr_trees:
        intertree = InterTree.get(ptree, base_bzr_tree)
        try:
            ppath = intertree.find_source_paths(decoded_path, recurse="none")
        except NoSuchFile:
            continue
        if ppath is None:
            continue
        pkind = ptree.kind(ppath)
        if pkind == kind and (
            (
                pkind == "symlink"
                and ptree.get_symlink_target(ppath) == kwargs.get("symlink_target")
            )
            or (
                pkind == "file"
                and ptree.get_file_sha1(ppath) == kwargs.get("text_sha1")
                and ptree.is_executable(ppath) == kwargs.get("executable")
            )
        ):
            # found a revision in one of the parents to use
            kwargs["revision"] = ptree.get_file_revision(ppath)
            break
        parent_key = (file_id, ptree.get_file_revision(ppath))
        if parent_key not in parent_keys:
            parent_keys.append(parent_key)
    if kwargs.get("revision") is None:
        # Need to store a new revision
        kwargs["revision"] = revision_id
        if kwargs["revision"] is None:
            raise ValueError("no file revision set")
        chunks = [] if kind == "symlink" else blob.chunked
        texts.insert_record_stream(
            [
                ChunkedContentFactory(
                    (file_id, kwargs["revision"]),
                    tuple(parent_keys),
                    kwargs.get("text_sha1"),
                    chunks,
                )
            ]
        )
    invdelta = []
    if base_hexsha is not None:
        old_path = decoded_path  # Renames are not supported yet
        if stat.S_ISDIR(base_mode):
            invdelta.extend(
                remove_disappeared_children(
                    base_bzr_tree,
                    old_path,
                    lookup_object(base_hexsha),
                    [],
                    lookup_object,
                )
            )
    else:
        old_path = None

    if kind == "symlink":
        ie = InventoryLink(file_id, decoded_name, parent_id, **kwargs)
    else:
        ie = InventoryFile(file_id, decoded_name, parent_id, **kwargs)
    invdelta.append((old_path, decoded_path, file_id, ie))
    if base_hexsha != hexsha:
        store_updater.add_object(blob, (ie.file_id, ie.revision), path)
    return invdelta


class SubmodulesRequireSubtrees(BzrError):
    """Error raised when repository contains submodules but format doesn't support them."""

    _fmt = (
        "The repository you are fetching from contains submodules, "
        "which require a Bazaar format that supports tree references."
    )
    internal = False


def import_git_submodule(
    texts,
    mapping,
    path,
    name,
    hexshas,
    base_bzr_tree,
    parent_id,
    revision_id,
    parent_bzr_trees,
    lookup_object,
    modes,
    store_updater,
    lookup_file_id,
):
    """Import a git submodule."""
    (base_hexsha, hexsha) = hexshas
    (base_mode, mode) = modes
    if base_hexsha == hexsha and base_mode == mode:
        return [], {}
    path = decode_git_path(path)
    file_id = lookup_file_id(path)
    invdelta = []
    ie = TreeReference(
        file_id,
        decode_git_path(name),
        parent_id,
        revision_id,
        reference_revision=mapping.revision_id_foreign_to_bzr(hexsha),
    )
    if base_hexsha is not None:
        old_path = path  # Renames are not supported yet
        if stat.S_ISDIR(base_mode):
            invdelta.extend(
                remove_disappeared_children(
                    base_bzr_tree,
                    old_path,
                    lookup_object(base_hexsha),
                    [],
                    lookup_object,
                )
            )
    else:
        old_path = None
    texts.insert_record_stream(
        [ChunkedContentFactory((file_id, ie.revision), (), None, [])]
    )
    invdelta.append((old_path, path, file_id, ie))
    return invdelta, {}


def remove_disappeared_children(
    base_bzr_tree, path, base_tree, existing_children, lookup_object
):
    """Generate an inventory delta for removed children.

    :param base_bzr_tree: Base bzr tree against which to generate the
        inventory delta.
    :param path: Path to process (unicode)
    :param base_tree: Git Tree base object
    :param existing_children: Children that still exist
    :param lookup_object: Lookup a git object by its SHA1
    :return: Inventory delta, as list
    """
    if not isinstance(path, str):
        raise TypeError(path)
    ret = []
    for name, mode, hexsha in base_tree.iteritems():
        if name in existing_children:
            continue
        c_path = posixpath.join(path, decode_git_path(name))
        file_id = base_bzr_tree.path2id(c_path)
        if file_id is None:
            raise TypeError(file_id)
        ret.append((c_path, None, file_id, None))
        if stat.S_ISDIR(mode):
            ret.extend(
                remove_disappeared_children(
                    base_bzr_tree, c_path, lookup_object(hexsha), [], lookup_object
                )
            )
    return ret


def import_git_tree(
    texts,
    mapping,
    path,
    name,
    hexshas,
    base_bzr_tree,
    parent_id,
    revision_id,
    parent_bzr_trees,
    lookup_object,
    modes,
    store_updater,
    lookup_file_id,
    allow_submodules=False,
):
    """Import a git tree object into a bzr repository.

    :param texts: VersionedFiles object to add to
    :param path: Path in the tree (str)
    :param name: Name of the tree (str)
    :param tree: A git tree object
    :param base_bzr_tree: Base inventory against which to return inventory
        delta
    :return: Inventory delta for this subtree
    """
    (base_hexsha, hexsha) = hexshas
    (base_mode, mode) = modes
    if not isinstance(path, bytes):
        raise TypeError(path)
    if not isinstance(name, bytes):
        raise TypeError(name)
    if base_hexsha == hexsha and base_mode == mode:
        # If nothing has changed since the base revision, we're done
        return [], {}
    invdelta = []
    file_id = lookup_file_id(osutils.safe_unicode(path))
    ie = InventoryDirectory(
        file_id, decode_git_path(name), parent_id, revision=revision_id
    )
    tree = lookup_object(hexsha)
    if base_hexsha is None:
        base_tree = None
        old_path = None  # Newly appeared here
    else:
        base_tree = lookup_object(base_hexsha)
        old_path = decode_git_path(path)  # Renames aren't supported yet
    new_path = decode_git_path(path)
    if base_tree is None or type(base_tree) is not Tree:
        invdelta.append((old_path, new_path, ie.file_id, ie))
        texts.insert_record_stream(
            [ChunkedContentFactory((ie.file_id, ie.revision), (), None, [])]
        )
    # Remember for next time
    existing_children = set()
    child_modes = {}
    for name, child_mode, child_hexsha in tree.iteritems():
        existing_children.add(name)
        child_path = posixpath.join(path, name)
        if type(base_tree) is Tree:
            try:
                child_base_mode, child_base_hexsha = base_tree[name]
            except KeyError:
                child_base_hexsha = None
                child_base_mode = 0
        else:
            child_base_hexsha = None
            child_base_mode = 0
        if stat.S_ISDIR(child_mode):
            subinvdelta, grandchildmodes = import_git_tree(
                texts,
                mapping,
                child_path,
                name,
                (child_base_hexsha, child_hexsha),
                base_bzr_tree,
                file_id,
                revision_id,
                parent_bzr_trees,
                lookup_object,
                (child_base_mode, child_mode),
                store_updater,
                lookup_file_id,
                allow_submodules=allow_submodules,
            )
        elif S_ISGITLINK(child_mode):  # submodule
            if not allow_submodules:
                raise SubmodulesRequireSubtrees()
            subinvdelta, grandchildmodes = import_git_submodule(
                texts,
                mapping,
                child_path,
                name,
                (child_base_hexsha, child_hexsha),
                base_bzr_tree,
                file_id,
                revision_id,
                parent_bzr_trees,
                lookup_object,
                (child_base_mode, child_mode),
                store_updater,
                lookup_file_id,
            )
        else:
            if not mapping.is_special_file(name):
                subinvdelta = import_git_blob(
                    texts,
                    mapping,
                    child_path,
                    name,
                    (child_base_hexsha, child_hexsha),
                    base_bzr_tree,
                    file_id,
                    revision_id,
                    parent_bzr_trees,
                    lookup_object,
                    (child_base_mode, child_mode),
                    store_updater,
                    lookup_file_id,
                )
            else:
                subinvdelta = []
            grandchildmodes = {}
        child_modes.update(grandchildmodes)
        invdelta.extend(subinvdelta)
        if child_mode not in (
            stat.S_IFDIR,
            DEFAULT_FILE_MODE,
            stat.S_IFLNK,
            DEFAULT_FILE_MODE | 0o111,
            S_IFGITLINK,
        ):
            child_modes[child_path] = child_mode
    # Remove any children that have disappeared
    if base_tree is not None and type(base_tree) is Tree:
        invdelta.extend(
            remove_disappeared_children(
                base_bzr_tree, old_path, base_tree, existing_children, lookup_object
            )
        )
    store_updater.add_object(tree, (file_id, revision_id), path)
    return invdelta, child_modes


def verify_commit_reconstruction(
    target_git_object_retriever,
    lookup_object,
    o,
    rev,
    ret_tree,
    parent_trees,
    mapping,
    unusual_modes,
    verifiers,
):
    """Verify that a commit can be reconstructed correctly.

    Args:
        target_git_object_retriever: Object retriever for the target repository.
        lookup_object: Function to look up Git objects by SHA.
        o: Original Git commit object.
        rev: Bazaar revision object.
        ret_tree: Reconstructed tree.
        parent_trees: Parent trees.
        mapping: Mapping between Git and Bazaar.
        unusual_modes: Dictionary of unusual file modes.
        verifiers: Verifier information.

    Raises:
        AssertionError: If reconstruction fails or differs from original.
    """
    new_unusual_modes = mapping.export_unusual_file_modes(rev)
    if new_unusual_modes != unusual_modes:
        raise AssertionError(
            f"unusual modes don't match: {unusual_modes!r} != {new_unusual_modes!r}"
        )
    # Verify that we can reconstruct the commit properly
    rec_o = target_git_object_retriever._reconstruct_commit(
        rev, o.tree, True, verifiers
    )
    if rec_o != o:
        raise AssertionError(f"Reconstructed commit differs: {rec_o!r} != {o!r}")
    diff = []
    new_objs = {}
    for path, obj, _ie in _tree_to_objects(
        ret_tree,
        parent_trees,
        target_git_object_retriever._cache.idmap,
        unusual_modes,
        mapping.BZR_DUMMY_FILE,
    ):
        old_obj_id = tree_lookup_path(lookup_object, o.tree, path)[1]
        new_objs[path] = obj
        if obj.id != old_obj_id:
            diff.append((path, lookup_object(old_obj_id), obj))
    for path, old_obj, new_obj in diff:
        while (
            old_obj.type_name == "tree"
            and new_obj.type_name == "tree"
            and sorted(old_obj) == sorted(new_obj)
        ):
            for name in old_obj:
                if old_obj[name][0] != new_obj[name][0]:
                    raise AssertionError(
                        f"Modes for {path} differ: {old_obj[name][0]:o} != {new_obj[name][0]:o}"
                    )
                if old_obj[name][1] != new_obj[name][1]:
                    # Found a differing child, delve deeper
                    path = posixpath.join(path, name)
                    old_obj = lookup_object(old_obj[name][1])
                    new_obj = new_objs[path]
                    break
        raise AssertionError(f"objects differ for {path}: {old_obj!r} != {new_obj!r}")


def ensure_inventories_in_repo(repo, trees):
    """Ensure that inventories for given trees are present in the repository.

    Args:
        repo: Repository to add inventories to.
        trees: List of trees whose inventories should be present.
    """
    real_inv_vf = repo.inventories.without_fallbacks()
    for t in trees:
        revid = t.get_revision_id()
        if not real_inv_vf.get_parent_map([(revid,)]):
            repo.add_inventory(revid, t.root_inventory, t.get_parent_ids())


def import_git_commit(
    repo, mapping, head, lookup_object, target_git_object_retriever, trees_cache, strict
):
    """Import a Git commit into a Bazaar repository.

    Args:
        repo: Target Bazaar repository.
        mapping: Mapping between Git and Bazaar.
        head: Git commit SHA to import.
        lookup_object: Function to look up Git objects.
        target_git_object_retriever: Object retriever for the target.
        trees_cache: Cache for revision trees.
        strict: Whether to use strict mode.

    Returns:
        tuple: (revision, testament3_sha1) if testament was created, else (revision, None).
    """
    o = lookup_object(head)
    # Note that this uses mapping.revision_id_foreign_to_bzr. If the parents
    # were bzr roundtripped revisions they would be specified in the
    # roundtrip data.
    rev, roundtrip_revid, verifiers = mapping.import_commit(
        o, mapping.revision_id_foreign_to_bzr, strict
    )
    if roundtrip_revid is not None:
        original_revid = rev.revision_id
        rev.revision_id = roundtrip_revid
    # We have to do this here, since we have to walk the tree and
    # we need to make sure to import the blobs / trees with the right
    # path; this may involve adding them more than once.
    parent_trees = trees_cache.revision_trees(rev.parent_ids)
    ensure_inventories_in_repo(repo, parent_trees)
    if parent_trees == []:
        base_bzr_tree = trees_cache.revision_tree(NULL_REVISION)
        base_tree = None
        base_mode = None
    else:
        base_bzr_tree = parent_trees[0]
        base_tree = lookup_object(o.parents[0]).tree
        base_mode = stat.S_IFDIR
    store_updater = target_git_object_retriever._get_updater(rev)
    inv_delta, unusual_modes = import_git_tree(
        repo.texts,
        mapping,
        b"",
        b"",
        (base_tree, o.tree),
        base_bzr_tree,
        None,
        rev.revision_id,
        parent_trees,
        lookup_object,
        (base_mode, stat.S_IFDIR),
        store_updater,
        mapping.generate_file_id,
        allow_submodules=repo._format.supports_tree_reference,
    )
    if unusual_modes != {}:
        for path, mode in unusual_modes.iteritems():
            warn_unusual_mode(rev.foreign_revid, path, mode)
        mapping.import_unusual_file_modes(rev, unusual_modes)
    try:
        basis_id = rev.parent_ids[0]
    except IndexError:
        basis_id = NULL_REVISION
        base_bzr_inventory = None
    else:
        base_bzr_inventory = base_bzr_tree.root_inventory
    inv_delta = InventoryDelta(inv_delta)
    rev.inventory_sha1, inv = repo.add_inventory_by_delta(
        basis_id, inv_delta, rev.revision_id, rev.parent_ids, base_bzr_inventory
    )
    ret_tree = InventoryRevisionTree(repo, inv, rev.revision_id)
    # Check verifiers
    if verifiers and roundtrip_revid is not None:
        testament = StrictTestament3(rev, ret_tree)
        calculated_verifiers = {"testament3-sha1": testament.as_sha1()}
        if calculated_verifiers != verifiers:
            trace.mutter(
                "Testament SHA1 %r for %r did not match %r.",
                calculated_verifiers["testament3-sha1"],
                rev.revision_id,
                verifiers["testament3-sha1"],
            )
            rev.revision_id = original_revid
            rev.inventory_sha1, inv = repo.add_inventory_by_delta(
                basis_id, inv_delta, rev.revision_id, rev.parent_ids, base_bzr_tree
            )
            ret_tree = InventoryRevisionTree(repo, inv, rev.revision_id)
    else:
        calculated_verifiers = {}
    store_updater.add_object(o, calculated_verifiers, None)
    store_updater.finish()
    trees_cache.add(ret_tree)
    repo.add_revision(rev.revision_id, rev)
    if debug.debug_flag_enabled("verify"):
        verify_commit_reconstruction(
            target_git_object_retriever,
            lookup_object,
            o,
            rev,
            ret_tree,
            parent_trees,
            mapping,
            unusual_modes,
            verifiers,
        )


def import_git_objects(
    repo, mapping, object_iter, target_git_object_retriever, heads, pb=None, limit=None
):
    """Import a set of git objects into a bzr repository.

    :param repo: Target Bazaar repository
    :param mapping: Mapping to use
    :param object_iter: Iterator over Git objects.
    :return: Tuple with pack hints and last imported revision id
    """

    def lookup_object(sha):
        try:
            return object_iter[sha]
        except KeyError:
            return target_git_object_retriever[sha]

    graph = []
    checked = set()
    heads = list(set(heads))
    trees_cache = LRUTreeCache(repo)
    # Find and convert commit objects
    while heads:
        if pb is not None:
            pb.update("finding revisions to fetch", len(graph), None)
        head = heads.pop()
        if head == ZERO_SHA:
            continue
        if not isinstance(head, bytes):
            raise TypeError(head)
        try:
            o = lookup_object(head)
        except KeyError:
            continue
        if isinstance(o, Commit):
            rev, roundtrip_revid, verifiers = mapping.import_commit(
                o, mapping.revision_id_foreign_to_bzr, strict=True
            )
            if repo.has_revision(rev.revision_id) or (
                roundtrip_revid and repo.has_revision(roundtrip_revid)
            ):
                continue
            graph.append((o.id, o.parents))
            heads.extend([p for p in o.parents if p not in checked])
        elif isinstance(o, Tag):
            if o.object[1] not in checked:
                heads.append(o.object[1])
        else:
            trace.warning(f"Unable to import head object {o!r}")
        checked.add(o.id)
    del checked
    # Order the revisions
    # Create the inventory objects
    batch_size = 1000
    revision_ids = topo_sort(graph)
    pack_hints = []
    if limit is not None:
        revision_ids = revision_ids[:limit]
    last_imported = None
    for offset in range(0, len(revision_ids), batch_size):
        target_git_object_retriever.start_write_group()
        try:
            repo.start_write_group()
            try:
                for i, head in enumerate(revision_ids[offset : offset + batch_size]):
                    if pb is not None:
                        pb.update("fetching revisions", offset + i, len(revision_ids))
                    import_git_commit(
                        repo,
                        mapping,
                        head,
                        lookup_object,
                        target_git_object_retriever,
                        trees_cache,
                        strict=True,
                    )
                    last_imported = head
            except BaseException:
                repo.abort_write_group()
                raise
            else:
                hint = repo.commit_write_group()
                if hint is not None:
                    pack_hints.extend(hint)
        except BaseException:
            target_git_object_retriever.abort_write_group()
            raise
        else:
            target_git_object_retriever.commit_write_group()
    return pack_hints, last_imported


class DetermineWantsRecorder:
    """Recorder for determine_wants calls in Git fetch operations."""

    def __init__(self, actual):
        """Initialize the recorder.

        Args:
            actual: The actual determine_wants function to wrap.
        """
        self.actual = actual
        self.wants = []
        self.remote_refs = {}

    def __call__(self, refs):
        """Record refs and determine wants.

        Args:
            refs: Dictionary of remote references.

        Returns:
            List of wanted refs.

        Raises:
            TypeError: If refs is not a dictionary.
        """
        if not isinstance(refs, dict):
            raise TypeError(refs)
        self.remote_refs = refs
        self.wants = self.actual(refs)
        return self.wants
