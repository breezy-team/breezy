# Copyright (C) 2008 Jelmer Vernooij <jelmer@samba.org>
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

from cStringIO import (
    StringIO,
    )
import dulwich as git
from dulwich.client import (
    SimpleFetchGraphWalker,
    )
from dulwich.objects import (
    Commit,
    )

from bzrlib import (
    osutils,
    trace,
    ui,
    urlutils,
    )
from bzrlib.errors import (
    InvalidRevisionId,
    NoSuchRevision,
    )
from bzrlib.inventory import (
    Inventory,
    InventoryDirectory,
    InventoryFile,
    InventoryLink,
    )
from bzrlib.repository import (
    InterRepository,
    )
from bzrlib.revision import (
    NULL_REVISION,
    )
from bzrlib.tsort import (
    topo_sort,
    )

from bzrlib.plugins.git.converter import (
    GitObjectConverter,
    )
from bzrlib.plugins.git.repository import (
    LocalGitRepository, 
    GitRepository, 
    GitRepositoryFormat,
    )
from bzrlib.plugins.git.remote import (
    RemoteGitRepository,
    )


class BzrFetchGraphWalker(object):
    """GraphWalker implementation that uses a Bazaar repository."""

    def __init__(self, repository, mapping):
        self.repository = repository
        self.mapping = mapping
        self.done = set()
        self.heads = set(repository.all_revision_ids())
        self.parents = {}

    def __iter__(self):
        return iter(self.next, None)

    def ack(self, sha):
        revid = self.mapping.revision_id_foreign_to_bzr(sha)
        self.remove(revid)

    def remove(self, revid):
        self.done.add(revid)
        if revid in self.heads:
            self.heads.remove(revid)
        if revid in self.parents:
            for p in self.parents[revid]:
                self.remove(p)

    def next(self):
        while self.heads:
            ret = self.heads.pop()
            ps = self.repository.get_parent_map([ret])[ret]
            self.parents[ret] = ps
            self.heads.update([p for p in ps if not p in self.done])
            try:
                self.done.add(ret)
                return self.mapping.revision_id_bzr_to_foreign(ret)[0]
            except InvalidRevisionId:
                pass
        return None


def import_git_blob(texts, mapping, path, blob, base_inv, parent_id, 
    revision_id, parent_invs, shagitmap, executable):
    """Import a git blob object into a bzr repository.

    :param texts: VersionedFiles to add to
    :param path: Path in the tree
    :param blob: A git blob
    :return: Inventory delta for this file
    """
    file_id = mapping.generate_file_id(path)
    # We just have to hope this is indeed utf-8:
    ie = InventoryFile(file_id, urlutils.basename(path).decode("utf-8"), 
        parent_id)
    ie.text_size = len(blob.data)
    ie.text_sha1 = osutils.sha_string(blob.data)
    ie.executable = executable
    # If there were no changes compared to the base inventory, there's no need 
    # for a delta
    if (file_id in base_inv and 
        base_inv[file_id].parent_id == ie.parent_id and
        base_inv[file_id].text_sha1 == ie.text_sha1 and
        base_inv[file_id].executable == ie.executable):
        return []
    # Check what revision we should store
    parent_keys = []
    for pinv in parent_invs:
        if not file_id in pinv:
            continue
        if pinv[file_id].text_sha1 == ie.text_sha1:
            # found a revision in one of the parents to use
            ie.revision = pinv[file_id].revision
            break
        parent_keys.append((file_id, pinv[file_id].revision))
    if ie.revision is None:
        # Need to store a new revision
        ie.revision = revision_id
        assert file_id is not None
        assert ie.revision is not None
        texts.add_lines((file_id, ie.revision), parent_keys,
            osutils.split_lines(blob.data))
        shagitmap.add_entry(blob.sha().hexdigest(), "blob",
            (ie.file_id, ie.revision))
    if file_id in base_inv:
        old_path = base_inv.id2path(file_id)
    else:
        old_path = None
    return [(old_path, path, file_id, ie)]


def import_git_tree(texts, mapping, path, tree, base_inv, parent_id, 
    revision_id, parent_invs, shagitmap, lookup_object):
    """Import a git tree object into a bzr repository.

    :param texts: VersionedFiles object to add to
    :param path: Path in the tree
    :param tree: A git tree object
    :param base_inv: Base inventory against which to return inventory delta
    :return: Inventory delta for this subtree
    """
    ret = []
    file_id = mapping.generate_file_id(path)
    # We just have to hope this is indeed utf-8:
    ie = InventoryDirectory(file_id, urlutils.basename(path.decode("utf-8")), 
        parent_id)
    if not file_id in base_inv:
        # Newly appeared here
        ie.revision = revision_id
        texts.add_lines((file_id, ie.revision), [], [])
        ret.append((None, path, file_id, ie))
    else:
        # See if this has changed at all
        try:
            base_sha = shagitmap.lookup_tree(path, base_inv.revision_id)
        except KeyError:
            pass
        else:
            if tree_sha == tree.id:
                # If nothing has changed since the base revision, we're done
                return []
    # Remember for next time
    shagitmap.add_entry(tree.id, "tree", (file_id, revision_id))
    existing_children = set()
    for mode, name, hexsha in tree.entries():
        entry_kind = (mode & 0700000) / 0100000
        basename = name.decode("utf-8")
        existing_children.add(basename)
        if path == "":
            child_path = name
        else:
            child_path = urlutils.join(path, name)
        obj = lookup_object(hexsha)
        if entry_kind == 0:
            ret.extend(import_git_tree(texts, mapping, child_path, obj, base_inv, 
                file_id, revision_id, parent_invs, shagitmap, lookup_object))
        elif entry_kind == 1:
            fs_mode = mode & 0777
            ret.extend(import_git_blob(texts, mapping, child_path, obj, base_inv, 
                file_id, revision_id, parent_invs, shagitmap, 
                bool(fs_mode & 0111)))
        else:
            raise AssertionError("Unknown blob kind, perms=%r." % (mode,))
    # Remove any children that have disappeared
    if file_id in base_inv:
        for x in set(base_inv[file_id].children).difference(existing_children):
            # TODO: Remove recursively if child is a directory
            child_file_id = base_inv[file_id].children[x].file_id
            ret.append((base_inv.id2path(child_file_id), None, child_file_id,
                        None))
    return ret


def import_git_objects(repo, mapping, object_iter, target_git_object_retriever, 
        heads, pb=None):
    """Import a set of git objects into a bzr repository.

    :param repo: Bazaar repository
    :param mapping: Mapping to use
    :param object_iter: Iterator over Git objects.
    """
    # TODO: a more (memory-)efficient implementation of this
    graph = []
    root_trees = {}
    revisions = {}
    checked = set()
    heads = list(heads)
    # Find and convert commit objects
    while heads:
        if pb is not None:
            pb.update("finding revisions to fetch", len(graph), None)
        head = heads.pop()
        assert isinstance(head, str)
        o = object_iter[head]
        if isinstance(o, Commit):
            rev = mapping.import_commit(o)
            if repo.has_revision(rev.revision_id):
                continue
            root_trees[rev.revision_id] = o.tree
            revisions[rev.revision_id] = rev
            graph.append((rev.revision_id, rev.parent_ids))
            target_git_object_retriever._idmap.add_entry(o.sha().hexdigest(),
                "commit", (rev.revision_id, o._tree))
            heads.extend([p for p in o.parents if p not in checked])
        else:
            trace.warning("Unable to import head object %r" % o)
        checked.add(head)
    # Order the revisions
    # Create the inventory objects
    for i, revid in enumerate(topo_sort(graph)):
        if pb is not None:
            pb.update("fetching revisions", i, len(graph))
        root_tree = object_iter[root_trees[revid]]
        rev = revisions[revid]
        # We have to do this here, since we have to walk the tree and 
        # we need to make sure to import the blobs / trees with the right 
        # path; this may involve adding them more than once.
        def lookup_object(sha):
            if sha in object_iter:
                return object_iter[sha]
            return target_git_object_retriever[sha]
        parent_invs = list(repo.iter_inventories(rev.parent_ids))
        if parent_invs == []:
            base_inv = Inventory(root_id=None)
        else:
            base_inv = parent_invs[0]
        inv_delta = import_git_tree(repo.texts, mapping, "", root_tree, 
            base_inv, None, revid, parent_invs, 
            target_git_object_retriever._idmap, lookup_object)
        try:
            basis_id = rev.parent_ids[0]
        except IndexError:
            basis_id = NULL_REVISION
        rev.inventory_sha1, inv = repo.add_inventory_by_delta(basis_id,
                  inv_delta, rev.revision_id, rev.parent_ids)
        repo.add_revision(rev.revision_id, rev)
    target_git_object_retriever._idmap.commit()


class InterGitNonGitRepository(InterRepository):
    """InterRepository that copies revisions from a Git into a non-Git 
    repository."""

    _matching_repo_format = GitRepositoryFormat()

    @staticmethod
    def _get_repo_format_to_test():
        return None

    def copy_content(self, revision_id=None, pb=None):
        """See InterRepository.copy_content."""
        self.fetch(revision_id, pb, find_ghosts=False)

    def fetch_objects(self, determine_wants, mapping, pb=None):
        def progress(text):
            pb.update("git: %s" % text.rstrip("\r\n"), 0, 0)
        graph_walker = BzrFetchGraphWalker(self.target, mapping)
        create_pb = None
        if pb is None:
            create_pb = pb = ui.ui_factory.nested_progress_bar()
        target_git_object_retriever = GitObjectConverter(self.target, mapping)
        recorded_wants = []

        def record_determine_wants(heads):
            wants = determine_wants(heads)
            recorded_wants.extend(wants)
            return wants
        
        try:
            self.target.lock_write()
            try:
                self.target.start_write_group()
                try:
                    objects_iter = self.source.fetch_objects(
                                record_determine_wants, 
                                graph_walker, 
                                target_git_object_retriever.__getitem__, 
                                progress)
                    import_git_objects(self.target, mapping, objects_iter, 
                            target_git_object_retriever, recorded_wants, pb)
                finally:
                    self.target.commit_write_group()
            finally:
                self.target.unlock()
        finally:
            if create_pb:
                create_pb.finished()

    def fetch(self, revision_id=None, pb=None, find_ghosts=False, mapping=None,
            fetch_spec=None):
        self.fetch_refs(revision_id=revision_id, pb=pb, find_ghosts=find_ghosts,
                mapping=mapping, fetch_spec=fetch_spec)

    def fetch_refs(self, revision_id=None, pb=None, find_ghosts=False, 
              mapping=None, fetch_spec=None):
        if mapping is None:
            mapping = self.source.get_mapping()
        if revision_id is not None:
            interesting_heads = [revision_id]
        elif fetch_spec is not None:
            interesting_heads = fetch_spec.heads
        else:
            interesting_heads = None
        self._refs = {}
        def determine_wants(refs):
            self._refs = refs
            if interesting_heads is None:
                ret = [sha for (ref, sha) in refs.iteritems() if not ref.endswith("^{}")]
            else:
                ret = [mapping.revision_id_bzr_to_foreign(revid)[0] for revid in interesting_heads]
            return [rev for rev in ret if not self.target.has_revision(mapping.revision_id_foreign_to_bzr(rev))]
        self.fetch_objects(determine_wants, mapping, pb)
        return self._refs

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with GitRepository."""
        # FIXME: Also check target uses VersionedFile
        return (isinstance(source, GitRepository) and 
                target.supports_rich_root() and
                not isinstance(target, GitRepository))


class InterGitRepository(InterRepository):
    """InterRepository that copies between Git repositories."""

    _matching_repo_format = GitRepositoryFormat()

    @staticmethod
    def _get_repo_format_to_test():
        return None

    def copy_content(self, revision_id=None, pb=None):
        """See InterRepository.copy_content."""
        self.fetch(revision_id, pb, find_ghosts=False)

    def fetch(self, revision_id=None, pb=None, find_ghosts=False, 
              mapping=None, fetch_spec=None):
        if mapping is None:
            mapping = self.source.get_mapping()
        def progress(text):
            trace.info("git: %s", text)
        r = self.target._git
        if revision_id is not None:
            args = [mapping.revision_id_bzr_to_foreign(revision_id)[0]]
        elif fetch_spec is not None:
            args = [mapping.revision_id_bzr_to_foreign(revid)[0] for revid in fetch_spec.heads]
        if fetch_spec is None and revision_id is None:
            determine_wants = r.object_store.determine_wants_all
        else:
            determine_wants = lambda x: [y for y in args if not y in r.object_store]

        graphwalker = SimpleFetchGraphWalker(r.heads().values(), r.get_parents)
        f, commit = r.object_store.add_pack()
        try:
            self.source._git.fetch_pack(path, determine_wants, graphwalker, f.write, progress)
            f.close()
            commit()
        except:
            f.close()
            raise

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with GitRepository."""
        return (isinstance(source, GitRepository) and 
                isinstance(target, GitRepository))
