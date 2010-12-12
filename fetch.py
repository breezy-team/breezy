# Copyright (C) 2008-2010 Jelmer Vernooij <jelmer@samba.org>
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

from dulwich.objects import (
    Commit,
    Tag,
    Tree,
    S_ISGITLINK,
    )
from dulwich.object_store import (
    tree_lookup_path,
    )
from itertools import (
    imap,
    )
import posixpath
import re
import stat

from bzrlib import (
    debug,
    osutils,
    trace,
    ui,
    )
from bzrlib.errors import (
    BzrError,
    NoSuchId,
    )
from bzrlib.inventory import (
    Inventory,
    InventoryDirectory,
    InventoryFile,
    InventoryLink,
    TreeReference,
    )
from bzrlib.repository import (
    InterRepository,
    )
from bzrlib.revision import (
    NULL_REVISION,
    )
from bzrlib.revisiontree import (
    RevisionTree,
    )
from bzrlib.testament import (
    StrictTestament3,
    )
from bzrlib.tsort import (
    topo_sort,
    )
from bzrlib.versionedfile import (
    ChunkedContentFactory,
    )

from bzrlib.plugins.git.mapping import (
    DEFAULT_FILE_MODE,
    mode_is_executable,
    mode_kind,
    warn_unusual_mode,
    )
from bzrlib.plugins.git.object_store import (
    BazaarObjectStore,
    LRUTreeCache,
    _tree_to_objects,
    )
from bzrlib.plugins.git.remote import (
    RemoteGitRepository,
    )
from bzrlib.plugins.git.repository import (
    GitRepository,
    GitRepositoryFormat,
    LocalGitRepository,
    )


def import_git_blob(texts, mapping, path, name, (base_hexsha, hexsha), 
        base_inv, parent_id, revision_id,
        parent_invs, lookup_object, (base_mode, mode), store_updater,
        lookup_file_id):
    """Import a git blob object into a bzr repository.

    :param texts: VersionedFiles to add to
    :param path: Path in the tree
    :param blob: A git blob
    :return: Inventory delta for this file
    """
    if mapping.is_control_file(path):
        return []
    if base_hexsha == hexsha and base_mode == mode:
        # If nothing has changed since the base revision, we're done
        return []
    file_id = lookup_file_id(path)
    if stat.S_ISLNK(mode):
        cls = InventoryLink
    else:
        cls = InventoryFile
    ie = cls(file_id, name.decode("utf-8"), parent_id)
    if ie.kind == "file":
        ie.executable = mode_is_executable(mode)
    if base_hexsha == hexsha and mode_kind(base_mode) == mode_kind(mode):
        base_ie = base_inv[base_inv.path2id(path)]
        ie.text_size = base_ie.text_size
        ie.text_sha1 = base_ie.text_sha1
        if ie.kind == "symlink":
            ie.symlink_target = base_ie.symlink_target
        if ie.executable == base_ie.executable:
            ie.revision = base_ie.revision
        else:
            blob = lookup_object(hexsha)
    else:
        blob = lookup_object(hexsha)
        if ie.kind == "symlink":
            ie.revision = None
            ie.symlink_target = blob.data
        else:
            ie.text_size = sum(imap(len, blob.chunked))
            ie.text_sha1 = osutils.sha_strings(blob.chunked)
    # Check what revision we should store
    parent_keys = []
    for pinv in parent_invs:
        try:
            pie = pinv[file_id]
        except NoSuchId:
            continue
        if (pie.text_sha1 == ie.text_sha1 and
            pie.executable == ie.executable and
            pie.symlink_target == ie.symlink_target):
            # found a revision in one of the parents to use
            ie.revision = pie.revision
            break
        parent_key = (file_id, pie.revision)
        if not parent_key in parent_keys:
            parent_keys.append(parent_key)
    if ie.revision is None:
        # Need to store a new revision
        ie.revision = revision_id
        assert ie.revision is not None
        if ie.kind == 'symlink':
            chunks = []
        else: 
            chunks = blob.chunked
        texts.insert_record_stream([
            ChunkedContentFactory((file_id, ie.revision),
                tuple(parent_keys), ie.text_sha1, chunks)])
    invdelta = []
    if base_hexsha is not None:
        old_path = path.decode("utf-8") # Renames are not supported yet
        if stat.S_ISDIR(base_mode):
            invdelta.extend(remove_disappeared_children(base_inv, old_path,
                lookup_object(base_hexsha), [], lookup_object))
    else:
        old_path = None
    new_path = path.decode("utf-8")
    invdelta.append((old_path, new_path, file_id, ie))
    if base_hexsha != hexsha:
        store_updater.add_object(blob, ie, path)
    return invdelta


class SubmodulesRequireSubtrees(BzrError):
    _fmt = """The repository you are fetching from contains submodules. To continue, upgrade your Bazaar repository to a format that supports nested trees, such as 'development-subtree'."""
    internal = False


def import_git_submodule(texts, mapping, path, name, (base_hexsha, hexsha),
    base_inv, parent_id, revision_id, parent_invs, lookup_object,
    (base_mode, mode), store_updater, lookup_file_id):
    if base_hexsha == hexsha and base_mode == mode:
        return [], {}
    file_id = lookup_file_id(path)
    ie = TreeReference(file_id, name.decode("utf-8"), parent_id)
    ie.revision = revision_id
    if base_hexsha is None:
        oldpath = None
    else:
        oldpath = path
    ie.reference_revision = mapping.revision_id_foreign_to_bzr(hexsha)
    texts.insert_record_stream([
        ChunkedContentFactory((file_id, ie.revision), (), None, [])])
    invdelta = [(oldpath, path, file_id, ie)]
    return invdelta, {}


def remove_disappeared_children(base_inv, path, base_tree, existing_children,
        lookup_object):
    """Generate an inventory delta for removed children.

    :param base_inv: Base inventory against which to generate the 
        inventory delta.
    :param path: Path to process (unicode)
    :param base_tree: Git Tree base object
    :param existing_children: Children that still exist
    :param lookup_object: Lookup a git object by its SHA1
    :return: Inventory delta, as list
    """
    assert type(path) is unicode
    ret = []
    for name, mode, hexsha in base_tree.iteritems():
        if name in existing_children:
            continue
        c_path = posixpath.join(path, name.decode("utf-8"))
        file_id = base_inv.path2id(c_path)
        assert file_id is not None
        ret.append((c_path, None, file_id, None))
        if stat.S_ISDIR(mode):
            ret.extend(remove_disappeared_children(
                base_inv, c_path, lookup_object(hexsha), [], lookup_object))
    return ret


def import_git_tree(texts, mapping, path, name, (base_hexsha, hexsha),
        base_inv, parent_id, revision_id, parent_invs,
        lookup_object, (base_mode, mode), store_updater,
        lookup_file_id, allow_submodules=False):
    """Import a git tree object into a bzr repository.

    :param texts: VersionedFiles object to add to
    :param path: Path in the tree (str)
    :param name: Name of the tree (str)
    :param tree: A git tree object
    :param base_inv: Base inventory against which to return inventory delta
    :return: Inventory delta for this subtree
    """
    assert type(path) is str
    assert type(name) is str
    if base_hexsha == hexsha and base_mode == mode:
        # If nothing has changed since the base revision, we're done
        return [], {}
    invdelta = []
    file_id = lookup_file_id(path)
    # We just have to hope this is indeed utf-8:
    ie = InventoryDirectory(file_id, name.decode("utf-8"), parent_id)
    tree = lookup_object(hexsha)
    if base_hexsha is None:
        base_tree = None
        old_path = None # Newly appeared here
    else:
        base_tree = lookup_object(base_hexsha)
        old_path = path.decode("utf-8") # Renames aren't supported yet
    new_path = path.decode("utf-8")
    if base_tree is None or type(base_tree) is not Tree:
        ie.revision = revision_id
        invdelta.append((old_path, new_path, ie.file_id, ie))
        texts.insert_record_stream([
            ChunkedContentFactory((ie.file_id, ie.revision), (), None, [])])
    # Remember for next time
    existing_children = set()
    child_modes = {}
    for child_mode, name, child_hexsha in tree.entries():
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
            subinvdelta, grandchildmodes = import_git_tree(texts, mapping,
                child_path, name, (child_base_hexsha, child_hexsha), base_inv,
                file_id, revision_id, parent_invs, lookup_object,
                (child_base_mode, child_mode), store_updater, lookup_file_id,
                allow_submodules=allow_submodules)
        elif S_ISGITLINK(child_mode): # submodule
            if not allow_submodules:
                raise SubmodulesRequireSubtrees()
            subinvdelta, grandchildmodes = import_git_submodule(texts, mapping,
                child_path, name, (child_base_hexsha, child_hexsha), base_inv,
                file_id, revision_id, parent_invs, lookup_object,
                (child_base_mode, child_mode), store_updater, lookup_file_id)
        else:
            subinvdelta = import_git_blob(texts, mapping, child_path, name,
                (child_base_hexsha, child_hexsha), base_inv, file_id,
                revision_id, parent_invs, lookup_object,
                (child_base_mode, child_mode), store_updater, lookup_file_id)
            grandchildmodes = {}
        child_modes.update(grandchildmodes)
        invdelta.extend(subinvdelta)
        if child_mode not in (stat.S_IFDIR, DEFAULT_FILE_MODE,
                        stat.S_IFLNK, DEFAULT_FILE_MODE|0111):
            child_modes[child_path] = child_mode
    # Remove any children that have disappeared
    if base_tree is not None and type(base_tree) is Tree:
        invdelta.extend(remove_disappeared_children(base_inv, old_path,
            base_tree, existing_children, lookup_object))
    store_updater.add_object(tree, ie, path)
    return invdelta, child_modes


def verify_commit_reconstruction(target_git_object_retriever, lookup_object,
    o, rev, ret_tree, parent_trees, mapping, unusual_modes, verifiers):
    new_unusual_modes = mapping.export_unusual_file_modes(rev)
    if new_unusual_modes != unusual_modes:
        raise AssertionError("unusual modes don't match: %r != %r" % (
            unusual_modes, new_unusual_modes))
    # Verify that we can reconstruct the commit properly
    rec_o = target_git_object_retriever._reconstruct_commit(rev, o.tree, True,
        verifiers)
    if rec_o != o:
        raise AssertionError("Reconstructed commit differs: %r != %r" % (
            rec_o, o))
    diff = []
    new_objs = {}
    for path, obj, ie in _tree_to_objects(ret_tree, parent_trees,
        target_git_object_retriever._cache.idmap, unusual_modes, mapping.BZR_DUMMY_FILE):
        old_obj_id = tree_lookup_path(lookup_object, o.tree, path)[1]
        new_objs[path] = obj
        if obj.id != old_obj_id:
            diff.append((path, lookup_object(old_obj_id), obj))
    for (path, old_obj, new_obj) in diff:
        while (old_obj.type_name == "tree" and
               new_obj.type_name == "tree" and
               sorted(old_obj) == sorted(new_obj)):
            for name in old_obj:
                if old_obj[name][0] != new_obj[name][0]:
                    raise AssertionError("Modes for %s differ: %o != %o" %
                        (path, old_obj[name][0], new_obj[name][0]))
                if old_obj[name][1] != new_obj[name][1]:
                    # Found a differing child, delve deeper
                    path = posixpath.join(path, name)
                    old_obj = lookup_object(old_obj[name][1])
                    new_obj = new_objs[path]
                    break
        raise AssertionError("objects differ for %s: %r != %r" % (path,
            old_obj, new_obj))


def import_git_commit(repo, mapping, head, lookup_object,
                      target_git_object_retriever, trees_cache):
    o = lookup_object(head)
    rev, roundtrip_revid, verifiers = mapping.import_commit(o,
            lambda x: target_git_object_retriever.lookup_git_sha(x)[1][0])
    # We have to do this here, since we have to walk the tree and
    # we need to make sure to import the blobs / trees with the right
    # path; this may involve adding them more than once.
    parent_trees = trees_cache.revision_trees(rev.parent_ids)
    if parent_trees == []:
        base_inv = Inventory(root_id=None)
        base_tree = None
        base_mode = None
    else:
        base_inv = parent_trees[0].inventory
        base_tree = lookup_object(o.parents[0]).tree
        base_mode = stat.S_IFDIR
    store_updater = target_git_object_retriever._get_updater(rev)
    fileid_map = mapping.get_fileid_map(lookup_object, o.tree)
    inv_delta, unusual_modes = import_git_tree(repo.texts,
            mapping, "", "", (base_tree, o.tree), base_inv,
            None, rev.revision_id, [p.inventory for p in parent_trees],
            lookup_object, (base_mode, stat.S_IFDIR), store_updater,
            fileid_map.lookup_file_id,
            allow_submodules=getattr(repo._format, "supports_tree_reference", False))
    if unusual_modes != {}:
        for path, mode in unusual_modes.iteritems():
            warn_unusual_mode(rev.foreign_revid, path, mode)
        mapping.import_unusual_file_modes(rev, unusual_modes)
    try:
        basis_id = rev.parent_ids[0]
    except IndexError:
        basis_id = NULL_REVISION
        base_inv = None
    rev.inventory_sha1, inv = repo.add_inventory_by_delta(basis_id,
              inv_delta, rev.revision_id, rev.parent_ids, base_inv)
    # Check verifiers
    testament = StrictTestament3(rev, inv)
    calculated_verifiers = { "testament3-sha1": testament.as_sha1() }
    if roundtrip_revid is not None:
        original_revid = rev.revision_id
        rev.revision_id = roundtrip_revid
        if calculated_verifiers != verifiers:
            trace.mutter("Testament SHA1 %r for %r did not match %r.",
                         calculated_verifiers["testament3-sha1"],
                         rev.revision_id, verifiers["testament3-sha1"])
            rev.revision_id = original_revid
    store_updater.add_object(o, calculated_verifiers, None)
    store_updater.finish()
    ret_tree = RevisionTree(repo, inv, rev.revision_id)
    trees_cache.add(ret_tree)
    repo.add_revision(rev.revision_id, rev)
    if "verify" in debug.debug_flags:
        verify_commit_reconstruction(target_git_object_retriever, 
            lookup_object, o, rev, ret_tree, parent_trees, mapping,
            unusual_modes, verifiers)


def import_git_objects(repo, mapping, object_iter,
    target_git_object_retriever, heads, pb=None, limit=None):
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
        assert isinstance(head, str)
        try:
            o = lookup_object(head)
        except KeyError:
            continue
        if isinstance(o, Commit):
            rev, roundtrip_revid, verifiers = mapping.import_commit(o,
                lambda x: None)
            if (repo.has_revision(rev.revision_id) or
                (roundtrip_revid and repo.has_revision(roundtrip_revid))):
                continue
            graph.append((o.id, o.parents))
            heads.extend([p for p in o.parents if p not in checked])
        elif isinstance(o, Tag):
            if o.object[1] not in checked:
                heads.append(o.object[1])
        else:
            trace.warning("Unable to import head object %r" % o)
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
                for i, head in enumerate(
                    revision_ids[offset:offset+batch_size]):
                    if pb is not None:
                        pb.update("fetching revisions", offset+i,
                                  len(revision_ids))
                    import_git_commit(repo, mapping, head, lookup_object,
                        target_git_object_retriever, trees_cache)
                    last_imported = head
            except:
                repo.abort_write_group()
                raise
            else:
                hint = repo.commit_write_group()
                if hint is not None:
                    pack_hints.extend(hint)
        except:
            target_git_object_retriever.abort_write_group()
            raise
        else:
            target_git_object_retriever.commit_write_group()
    return pack_hints, last_imported


class InterGitRepository(InterRepository):

    _matching_repo_format = GitRepositoryFormat()

    @staticmethod
    def _get_repo_format_to_test():
        return None

    def copy_content(self, revision_id=None, pb=None):
        """See InterRepository.copy_content."""
        self.fetch(revision_id, pb, find_ghosts=False)


class InterGitNonGitRepository(InterGitRepository):
    """Base InterRepository that copies revisions from a Git into a non-Git
    repository."""

    def fetch_objects(self, determine_wants, mapping, pb=None, limit=None):
        """Fetch objects from a remote server.

        :param determine_wants: determine_wants callback
        :param mapping: BzrGitMapping to use
        :param pb: Optional progress bar
        :param limit: Maximum number of commits to import.
        :return: Tuple with pack hint, last imported revision id and remote refs
        """
        raise NotImplementedError(self.fetch_objects)

    def fetch(self, revision_id=None, pb=None, find_ghosts=False,
              mapping=None, fetch_spec=None):
        if mapping is None:
            mapping = self.source.get_mapping()
        if revision_id is not None:
            interesting_heads = [revision_id]
        elif fetch_spec is not None:
            interesting_heads = fetch_spec.heads
        else:
            interesting_heads = None
        def determine_wants(refs):
            if interesting_heads is None:
                ret = [sha for (ref, sha) in refs.iteritems() if not ref.endswith("^{}")]
            else:
                ret = [self.source.lookup_bzr_revision_id(revid)[0] for revid in interesting_heads if revid not in (None, NULL_REVISION)]
            return [rev for rev in ret if not self.target.has_revision(self.source.lookup_foreign_revision_id(rev))]
        (pack_hint, _, remote_refs) = self.fetch_objects(determine_wants, mapping, pb)
        if pack_hint is not None and self.target._format.pack_compresses:
            self.target.pack(hint=pack_hint)
        return remote_refs


_GIT_PROGRESS_RE = re.compile(r"(.*?): +(\d+)% \((\d+)/(\d+)\)")
def report_git_progress(pb, text):
    text = text.rstrip("\r\n")
    g = _GIT_PROGRESS_RE.match(text)
    if g is not None:
        (text, pct, current, total) = g.groups()
        pb.update(text, int(current), int(total))
    else:
        pb.update(text, 0, 0)


class DetermineWantsRecorder(object):

    def __init__(self, actual):
        self.actual = actual
        self.wants = []
        self.remote_refs = {}

    def __call__(self, refs):
        self.remote_refs = refs
        self.wants = self.actual(refs)
        return self.wants


class InterRemoteGitNonGitRepository(InterGitNonGitRepository):
    """InterRepository that copies revisions from a remote Git into a non-Git
    repository."""

    def get_target_heads(self):
        # FIXME: This should be more efficient
        all_revs = self.target.all_revision_ids()
        parent_map = self.target.get_parent_map(all_revs)
        all_parents = set()
        map(all_parents.update, parent_map.itervalues())
        return set(all_revs) - all_parents

    def fetch_objects(self, determine_wants, mapping, pb=None, limit=None):
        """See `InterGitNonGitRepository`."""
        def progress(text):
            report_git_progress(pb, text)
        store = BazaarObjectStore(self.target, mapping)
        self.target.lock_write()
        try:
            heads = self.get_target_heads()
            graph_walker = store.get_graph_walker(
                    [store._lookup_revision_sha1(head) for head in heads])
            wants_recorder = DetermineWantsRecorder(determine_wants)

            create_pb = None
            if pb is None:
                create_pb = pb = ui.ui_factory.nested_progress_bar()
            try:
                objects_iter = self.source.fetch_objects(
                    wants_recorder, graph_walker, store.get_raw,
                    progress)
                (pack_hint, last_rev) = import_git_objects(self.target, mapping,
                    objects_iter, store, wants_recorder.wants, pb, limit)
                return (pack_hint, last_rev, wants_recorder.remote_refs)
            finally:
                if create_pb:
                    create_pb.finished()
        finally:
            self.target.unlock()

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with GitRepository."""
        return (isinstance(source, RemoteGitRepository) and
                target.supports_rich_root() and
                not isinstance(target, GitRepository) and
                target.texts is not None)


class InterLocalGitNonGitRepository(InterGitNonGitRepository):
    """InterRepository that copies revisions from a local Git into a non-Git
    repository."""

    def fetch_objects(self, determine_wants, mapping, pb=None, limit=None):
        """See `InterGitNonGitRepository`."""
        remote_refs = self.source._git.get_refs()
        wants = determine_wants(remote_refs)
        create_pb = None
        if pb is None:
            create_pb = pb = ui.ui_factory.nested_progress_bar()
        target_git_object_retriever = BazaarObjectStore(self.target, mapping)
        try:
            self.target.lock_write()
            try:
                (pack_hint, last_rev) = import_git_objects(self.target, mapping,
                    self.source._git.object_store,
                    target_git_object_retriever, wants, pb, limit)
                return (pack_hint, last_rev, remote_refs)
            finally:
                self.target.unlock()
        finally:
            if create_pb:
                create_pb.finished()

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with GitRepository."""
        return (isinstance(source, LocalGitRepository) and
                target.supports_rich_root() and
                not isinstance(target, GitRepository) and
                target.texts is not None)


class InterGitGitRepository(InterGitRepository):
    """InterRepository that copies between Git repositories."""

    def fetch_objects(self, determine_wants, mapping, pb=None):
        def progress(text):
            trace.note("git: %s", text)
        graphwalker = self.target._git.get_graph_walker()
        if (isinstance(self.source, LocalGitRepository) and
            isinstance(self.target, LocalGitRepository)):
            refs = self.source._git.fetch(self.target._git, determine_wants,
                progress)
            return (None, None, refs)
        elif (isinstance(self.source, LocalGitRepository) and
              isinstance(self.target, RemoteGitRepository)):
            raise NotImplementedError
        elif (isinstance(self.source, RemoteGitRepository) and
              isinstance(self.target, LocalGitRepository)):
            f, commit = self.target._git.object_store.add_thin_pack()
            try:
                refs = self.source.bzrdir.root_transport.fetch_pack(
                    determine_wants, graphwalker, f.write, progress)
                commit()
                return (None, None, refs)
            except:
                f.close()
                raise
        else:
            raise AssertionError

    def fetch(self, revision_id=None, pb=None, find_ghosts=False,
              mapping=None, fetch_spec=None, branches=None):
        if mapping is None:
            mapping = self.source.get_mapping()
        r = self.target._git
        if revision_id is not None:
            args = [mapping.revision_id_bzr_to_foreign(revision_id)[0]]
        elif fetch_spec is not None:
            args = [mapping.revision_id_bzr_to_foreign(revid)[0] for revid in fetch_spec.heads]
        if branches is not None:
            determine_wants = lambda x: [x[y] for y in branches if not x[y] in r.object_store]
        elif fetch_spec is None and revision_id is None:
            determine_wants = r.object_store.determine_wants_all
        else:
            determine_wants = lambda x: [y for y in args if not y in r.object_store]
        self.fetch_objects(determine_wants, mapping)

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with GitRepository."""
        return (isinstance(source, GitRepository) and
                isinstance(target, GitRepository))
